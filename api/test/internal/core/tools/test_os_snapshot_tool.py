import importlib
import json
import urllib.request

from internal.core.tools.builtin_tools.providers.codex_os.os_snapshot import (
    OsSnapshotTool,
)


module = importlib.import_module(
    "internal.core.tools.builtin_tools.providers.codex_os.os_snapshot"
)


def test_os_snapshot_returns_disabled_error_when_not_configured(monkeypatch):
    monkeypatch.delenv("OS_AUTOMATION_URL", raising=False)
    monkeypatch.delenv("OS_AUTOMATION_TOKEN", raising=False)
    monkeypatch.delenv("DESKTOP_BRIDGE_URL", raising=False)
    monkeypatch.delenv("DESKTOP_BRIDGE_TOKEN", raising=False)

    result = json.loads(OsSnapshotTool()._run(op="list_snapshots"))

    assert result["ok"] is False
    assert "未配置" in result["error"]


def test_os_snapshot_passes_payload(monkeypatch):
    captured = {}

    def fake_call_worker(payload):
        captured.update(payload)
        return {"ok": True, "entries": [], "count": 0}

    monkeypatch.setattr(module, "_call_worker", fake_call_worker)

    result = json.loads(
        OsSnapshotTool()._run(
            op="rollback_file",
            path="C:/tmp/a.txt",
            snapshot_id="snap-1",
            working_dir="C:/tmp",
        )
    )

    assert result["ok"] is True
    assert captured["op"] == "rollback_file"
    assert captured["path"] == "C:/tmp/a.txt"
    assert captured["snapshot_id"] == "snap-1"
    assert captured["working_dir"] == "C:/tmp"


def test_os_snapshot_uses_desktop_bridge(monkeypatch):
    monkeypatch.setenv("DESKTOP_BRIDGE_URL", "http://127.0.0.1:9876")
    monkeypatch.setenv("DESKTOP_BRIDGE_TOKEN", "bridge-token")
    captured = {}

    class _FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def read(self):
            return b'{"ok":true,"entries":[],"count":0}'

    def fake_urlopen(request, timeout=None):
        captured["url"] = request.full_url
        captured["auth"] = request.headers.get("Authorization")
        return _FakeResponse()

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)

    result = json.loads(OsSnapshotTool()._run(op="list_snapshots"))

    assert result["ok"] is True
    assert captured["url"] == "http://127.0.0.1:9876/snapshot"
    assert captured["auth"] == "Bearer bridge-token"


def test_os_snapshot_appends_snapshot_path_for_os_automation_url(monkeypatch):
    """OS_AUTOMATION_URL 分支必须拼接 /snapshot。"""
    monkeypatch.delenv("DESKTOP_BRIDGE_URL", raising=False)
    monkeypatch.delenv("DESKTOP_BRIDGE_TOKEN", raising=False)
    monkeypatch.setenv("OS_AUTOMATION_URL", "http://worker:8765")
    monkeypatch.setenv("OS_AUTOMATION_TOKEN", "os-token")
    captured = {}

    class _FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def read(self):
            return b'{"ok":true,"entries":[],"count":0}'

    def fake_urlopen(request, timeout=None):
        captured["url"] = request.full_url
        captured["auth"] = request.headers.get("Authorization")
        return _FakeResponse()

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)

    result = json.loads(OsSnapshotTool()._run(op="list_snapshots"))

    assert result["ok"] is True
    assert captured["url"] == "http://worker:8765/snapshot"
    assert captured["auth"] == "Bearer os-token"


def test_os_snapshot_passes_rollback_turn_payload(monkeypatch):
    captured = {}

    def fake_call_worker(payload):
        captured.update(payload)
        return {"ok": True, "restored": [], "errors": [], "count": 0}

    monkeypatch.setattr(module, "_call_worker", fake_call_worker)

    result = json.loads(
        OsSnapshotTool()._run(
            op="rollback_turn",
            conversation_turn="turn-42",
            requester="account-1",
        )
    )

    assert result["ok"] is True
    assert captured["op"] == "rollback_turn"
    assert captured["conversation_turn"] == "turn-42"
    assert captured["requester"] == "account-1"


def test_os_snapshot_falls_back_to_bound_conversation_turn(monkeypatch):
    """工具实例绑定的 conversation_turn 作为缺省值：Agent 按轮回滚无需模型自填。"""
    captured = {}

    def fake_call_worker(payload):
        captured.update(payload)
        return {"ok": True, "restored": [], "errors": [], "count": 0}

    monkeypatch.setattr(module, "_call_worker", fake_call_worker)

    tool = OsSnapshotTool(
        requester="account-1",
        session_id="conv-9",
        conversation_turn="conv-9:msg-1",
    )
    result = json.loads(tool._run(op="rollback_turn"))

    assert result["ok"] is True
    assert captured["conversation_turn"] == "conv-9:msg-1"
    assert captured["session_id"] == "conv-9"
    assert captured["requester"] == "account-1"


def test_os_snapshot_factory_binds_session_context(monkeypatch):
    """工厂透传：os_snapshot(session_id=..., conversation_turn=...) 绑定到工具实例。"""
    from internal.core.tools.builtin_tools.providers.codex_os.os_snapshot import (
        os_snapshot,
    )

    tool = os_snapshot(
        requester="account-1",
        session_id="conv-9",
        conversation_turn="conv-9:msg-1",
    )
    assert tool.requester == "account-1"
    assert tool.session_id == "conv-9"
    assert tool.conversation_turn == "conv-9:msg-1"
