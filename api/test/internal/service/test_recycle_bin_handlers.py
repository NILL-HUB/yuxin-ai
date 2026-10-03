from types import SimpleNamespace
from uuid import uuid4

import pytest

from internal.exception import DeviceMismatchException, ValidateErrorException
from internal.service import recycle_bin_handlers as handlers


def _snapshot(entry_id="e1"):
    return {"entry_id": entry_id, "original_path": "C:/tmp/a.txt"}


def test_restore_os_file_passes_target_and_confirm_flags(monkeypatch):
    captured = {}

    def fake_call_worker(payload, account_id=None):
        captured.update(payload)
        return {"ok": True, "restored_to": "C:/tmp/custom/a.txt"}

    monkeypatch.setattr(handlers, "_call_worker_recycle", fake_call_worker)

    ok = handlers.restore_os_file(
        _snapshot(),
        target_path="C:/tmp/custom/a.txt",
        check_device=True,
        confirm_device_mismatch=True,
    )

    assert ok is True
    assert captured["op"] == "restore"
    assert captured["entry_id"] == "e1"
    assert captured["target_path"] == "C:/tmp/custom/a.txt"
    assert captured["check_device"] is True
    assert captured["confirm_device_mismatch"] is True


def test_restore_os_file_raises_device_mismatch(monkeypatch):
    monkeypatch.setattr(
        handlers,
        "_call_worker_recycle",
        lambda payload, account_id=None: {
            "ok": False,
            "code": "device_mismatch",
            "recorded_device": {"ip": "192.168.1.10", "name": "alice"},
            "current_device": {"ip": "192.168.1.20", "name": "bob"},
        },
    )

    with pytest.raises(DeviceMismatchException) as exc_info:
        handlers.restore_os_file(_snapshot(), check_device=True)

    assert exc_info.value.recorded_device == {"ip": "192.168.1.10", "name": "alice"}
    assert exc_info.value.current_device == {"ip": "192.168.1.20", "name": "bob"}
    assert exc_info.value.entry_id == "e1"


def test_restore_os_file_raises_validate_error_on_worker_failure(monkeypatch):
    monkeypatch.setattr(
        handlers,
        "_call_worker_recycle",
        lambda payload, account_id=None: {"ok": False, "error": "回收站中未找到对应条目"},
    )

    with pytest.raises(ValidateErrorException) as exc_info:
        handlers.restore_os_file(_snapshot())

    assert "回收站中未找到对应条目" in str(exc_info.value)


def test_purge_os_file_passes_recorded_safe_root_not_recycle_root(monkeypatch):
    """purge 必须传删除时记录的 safe_root（清单基点），不得把 recycle_root 当 safe_root。

    回归：把 recycle_root（<safe_root>/.yujianwo_recycle）当 safe_root 会让 worker
    在回收站目录下再套一层 .yujianwo_recycle 找 manifest 而定位失败（潜伏 bug）。
    """
    captured = {}
    monkeypatch.setattr(
        handlers,
        "_call_worker_recycle",
        lambda payload, account_id=None: captured.update(payload) or {"ok": True, "purged": []},
    )
    snapshot = {
        "entry_id": "entry-1",
        "original_path": "C:/Users/u/project/a.txt",
        "moved_to": "C:/Users/u/.yujianwo_recycle/project/a.txt",
        "recycle_root": "C:/Users/u/.yujianwo_recycle",
        "safe_root": "C:/Users/u",
    }

    handlers.purge_os_file(snapshot)

    assert captured["op"] == "purge"
    assert captured["entry_id"] == "entry-1"
    assert captured["safe_root"] == "C:/Users/u"
    assert captured["safe_root"] != captured.get("recycle_root")


def test_purge_os_file_raises_when_entry_id_missing():
    with pytest.raises(RuntimeError) as exc_info:
        handlers.purge_os_file({"original_path": "C:/tmp/a.txt"})
    assert "缺少 entry_id" in str(exc_info.value)


def test_purge_os_file_raises_on_worker_failure(monkeypatch):
    monkeypatch.setattr(
        handlers,
        "_call_worker_recycle",
        lambda payload, account_id=None: {"ok": False, "error": "worker 不可达"},
    )

    with pytest.raises(RuntimeError) as exc_info:
        handlers.purge_os_file({"entry_id": "entry-1"})
    assert "purge 失败" in str(exc_info.value)


