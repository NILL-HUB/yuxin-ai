from types import SimpleNamespace

import pytest

from internal.exception import DeviceMismatchException, ValidateErrorException
from internal.service import recycle_bin_handlers as handlers


def _snapshot(entry_id="e1"):
    return {"entry_id": entry_id, "original_path": "C:/tmp/a.txt"}


def test_restore_os_file_passes_target_and_confirm_flags(monkeypatch):
    captured = {}

    def fake_call_worker(payload):
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
        lambda payload: {
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
        lambda payload: {"ok": False, "error": "回收站中未找到对应条目"},
    )

    with pytest.raises(ValidateErrorException) as exc_info:
        handlers.restore_os_file(_snapshot())

    assert "回收站中未找到对应条目" in str(exc_info.value)


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
