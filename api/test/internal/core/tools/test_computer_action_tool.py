import importlib
import json
import urllib.request

from internal.core.tools.builtin_tools.providers.computer_control.computer_action import (
    ComputerActionTool,
)


module = importlib.import_module(
    "internal.core.tools.builtin_tools.providers.computer_control.computer_action"
)


def test_computer_action_returns_disabled_error_when_not_configured(monkeypatch):
    monkeypatch.delenv("COMPUTER_CONTROL_URL", raising=False)
    monkeypatch.delenv("COMPUTER_CONTROL_TOKEN", raising=False)
    monkeypatch.delenv("DESKTOP_BRIDGE_URL", raising=False)
    monkeypatch.delenv("DESKTOP_BRIDGE_TOKEN", raising=False)

    result = json.loads(
        ComputerActionTool()._run(actions=[{"action": "click", "x": 1, "y": 1}])
    )

    assert result["ok"] is False
    assert "未找到可用的桌面设备连接" in result["error"]


def test_computer_action_passes_requester_to_payload(monkeypatch):
    captured = {}

    def fake_call_worker(payload):
        captured.update(payload)
        return {"ok": True, "results": []}

    monkeypatch.setattr(module, "_call_worker", fake_call_worker)

    ComputerActionTool(requester="acct-1")._run(actions=[{"action": "move", "x": 1, "y": 1}])

    assert captured["requester"] == "acct-1"


def test_computer_action_resolves_bridge_by_requester(monkeypatch):
    captured = {}

    def fake_resolve(account_id=None, **kwargs):
        captured["account_id"] = account_id
        return "http://host.docker.internal:9876", "dynamic-token"

    monkeypatch.setattr(
        "internal.service.desktop_bridge_resolver.resolve_desktop_bridge",
        fake_resolve,
    )

    class _FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def read(self):
            return b'{"ok":true}'

    def fake_urlopen(request, timeout=None):
        captured["url"] = request.full_url
        captured["auth"] = request.headers.get("Authorization")
        return _FakeResponse()

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)

    result = json.loads(
        ComputerActionTool(requester="acct-1")._run(actions=[{"action": "move", "x": 1, "y": 1}])
    )

    assert result["ok"] is True
    assert captured["account_id"] == "acct-1"
    assert captured["url"] == "http://host.docker.internal:9876/control"
    assert captured["auth"] == "Bearer dynamic-token"


def test_computer_action_passes_actions(monkeypatch):
    captured = {}

    def fake_call_worker(payload):
        captured.update(payload)
        return {"ok": True, "results": [{"action": "click", "ok": True}]}

    monkeypatch.setattr(module, "_call_worker", fake_call_worker)

    result = json.loads(
        ComputerActionTool()._run(
            actions=[{"action": "click", "x": 10, "y": 20}]
        )
    )

    assert result["ok"] is True
    assert captured["actions"] == [{"action": "click", "x": 10, "y": 20}]


def test_computer_action_uses_desktop_bridge(monkeypatch):
    monkeypatch.setenv("DESKTOP_BRIDGE_URL", "http://127.0.0.1:9876")
    monkeypatch.setenv("DESKTOP_BRIDGE_TOKEN", "bridge-token")
    captured = {}

    class _FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def read(self):
            return b'{"ok":true}'

    def fake_urlopen(request, timeout=None):
        captured["url"] = request.full_url
        captured["auth"] = request.headers.get("Authorization")
        return _FakeResponse()

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)

    result = json.loads(ComputerActionTool()._run(actions=[{"action": "move", "x": 1, "y": 1}]))

    assert result["ok"] is True
    assert captured["url"] == "http://127.0.0.1:9876/control"
    assert captured["auth"] == "Bearer bridge-token"