# ---------------------------------------------------------------------------
# 本机回收站端点解析：必须与 4 个 Agent 工具走同一套「按账号动态解析」
# ---------------------------------------------------------------------------
class TestWorkerRecycleEndpointResolution:
    """回归：平台回收站恢复/销毁本机文件曾只读静态 env。

    桌面端 token 是每次启动随机生成的（`crypto.randomBytes(24)`），只有注册到
    `desktop_device` 后由 `resolve_desktop_bridge` 才能解析到。因此只读静态 env
    会导致「agent 删了本机文件 → 平台回收站里恢复必然失败」的断链。
    """

    def test_prefers_account_scoped_dynamic_resolution(self, monkeypatch):
        calls = {}

        def fake_resolve(account_id=None, *, purpose=""):
            calls["account_id"] = account_id
            calls["purpose"] = purpose
            return ("http://host.docker.internal:9876", "dynamic-token")

        monkeypatch.setattr(
            "internal.service.desktop_bridge_resolver.resolve_desktop_bridge",
            fake_resolve,
        )
        # 静态 env 故意配成别的值：动态解析必须优先
        monkeypatch.setenv("DESKTOP_BRIDGE_URL", "http://static:1")
        monkeypatch.setenv("DESKTOP_BRIDGE_TOKEN", "static-token")

        endpoint, token = handlers._worker_recycle_endpoint(account_id="acct-1")

        assert endpoint == "http://host.docker.internal:9876/recycle"
        assert token == "dynamic-token"
        assert calls["account_id"] == "acct-1"

    def test_falls_back_to_static_when_no_dynamic_device(self, monkeypatch):
        monkeypatch.setattr(
            "internal.service.desktop_bridge_resolver.resolve_desktop_bridge",
            lambda account_id=None, *, purpose="": None,
        )
        monkeypatch.setenv("DESKTOP_BRIDGE_URL", "http://static:1")
        monkeypatch.setenv("DESKTOP_BRIDGE_TOKEN", "static-token")

        endpoint, token = handlers._worker_recycle_endpoint(account_id="acct-1")

        assert endpoint == "http://static:1/recycle"
        assert token == "static-token"

    def test_keeps_legacy_os_automation_fallback(self, monkeypatch):
        """无账号上下文时仍须保留既有 OS_AUTOMATION_* 兼容路径。"""
        monkeypatch.setattr(
            "internal.service.desktop_bridge_resolver.resolve_desktop_bridge",
            lambda account_id=None, *, purpose="": None,
        )
        monkeypatch.delenv("DESKTOP_BRIDGE_URL", raising=False)
        monkeypatch.delenv("DESKTOP_BRIDGE_TOKEN", raising=False)
        monkeypatch.setenv("OS_AUTOMATION_URL", "http://legacy:8765")
        monkeypatch.setenv("OS_AUTOMATION_TOKEN", "legacy-token")

        endpoint, token = handlers._worker_recycle_endpoint()

        assert endpoint == "http://legacy:8765/recycle"
        assert token == "legacy-token"

    def test_restore_uses_account_scoped_endpoint(self, monkeypatch):
        """恢复接口要把账号透传下去，否则拿不到动态设备。"""
        captured = {}
        monkeypatch.setattr(
            handlers,
            "_call_worker_recycle",
            lambda payload, account_id=None: captured.update(
                {"payload": payload, "account_id": account_id}
            ) or {"ok": True},
        )

        handlers.restore_os_file(_snapshot(), account_id="acct-9")

        assert captured["account_id"] == "acct-9"

    def test_purge_uses_account_scoped_endpoint(self, monkeypatch):
        captured = {}
        monkeypatch.setattr(
            handlers,
            "_call_worker_recycle",
            lambda payload, account_id=None: captured.update(
                {"payload": payload, "account_id": account_id}
            ) or {"ok": True, "purged": []},
        )

        handlers.purge_os_file({"entry_id": "entry-1"}, account_id="acct-9")

        assert captured["account_id"] == "acct-9"


