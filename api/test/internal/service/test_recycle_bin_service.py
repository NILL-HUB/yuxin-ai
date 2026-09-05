from types import SimpleNamespace
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy.dialects import postgresql

from internal.exception import ForbiddenException, ValidateErrorException
from internal.model import RecycleBin
from internal.service import recycle_bin_service
from internal.service.recycle_bin_service import RecycleBinService
from internal.service import recycle_bin_handlers as handlers


class _Query:
    def __init__(self, items=None):
        self.filters = []
        self.items = items or []

    def filter(self, *args):
        self.filters.extend(args)
        return self

    def order_by(self, *_args):
        return self

    def offset(self, _offset):
        return self

    def limit(self, _limit):
        return self

    def count(self):
        return len(self.items)

    def all(self):
        return self.items


class _Session:
    def __init__(self, items=None):
        self.query_result = _Query(items)

    def query(self, *_args):
        return self.query_result


def test_list_user_items_only_exposes_user_visible_resource_types(monkeypatch):
    session = _Session()
    monkeypatch.setattr(
        recycle_bin_service,
        "db",
        SimpleNamespace(session=session),
    )

    RecycleBinService().list_user_items(account_id="acc-1")

    base_filters = session.query_result.filters[:3]
    assert len(base_filters) == 3
    type_expr = base_filters[2].compile(
        dialect=postgresql.dialect(),
        compile_kwargs={"literal_binds": True},
    )
    assert "recycle_bin.resource_type IN" in str(type_expr)
    for resource_type in RecycleBinService.USER_VISIBLE_RESOURCE_TYPES:
        assert resource_type in str(type_expr)
    assert "app" not in str(type_expr)


def test_delete_resource_rejects_user_source_for_admin_only_type(monkeypatch):
    monkeypatch.setattr(
        recycle_bin_service,
        "snapshot_resource",
        lambda *_args, **_kwargs: {},
    )

    with pytest.raises(ValidateErrorException):
        RecycleBinService().delete_resource(
            resource_type="app",
            resource_id="app-1",
            deleted_by="acc-1",
            deleted_by_type="user",
        )

    with pytest.raises(ValidateErrorException):
        RecycleBinService().delete_resource(
            resource_type="workflow",
            resource_id="wf-1",
            deleted_by="acc-1",
            deleted_by_type="agent",
        )


def test_check_user_owned_rejects_admin_only_resource_type():
    service = RecycleBinService()
    item = SimpleNamespace(
        id=1,
        resource_type="app",
        deleted_by_type="user",
        deleted_by="acc-1",
    )

    with pytest.raises(ForbiddenException):
        service._check_user_owned(item, "acc-1")


def test_check_user_owned_rejects_other_account_and_admin_source():
    service = RecycleBinService()
    user_item = SimpleNamespace(
        id=2,
        resource_type="memory",
        deleted_by_type="user",
        deleted_by="acc-1",
    )
    with pytest.raises(ForbiddenException):
        service._check_user_owned(user_item, "acc-2")

    admin_item = SimpleNamespace(
        id=3,
        resource_type="knowledge_base",
        deleted_by_type="admin",
        deleted_by="admin-1",
    )
    with pytest.raises(ForbiddenException):
        service._check_user_owned(admin_item, "admin-1")


def test_check_user_owned_allows_own_user_visible_item():
    service = RecycleBinService()
    item = SimpleNamespace(
        id=4,
        resource_type="knowledge_document",
        deleted_by_type="agent",
        deleted_by="acc-1",
    )

    service._check_user_owned(item, "acc-1")


# ---------------------------------------------------------------------------
# 到期销毁：恢复截止校验 + purge 失败保护
# ---------------------------------------------------------------------------
def _utcnow_naive_test():
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _expired_item(extra=None):
    data = {
        "id": 100,
        "status": "pending",
        "expire_at": _utcnow_naive_test() - timedelta(seconds=1),
        "resource_type": "app",
        "snapshot": {"main": {"id": "app-1"}},
        "deleted_by_type": "admin",
        "deleted_by": None,
        "remark": "",
    }
    if extra:
        data.update(extra)
    return SimpleNamespace(**data)


def test_restore_item_rejects_pending_item_past_expire_at(monkeypatch):
    """已到留存期但尚未被 celery purge 的 pending 条目必须拒绝恢复。"""
    item = _expired_item()
    monkeypatch.setattr(RecycleBinService, "get_item", lambda self, item_id: item)
    # 即使 restore_resource 能成功，也不应被调用（到期即不可恢复）
    monkeypatch.setattr(
        recycle_bin_service,
        "restore_resource",
        lambda *_a, **_k: (_ for _ in ()).throw(AssertionError("restore_resource 不应被调用")),
    )

    with pytest.raises(ValidateErrorException) as exc_info:
        RecycleBinService().restore_item(item.id)

    assert "留存期" in str(exc_info.value) or "销毁" in str(exc_info.value)


