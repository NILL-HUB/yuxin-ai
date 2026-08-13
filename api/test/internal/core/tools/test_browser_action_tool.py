import json
import importlib
import urllib.request

from internal.core.tools.builtin_tools.providers.browser_automation.browser_action import (
    BrowserActionTool,
)

browser_action_module = importlib.import_module(
    "internal.core.tools.builtin_tools.providers.browser_automation.browser_action"
)


def test_browser_action_returns_disabled_error_when_not_configured(monkeypatch):
    monkeypatch.delenv("BROWSER_AUTOMATION_URL", raising=False)
    monkeypatch.delenv("BROWSER_AUTOMATION_TOKEN", raising=False)

    result = json.loads(BrowserActionTool()._run(action="navigate", url="https://example.com"))

    assert result["ok"] is False
    assert "默认关闭" in result["error"]


def test_browser_action_calls_worker(monkeypatch):
    captured = {}

    def fake_call_worker(payload):
        captured.update(payload)
        return {"ok": True, "title": "Example", "text": "hello"}

    monkeypatch.setattr(browser_action_module, "_call_worker", fake_call_worker)

    result = json.loads(
        BrowserActionTool()._run(
            action="click",
            url="https://example.com",
            selector="#btn",
            wait_ms=100,
            timeout=30000,
        )
    )

    assert result["ok"] is True
    assert result["text"] == "hello"
    assert captured["action"] == "click"
    assert captured["url"] == "https://example.com"
    assert captured["selector"] == "#btn"
    assert captured["wait_ms"] == 100


def test_browser_action_uses_desktop_bridge(monkeypatch):
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

    result = json.loads(BrowserActionTool()._run(action="snapshot", url="https://example.com"))

    assert result["ok"] is True
    assert captured["url"] == "http://127.0.0.1:9876/browser"
    assert captured["auth"] == "Bearer bridge-token"