# ---------------------------------------------------------------------------
# 新增资源类型：分发入口路由正确性（无 DB 依赖）
# ---------------------------------------------------------------------------
def test_snapshot_resource_routes_schedule_task(monkeypatch):
    called = {}
    monkeypatch.setattr(
        handlers, "snapshot_schedule_task", lambda rid: called.update(rid=str(rid)) or {"main": {}}
    )
    assert handlers.snapshot_resource("schedule_task", "task-1") == {"main": {}}
    assert called["rid"] == "task-1"


def test_snapshot_resource_routes_external_data_source(monkeypatch):
    called = {}
    monkeypatch.setattr(
        handlers,
        "snapshot_external_data_source",
        lambda rid: called.update(rid=str(rid)) or {"main": {}},
    )
    assert handlers.snapshot_resource("external_data_source", "eds-1") == {"main": {}}
    assert called["rid"] == "eds-1"


def test_snapshot_resource_routes_conversation(monkeypatch):
    called = {}
    monkeypatch.setattr(
        handlers, "snapshot_conversation", lambda rid: called.update(rid=str(rid)) or {"main": {}}
    )
    assert handlers.snapshot_resource("conversation", "conv-1") == {"main": {}}
    assert called["rid"] == "conv-1"


def test_physical_delete_resource_routes_new_types(monkeypatch):
    called = []
    for fn in (
        "physical_delete_schedule_task",
        "physical_delete_external_data_source",
        "physical_delete_conversation",
    ):
        monkeypatch.setattr(handlers, fn, lambda rid, fn=fn: called.append(f"{fn}:{rid}"))
    handlers.physical_delete_resource("schedule_task", "t1")
    handlers.physical_delete_resource("external_data_source", "e1")
    handlers.physical_delete_resource("conversation", "c1")
    assert called == [
        "physical_delete_schedule_task:t1",
        "physical_delete_external_data_source:e1",
        "physical_delete_conversation:c1",
    ]


def test_restore_resource_routes_new_types(monkeypatch):
    called = []
    monkeypatch.setattr(handlers, "restore_schedule_task", lambda s: called.append("schedule_task") or True)
    monkeypatch.setattr(
        handlers, "restore_external_data_source", lambda s: called.append("external_data_source") or True
    )
    monkeypatch.setattr(handlers, "restore_conversation", lambda s: called.append("conversation") or True)
    assert handlers.restore_resource("schedule_task", {}) is True
    assert handlers.restore_resource("external_data_source", {}) is True
    assert handlers.restore_resource("conversation", {}) is True
    assert called == ["schedule_task", "external_data_source", "conversation"]


def test_purge_resource_routes_new_types(monkeypatch):
    called = []
    monkeypatch.setattr(handlers, "purge_schedule_task", lambda s: called.append("schedule_task"))
    monkeypatch.setattr(
        handlers, "purge_external_data_source", lambda s: called.append("external_data_source")
    )
    monkeypatch.setattr(handlers, "purge_conversation", lambda s: called.append("conversation"))
    handlers.purge_resource("schedule_task", {})
    handlers.purge_resource("external_data_source", {})
    handlers.purge_resource("conversation", {})
    assert called == ["schedule_task", "external_data_source", "conversation"]


def test_restore_conversation_toggles_is_deleted(monkeypatch):
    conversation = SimpleNamespace(id="c1", is_deleted=True)

    class _Query:
        def filter(self, *_a, **_k):
            return self

        def one_or_none(self):
            return conversation

    monkeypatch.setattr(handlers, "db", SimpleNamespace(session=SimpleNamespace(query=lambda *_: _Query())))

    assert handlers.restore_conversation({"main": {"id": "c1"}}) is True
    assert conversation.is_deleted is False

    # 已恢复时重复恢复返回 False
    assert handlers.restore_conversation({"main": {"id": "c1"}}) is False


def test_restore_conversation_fails_when_destroyed(monkeypatch):
    class _Query:
        def filter(self, *_a, **_k):
            return self

        def one_or_none(self):
            return None

    monkeypatch.setattr(handlers, "db", SimpleNamespace(session=SimpleNamespace(query=lambda *_: _Query())))

    assert handlers.restore_conversation({"main": {"id": "gone"}}) is False


