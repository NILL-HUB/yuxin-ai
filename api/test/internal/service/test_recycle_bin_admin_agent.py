"""回收站 admin_agent 来源测试（设计 §7.1）。

要覆盖的组合是「admin 专属资源 + Agent 来源」——该组合在当前代码下会抛
ValidateErrorException，是设计文档明确要求补测的缺口。

注意：本文件用 `workflow` 作为 admin 专属资源的代表（它在 RESOURCE_TYPES 中
且不在 USER_VISIBLE_RESOURCE_TYPES 中）。不要用 builtin_tool —— 它**不在**
RESOURCE_TYPES 里，会因"资源类型不支持"这一**无关原因**抛错，从而使
"admin_agent 是否放行 admin 专属资源"这条断言假通过。
"""
from types import SimpleNamespace
from uuid import uuid4

import pytest

import internal.service.recycle_bin_service as mod
from internal.exception import ValidateErrorException
from internal.service.recycle_bin_service import RecycleBinService


class _AutoCommit:
    def __init__(self):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def _service(monkeypatch, snapshot=None):
    """构造只测校验逻辑的服务实例：替换掉快照/物理删除/会话三处 I/O。"""
    monkeypatch.setattr(
        mod,
        "snapshot_resource",
        lambda resource_type, resource_id, resource_key="": (
            {"main": {"id": str(resource_id)}} if snapshot is None else snapshot
        ),
    )
    monkeypatch.setattr(mod, "physical_delete_resource", lambda *a, **kw: None)
    added: list = []
    session = SimpleNamespace(
        add=lambda obj: added.append(obj),
        flush=lambda: None,
        commit=lambda: None,
    )
    monkeypatch.setattr(mod, "db", SimpleNamespace(session=session))
    return RecycleBinService(), added


class TestAdminAgentSource:
    def test_admin_only_resource_can_be_deleted_by_admin_agent(self, monkeypatch):
        """核心缺口：admin 专属资源 + admin_agent 来源必须可入站。

        历史行为：以 deleted_by_type='agent' 传 admin 专属资源会抛
        ValidateErrorException，导致 Agent 代删系统资源在运行时不可达。
        """
        svc, added = _service(monkeypatch)
        agent_id = uuid4()
        ok = svc.delete_resource(
            resource_type="workflow",
            resource_id=uuid4(),
            deleted_by=uuid4(),
            deleted_by_type="admin_agent",
            agent_id=agent_id,
        )
        assert ok is True
        assert len(added) == 1
        item = added[0]
        assert item.deleted_by_type == "admin_agent"
        assert item.snapshot.get("_agent_id") == str(agent_id)

    def test_admin_agent_retention_defaults_to_30_days(self, monkeypatch):
        """admin_agent 来源留存默认 30 天（不是用户侧 agent 的 7 天）。"""
        svc, added = _service(monkeypatch)
        svc.delete_resource(
            resource_type="workflow",
            resource_id=uuid4(),
            deleted_by=uuid4(),
            deleted_by_type="admin_agent",
        )
        assert added[0].retention_days == 30

    def test_admin_agent_retention_respects_choices(self, monkeypatch):
        svc, added = _service(monkeypatch)
        svc.delete_resource(
            resource_type="workflow",
            resource_id=uuid4(),
            deleted_by=uuid4(),
            deleted_by_type="admin_agent",
            retention_days=90,
        )
        assert added[0].retention_days == 90

    def test_admin_agent_retention_falls_back_on_invalid_choice(self, monkeypatch):
        """非法留存天数回落 30（而非静默接受）。"""
        svc, added = _service(monkeypatch)
        svc.delete_resource(
            resource_type="workflow",
            resource_id=uuid4(),
            deleted_by=uuid4(),
            deleted_by_type="admin_agent",
            retention_days=45,
        )
        assert added[0].retention_days == 30

    def test_user_visible_resource_can_still_use_agent_source(self, monkeypatch):
        """既有 agent（用户侧）语义不受影响：仍固定 7 天。"""
        svc, added = _service(monkeypatch)
        svc.delete_resource(
            resource_type="os_file",
            resource_id=uuid4(),
            deleted_by=uuid4(),
            deleted_by_type="agent",
            agent_id=uuid4(),
        )
        assert added[0].deleted_by_type == "agent"
        assert added[0].retention_days == 7

    def test_agent_source_still_rejects_admin_only_resource(self, monkeypatch):
        """守卫：新分支不得放宽既有 agent 来源的约束（防越权回归）。"""
        svc, _ = _service(monkeypatch)
        with pytest.raises(ValidateErrorException):
            svc.delete_resource(
                resource_type="workflow",
                resource_id=uuid4(),
                deleted_by=uuid4(),
                deleted_by_type="agent",
            )

    def test_admin_agent_source_rejects_unknown_resource(self, monkeypatch):
        """不存在的资源类型仍被拒绝（守卫：新分支没有绕过类型白名单）。"""
        svc, _ = _service(monkeypatch)
        with pytest.raises(ValidateErrorException):
            svc.delete_resource(
                resource_type="not_a_resource",
                resource_id=uuid4(),
                deleted_by_type="admin_agent",
            )

    def test_unknown_source_still_normalizes_to_admin(self, monkeypatch):
        """既有语义：未知来源静默归一为 admin（不破坏兼容）。"""
        svc, added = _service(monkeypatch)
        svc.delete_resource(
            resource_type="workflow",
            resource_id=uuid4(),
            deleted_by=uuid4(),
            deleted_by_type="who_knows",
        )
        assert added[0].deleted_by_type == "admin"

    def test_admin_agent_source_does_not_write_agent_id_when_absent(self, monkeypatch):
        """未传 agent_id 时不得写入该键（与既有 agent 分支的条件写一致）。"""
        svc, added = _service(monkeypatch)
        svc.delete_resource(
            resource_type="workflow",
            resource_id=uuid4(),
            deleted_by=uuid4(),
            deleted_by_type="admin_agent",
        )
        assert "_agent_id" not in added[0].snapshot


