import importlib
import json
import urllib.request

from internal.core.tools.builtin_tools.providers.codex_os.os_recycle_bin import (
    OsRecycleBinTool,
)


module = importlib.import_module(
    "internal.core.tools.builtin_tools.providers.codex_os.os_recycle_bin"
)


def test_os_recycle_bin_returns_disabled_error_when_not_configured(monkeypatch):
    monkeypatch.delenv("OS_AUTOMATION_URL", raising=False)
    monkeypatch.delenv("OS_AUTOMATION_TOKEN", raising=False)

    result = json.loads(OsRecycleBinTool()._run(op="list"))

    assert result["ok"] is False
    assert "未配置" in result["error"]


def test_os_recycle_bin_passes_payload(monkeypatch):
    captured = {}

    def fake_call_worker(payload):
        captured.update(payload)
        return {"ok": True, "entries": [], "count": 0}

    monkeypatch.setattr(module, "_call_worker", fake_call_worker)

    result = json.loads(
        OsRecycleBinTool()._run(
            op="delete",
            paths=["C:/tmp/a.txt"],
            task_id="task-1",
            reason="清理缓存",
        )
    )

    assert result["ok"] is True
    assert captured["op"] == "delete"
    assert captured["paths"] == ["C:/tmp/a.txt"]
    assert captured["task_id"] == "task-1"
    assert captured["reason"] == "清理缓存"
    assert captured["retention_days"] == 7


def test_os_recycle_bin_uses_desktop_bridge(monkeypatch):
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

    result = json.loads(OsRecycleBinTool()._run(op="list"))

    assert result["ok"] is True
    assert captured["url"] == "http://127.0.0.1:9876/recycle"
    assert captured["auth"] == "Bearer bridge-token"