# ---------------------------------------------------------------------------
# memory：个人记忆（软删模式）分发路由正确性
# ---------------------------------------------------------------------------
def test_snapshot_resource_routes_memory(monkeypatch):
    called = {}
    monkeypatch.setattr(
        handlers, "snapshot_memory", lambda rid: called.update(rid=str(rid)) or {"main": {}}
    )
    assert handlers.snapshot_resource("memory", "mem-1") == {"main": {}}
    assert called["rid"] == "mem-1"


def test_physical_delete_resource_routes_memory(monkeypatch):
    called = []
    monkeypatch.setattr(
        handlers, "physical_delete_memory", lambda rid: called.append(f"physical_delete_memory:{rid}")
    )
    handlers.physical_delete_resource("memory", "mem-1")
    assert called == ["physical_delete_memory:mem-1"]


def test_restore_resource_routes_memory(monkeypatch):
    called = []
    monkeypatch.setattr(handlers, "restore_memory", lambda s: called.append("memory") or True)
    assert handlers.restore_resource("memory", {}) is True
    assert called == ["memory"]


def test_purge_resource_routes_memory(monkeypatch):
    called = []
    monkeypatch.setattr(handlers, "purge_memory", lambda s: called.append("memory"))
    handlers.purge_resource("memory", {})
    assert called == ["memory"]


def test_restore_memory_rebuilds_user_memory_row_when_missing(monkeypatch):
    added = []

    class _Session:
        def add(self, row):
            added.append(row)

        def query(self, *_a, **_k):
            return _Query()

    class _Query:
        def filter(self, *_a, **_k):
            return self

        def one_or_none(self):
            return None

    monkeypatch.setattr(handlers, "db", SimpleNamespace(session=_Session()))
    monkeypatch.setattr(handlers, "_memory_driver", lambda: None)

    snapshot = {
        "main": {
            "id": "mem-1",
            "embedding_node_id": "mem-1",
            "owner_account_id": "acc-1",
            "memory_type": "episode",
            "content": "我的个人记忆内容",
        },
    }
    assert handlers.restore_memory(snapshot) is True
    assert len(added) == 1
    assert added[0].id == "mem-1"
    assert added[0].content == "我的个人记忆内容"


def test_restore_memory_returns_false_without_id():
    assert handlers.restore_memory({"main": {}}) is False


def test_delete_documents_by_source_removes_matching_docs_and_segments(monkeypatch):
    """按 source_type + source_id 清理，且必须经 injector 取向量服务。"""
    from internal.service import recycle_bin_handlers as handlers

    doc = SimpleNamespace(id=uuid4(), upload_file_id=None)
    segment = SimpleNamespace(id=uuid4())
    removed = {"vector": [], "deleted_models": []}

    class _Query:
        def __init__(self, result):
            self._result = result

        def filter(self, *_a, **_k):
            return self

        def all(self):
            return self._result if isinstance(self._result, list) else []

        def one_or_none(self):
            return self._result

        def delete(self, **_k):
            removed["deleted_models"].append(self._result)
            return 1

    class _Session:
        def query(self, model, *_a, **_k):
            name = getattr(model, "__name__", str(model))
            if name == "KnowledgeDocument":
                return _Query([doc])
            if name == "KnowledgeSegment":
                return _Query([segment])
            return _Query(None)

        def commit(self):
            pass

    monkeypatch.setattr(handlers, "db", SimpleNamespace(session=_Session()))

    class _Vector:
        def remove_segment(self, seg):
            removed["vector"].append(seg.id)

    monkeypatch.setattr(
        handlers, "_get_knowledge_vector_service", lambda: _Vector(), raising=False
    )

    count = handlers._delete_documents_by_source("lark", "ds-1")

    assert count == 1
    assert removed["vector"] == [segment.id]