def test_restore_user_item_rejects_expired_pending_item(monkeypatch):
    """用户端到期 pending 条目同样必须拒绝恢复。"""
    item = _expired_item(
        {
            "resource_type": "memory",
            "deleted_by_type": "user",
            "deleted_by": "acc-1",
        }
    )
    monkeypatch.setattr(RecycleBinService, "get_item", lambda self, item_id: item)
    # 归属校验走真实方法，但阻止 DB 查询返回
    monkeypatch.setattr(
        recycle_bin_service,
        "_utcnow_naive",
        _utcnow_naive_test,
    )
    monkeypatch.setattr(
        recycle_bin_service,
        "restore_resource",
        lambda *_a, **_k: (_ for _ in ()).throw(AssertionError("restore_resource 不应被调用")),
    )

    with pytest.raises(ValidateErrorException) as exc_info:
        RecycleBinService().restore_user_item(item.id, "acc-1")

    assert "留存期" in str(exc_info.value) or "销毁" in str(exc_info.value)


def test_purge_expired_keeps_pending_when_purge_fails(monkeypatch):
    """purge 抛异常时条目必须保持 pending（不能误标 expired），并记录失败原因。"""
    records = {
        "id101": _expired_item({"id": 101}),
        "id102": _expired_item({"id": 102}),
    }
    committed = []

    class _Session:
        def query(self, *_a):
            return _Query(records)

        def commit(self):
            committed.append(True)

    class _Query:
        def __init__(self, records):
            self.records = records

        def filter(self, *_a):
            return self

        def all(self):
            return list(self.records.values())

    monkeypatch.setattr(recycle_bin_service, "db", SimpleNamespace(session=_Session()))
    monkeypatch.setattr(
        recycle_bin_service,
        "purge_resource",
        lambda resource_type, snapshot: (_ for _ in ()).throw(RuntimeError("worker 不可达")),
    )

    result = RecycleBinService().purge_expired()

    assert result["failed"] == 2
    assert result["purged"] == 0
    for rec in records.values():
        assert rec.status == "pending"
        assert "销毁失败" in rec.remark


def test_purge_expired_marks_expired_when_purge_succeeds(monkeypatch):
    """purge 成功时条目标记 expired 且 remark 记录销毁时间。"""
    records = {"id103": _expired_item({"id": 103})}
    committed = []
    now = _utcnow_naive_test()

    class _Session:
        def query(self, *_a):
            return _Query(records)

        def commit(self):
            committed.append(True)

    class _Query:
        def __init__(self, records):
            self.records = records

        def filter(self, *_a):
            return self

        def all(self):
            return list(self.records.values())

    monkeypatch.setattr(recycle_bin_service, "db", SimpleNamespace(session=_Session()))
    monkeypatch.setattr(recycle_bin_service, "purge_resource", lambda resource_type, snapshot: None)
    monkeypatch.setattr(recycle_bin_service, "_utcnow_naive", lambda: now)

    result = RecycleBinService().purge_expired()

    assert result["purged"] == 1
    assert result["failed"] == 0
    assert records["id103"].status == "expired"
    assert "已彻底销毁" in records["id103"].remark


# ---------------------------------------------------------------------------
# 一键清理已销毁（expired）记录
# ---------------------------------------------------------------------------
def test_cleanup_expired_records_filters_only_expired(monkeypatch):
    """只删除 status=expired 的记录，且带账号/来源过滤。"""
    deleted = []

    class _Session:
        def query(self, *_a):
            return _Query()

        def commit(self):
            pass

    class _Query:
        def __init__(self):
            self.filters = []

        def filter(self, *args):
            self.filters.extend(args)
            return self

        def delete(self, synchronize_session=False):
            deleted.append(self.filters)
            return 3

    monkeypatch.setattr(recycle_bin_service, "db", SimpleNamespace(session=_Session()))

    count = RecycleBinService().cleanup_expired_records()
    assert count == 3
    assert len(deleted) == 1
    # 第一个 filter 必须是 status == expired
    status_expr = deleted[0][0].compile(
        dialect=postgresql.dialect(),
        compile_kwargs={"literal_binds": True},
    )
    assert "expired" in str(status_expr)


def test_cleanup_expired_records_scopes_by_account(monkeypatch):
    """account_id 传入时按账号归属过滤（user/agent 来源 + 用户可见类型）。"""
    deleted = []

    class _Session:
        def query(self, *_a):
            return _Query()

        def commit(self):
            pass

    class _Query:
        def __init__(self):
            self.filters = []

        def filter(self, *args):
            self.filters.extend(args)
            return self

        def delete(self, synchronize_session=False):
            deleted.append(self.filters)
            return 2

    monkeypatch.setattr(recycle_bin_service, "db", SimpleNamespace(session=_Session()))

    count = RecycleBinService().cleanup_expired_records(account_id="acc-1")
    assert count == 2
    joined = [str(f.compile(dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True})) for f in deleted[0]]
    joined_text = " ".join(joined)
    assert "expired" in joined_text
    assert "acc-1" in joined_text
    assert "recycle_bin.deleted_by_type IN" in joined_text
    for resource_type in RecycleBinService.USER_VISIBLE_RESOURCE_TYPES:
        assert resource_type in joined_text