class TestResourceTypeConstants:
    def test_admin_only_types_match_derivation(self):
        """ADMIN_ONLY_RESOURCE_TYPES 必须与派生结果一致。

        类体内无法用生成器派生（作用域限制），因此写成字面量；本用例守护
        它不在 RESOURCE_TYPES / USER_VISIBLE_RESOURCE_TYPES 变更后漂移。
        """
        derived = tuple(
            rt
            for rt in RecycleBinService.RESOURCE_TYPES
            if rt not in RecycleBinService.USER_VISIBLE_RESOURCE_TYPES
        )
        assert set(RecycleBinService.ADMIN_ONLY_RESOURCE_TYPES) == set(derived)

    def test_admin_only_and_user_visible_are_disjoint_and_cover_all(self):
        user_visible = set(RecycleBinService.USER_VISIBLE_RESOURCE_TYPES)
        admin_only = set(RecycleBinService.ADMIN_ONLY_RESOURCE_TYPES)
        assert user_visible & admin_only == set()
        assert user_visible | admin_only == set(RecycleBinService.RESOURCE_TYPES)


class TestAdminAgentListingFilter:
    def _capture_filters(self, monkeypatch, call):
        """拦截 list_items / overview 的 filter 表达式，编译成 SQL 文本。"""
        captured: list = []

        class _Q:
            def filter(self, *crits):
                captured.extend(crits)
                return self

            def with_entities(self, *a, **kw):
                return self

            def group_by(self, *a, **kw):
                return self

            def select_from(self, *a, **kw):
                return self

            def scalar(self):
                return 0

            def count(self):
                return 0

            def order_by(self, *a):
                return self

            def offset(self, *a):
                return self

            def limit(self, *a):
                return self

            def all(self):
                return []

        monkeypatch.setattr(mod, "db", SimpleNamespace(session=SimpleNamespace(query=lambda *a, **kw: _Q())))
        call()
        return " ".join(
            str(c.compile(compile_kwargs={"literal_binds": True})) for c in captured
        )

    def test_list_items_admin_covers_admin_agent(self, monkeypatch):
        """admin 回收站列表需能覆盖 admin_agent 条目。

        list_items 用 `==` 精确匹配 deleted_by_type；若列表仍只传 'admin'，
        Agent 代删的系统资源在后台回收站里**看不见**，用户将无法恢复。
        """
        sql = self._capture_filters(
            monkeypatch,
            lambda: RecycleBinService().list_items(deleted_by_type="admin"),
        )
        assert "admin_agent" in sql

    def test_overview_admin_covers_admin_agent(self, monkeypatch):
        sql = self._capture_filters(
            monkeypatch,
            lambda: RecycleBinService().overview(deleted_by_type="admin"),
        )
        assert "admin_agent" in sql

    def test_explicit_admin_agent_filter_stays_exact(self, monkeypatch):
        """显式按 admin_agent 过滤时不应把 admin 也带进来。"""
        sql = self._capture_filters(
            monkeypatch,
            lambda: RecycleBinService().list_items(deleted_by_type="admin_agent"),
        )
        assert "in (" not in sql.lower() or "admin_agent" in sql


class TestOwnerContextAndNames:
    def test_owner_account_context_returns_none_for_admin_agent(self):
        """admin_agent 的 deleted_by 是管理员 ID，不能当账号去解析设备。"""
        svc = RecycleBinService()
        item = SimpleNamespace(deleted_by_type="admin_agent", deleted_by=uuid4())
        assert svc._owner_account_context(item) is None

    def test_owner_account_context_returns_account_for_agent(self):
        svc = RecycleBinService()
        account_id = uuid4()
        item = SimpleNamespace(deleted_by_type="agent", deleted_by=account_id)
        assert svc._owner_account_context(item) == str(account_id)

    def test_check_user_owned_rejects_admin_agent(self):
        """管理员 Agent 代删的条目不得被用户端恢复（越权边界）。"""
        from internal.exception import ForbiddenException

        svc = RecycleBinService()
        item = SimpleNamespace(
            resource_type="workflow",
            deleted_by_type="admin_agent",
            deleted_by=uuid4(),
        )
        with pytest.raises(ForbiddenException):
            svc._check_user_owned(item, uuid4())

    def test_attach_names_resolves_admin_agent_creator_as_admin(self, monkeypatch):
        """admin_agent 的 deleted_by 记人类责任人（管理员），名称走 admin 分支。"""
        admin_id = uuid4()
        item = SimpleNamespace(
            deleted_by=str(admin_id),
            deleted_by_type="admin_agent",
            deleted_by_name=None,
        )
        rows = [SimpleNamespace(id=admin_id, name="运维管理员", username="ops")]

        class _Q:
            def filter(self, *a, **kw):
                return self

            def all(self):
                return rows

        monkeypatch.setattr(
            mod, "db", SimpleNamespace(session=SimpleNamespace(query=lambda *a, **kw: _Q()))
        )
        RecycleBinService()._attach_deleted_by_names([item])
        assert item.deleted_by_name == "运维管理员"