# ---------------------------------------------------------------------------
# account：用户账号（锁定模式）
# 删除 = 锁定（status='recycled' + 吊销全部会话），不清数据与资产；
# 恢复 = status 回写快照值；到期销毁 = 全量清空该账号资产与附属数据。
# ---------------------------------------------------------------------------
class _AccountQuery:
    def __init__(self, session, model_name):
        self._session = session
        self._model_name = model_name

    def filter(self, *_a, **_k):
        return self

    def one_or_none(self):
        if self._model_name == "Account":
            return self._session.account
        return None

    def update(self, values=None, **_k):
        self._session.updated.append((self._model_name, values))
        return 1

    def delete(self, **_k):
        self._session.deleted.append(self._model_name)
        return 1


class _AccountSession:
    """按模型名分派的 session stub：记录 update/delete 调用。"""

    def __init__(self, account):
        self.account = account
        self.updated: list = []
        self.deleted: list = []

    def query(self, model, *_a, **_k):
        return _AccountQuery(self, getattr(model, "__name__", str(model)))


def test_snapshot_account_returns_row_dict(monkeypatch):
    from internal.model.account import Account

    account = Account(id=uuid4(), status="active", name="张三", email="zhangsan@example.com")
    session = _AccountSession(account)
    monkeypatch.setattr(handlers, "db", SimpleNamespace(session=session))

    snapshot = handlers.snapshot_account(account.id)

    assert snapshot is not None
    main = snapshot["main"]
    assert main["status"] == "active"
    assert main["name"] == "张三"
    # 密码等字段一并入快照，保证恢复后仍可登录
    assert "password" in main and "password_salt" in main


def test_snapshot_account_returns_none_when_missing(monkeypatch):
    monkeypatch.setattr(handlers, "db", SimpleNamespace(session=_AccountSession(None)))
    assert handlers.snapshot_account(uuid4()) is None


def test_physical_delete_account_locks_and_revokes_sessions(monkeypatch):
    """入站 = 锁定：置 status='recycled' 并批量吊销未撤销会话，不删任何数据。"""
    account = SimpleNamespace(id="acc-1", status="active")
    session = _AccountSession(account)
    monkeypatch.setattr(handlers, "db", SimpleNamespace(session=session))

    handlers.physical_delete_account("acc-1")

    assert account.status == "recycled"
    updated_models = [name for name, _ in session.updated]
    assert "AccountSession" in updated_models
    assert session.deleted == []


def test_restore_account_restores_previous_status(monkeypatch):
    account = SimpleNamespace(id="acc-1", status="recycled")
    session = _AccountSession(account)
    monkeypatch.setattr(handlers, "db", SimpleNamespace(session=session))

    assert handlers.restore_account({"main": {"id": "acc-1", "status": "active"}}) is True
    assert account.status == "active"


def test_restore_account_falls_back_to_active_without_snapshot_status(monkeypatch):
    account = SimpleNamespace(id="acc-1", status="recycled")
    monkeypatch.setattr(handlers, "db", SimpleNamespace(session=_AccountSession(account)))

    assert handlers.restore_account({"main": {"id": "acc-1"}}) is True
    assert account.status == "active"


def test_restore_account_returns_false_when_destroyed(monkeypatch):
    monkeypatch.setattr(handlers, "db", SimpleNamespace(session=_AccountSession(None)))
    assert handlers.restore_account({"main": {"id": "gone", "status": "active"}}) is False


def test_purge_account_clears_assets_aux_data_and_row(monkeypatch):
    """到期销毁：清资产 + 清附属数据 + 解绑引用 + 物理删除账号行（无孤儿）。"""
    import internal.service.memory.memory_governor as _governor_mod

    account_id = uuid4()
    session = _AccountSession(None)
    monkeypatch.setattr(handlers, "db", SimpleNamespace(session=session))

    touched = []
    monkeypatch.setattr(
        handlers, "_purge_account_owned_resources", lambda aid: touched.append(str(aid))
    )
    monkeypatch.setattr(handlers, "_purge_account_neo4j", lambda aid: touched.append("neo4j"))

    class _GovernorStub:
        def __init__(self, *args, **kwargs):
            pass

        def _clear_all_user_cache(self, owner_key):
            touched.append("redis")
            return 0

    monkeypatch.setattr(_governor_mod, "MemoryGovernor", _GovernorStub)

    handlers.purge_account({"main": {"id": str(account_id), "status": "recycled"}})

    assert touched == [str(account_id), "neo4j", "redis"]
    updated_models = [name for name, _ in session.updated]
    assert "AdminUser" in updated_models
    assert "AuditLog" in updated_models
    assert "Account" in session.deleted


def test_purge_account_owned_resources_covers_all_owned_assets(monkeypatch):
    """资产清空必须逐一覆盖知识库/文件/应用/工作流/会话/记忆/任务/数据源/工具。"""
    ids = [uuid4() for _ in range(10)]
    mapping = {
        "KnowledgeBase": [(ids[0],)],
        "UploadFile": [(ids[1],)],
        "App": [(ids[2],)],
        "Workflow": [(ids[3],)],
        "Conversation": [(ids[4],)],
        "UserMemory": [(ids[5],)],
        "ScheduleTask": [(ids[6],)],
        "ExternalDataSource": [(ids[7],)],
        "ApiToolProvider": [(ids[8],)],
        "McpProvider": [(ids[9],)],
    }

    class _Query:
        def __init__(self, rows):
            self._rows = rows

        def filter(self, *_a, **_k):
            return self

        def all(self):
            return self._rows

    class _Session:
        def query(self, model, *_a, **_k):
            # 调用方传的是类（如 App）或列属性（如 KnowledgeBase.id），统一解析到类名
            cls = getattr(model, "class_", model)
            return _Query(mapping.get(getattr(cls, "__name__", ""), []))

    monkeypatch.setattr(handlers, "db", SimpleNamespace(session=_Session()))
    # 快照返回 None → 只走物理删除分支，purge 分支不执行（避免触达存储层）
    for name in (
        "snapshot_knowledge_base",
        "snapshot_upload_file",
        "snapshot_memory",
        "snapshot_schedule_task",
        "snapshot_external_data_source",
    ):
        monkeypatch.setattr(handlers, name, lambda rid: None)
    # 会话走 snapshot + purge（无 physical_delete 环节），快照需非空才能触达 purge
    monkeypatch.setattr(
        handlers, "snapshot_conversation", lambda rid: {"main": {"id": str(rid)}}
    )

    calls = []
    monkeypatch.setattr(
        handlers, "physical_delete_generic", lambda rtype, rid: calls.append((rtype, str(rid)))
    )
    for name in (
        "physical_delete_knowledge_base",
        "physical_delete_upload_file",
        "purge_conversation",
        "physical_delete_memory",
        "physical_delete_schedule_task",
        "physical_delete_external_data_source",
    ):
        monkeypatch.setattr(
            handlers, name, lambda rid, _n=name: calls.append((_n, str(rid)))
        )

    handlers._purge_account_owned_resources(uuid4())

    covered = {name for name, _ in calls}
    assert {
        "physical_delete_knowledge_base",
        "physical_delete_upload_file",
        "app",
        "workflow",
        "purge_conversation",
        "physical_delete_memory",
        "physical_delete_schedule_task",
        "physical_delete_external_data_source",
        "api_tool",
        "mcp",
    } <= covered


def test_snapshot_resource_routes_account(monkeypatch):
    called = {}
    monkeypatch.setattr(
        handlers, "snapshot_account", lambda rid: called.update(rid=str(rid)) or {"main": {}}
    )
    assert handlers.snapshot_resource("account", "acc-1") == {"main": {}}
    assert called["rid"] == "acc-1"


def test_physical_delete_resource_routes_account(monkeypatch):
    called = []
    monkeypatch.setattr(handlers, "physical_delete_account", lambda rid: called.append(str(rid)))
    handlers.physical_delete_resource("account", "acc-1")
    assert called == ["acc-1"]


def test_restore_resource_routes_account(monkeypatch):
    called = []
    monkeypatch.setattr(
        handlers, "restore_account", lambda s: called.append(s["main"]["id"]) or True
    )
    assert handlers.restore_resource("account", {"main": {"id": "acc-1"}}) is True
    assert called == ["acc-1"]


def test_purge_resource_routes_account(monkeypatch):
    called = []
    monkeypatch.setattr(handlers, "purge_account", lambda s: called.append("account"))
    handlers.purge_resource("account", {})
    assert called == ["account"]
