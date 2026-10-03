import importlib
import json
import urllib.request

from internal.core.tools.builtin_tools.providers.computer_control.computer_action import (
    ComputerActionInput,
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
    # 诚实降级：必须说明「本机操作只能由桌面客户端完成」，而不是暗示 Web 端可操作本机
    assert "在线桌面设备" in result["error"]
    assert "桌面客户端" in result["error"]


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


def test_computer_action_contract_exposes_cua_observability():
    """契约层：Agent 必须能从 schema 描述发现 cua 观察-行动能力。"""
    description = ComputerActionInput.model_fields["actions"].description or ""
    for token in (
        "capture",
        "include_accessibility_tree",
        "element_index",
        "element_token",
        "pid",
        "window_id",
        "list_apps",
        "list_windows",
        "launch_app",
        "double_click",
        "right_click",
        "drag",
        "set_value",
        "verified",
        "escalation",
        "return_base64",
    ):
        assert token in description, f"actions 描述缺少能力 token: {token}"


def test_computer_action_tool_description_teaches_observe_act():
    tool_desc = ComputerActionTool().description
    assert "capture" in tool_desc
    assert "元素树" in tool_desc
    assert "element_index" in tool_desc


def test_computer_action_replaces_screenshot_base64_with_url(monkeypatch):
    """base64 绝不进工具结果：替换为存储 URL + markdown 内联。"""
    monkeypatch.setattr(
        module,
        "_call_worker",
        lambda payload: {"ok": True, "screenshot_base64": "aGVsbG8=", "results": []},
    )
    monkeypatch.setattr(
        module,
        "_persist_screenshot",
        lambda b64, requester: "https://cdn.example.com/computer_control_abc.png",
    )

    result = json.loads(
        ComputerActionTool(requester="acct-1")._run(
            actions=[{"action": "screenshot", "return_base64": True}]
        )
    )

    assert "screenshot_base64" not in result
    assert result["screenshot_url"] == "https://cdn.example.com/computer_control_abc.png"
    assert result["screenshot"] == "![screenshot](https://cdn.example.com/computer_control_abc.png)"
    assert result["screenshot_saved"] is True


def test_computer_action_screenshot_persist_failure_hides_base64(monkeypatch):
    """存储失败：标注 screenshot_saved=false，仍不回传 base64。"""
    monkeypatch.setattr(
        module,
        "_call_worker",
        lambda payload: {"ok": True, "screenshot_base64": "aGVsbG8="},
    )

    def boom(base64_str, requester):
        raise RuntimeError("storage down")

    monkeypatch.setattr(module, "_persist_screenshot", boom)

    result = json.loads(
        ComputerActionTool(requester="acct-1")._run(
            actions=[{"action": "screenshot", "return_base64": True}]
        )
    )

    assert "screenshot_base64" not in result
    assert result["screenshot_saved"] is False
    assert result["ok"] is True


def test_computer_action_result_without_screenshot_unchanged(monkeypatch):
    monkeypatch.setattr(
        module,
        "_call_worker",
        lambda payload: {"ok": True, "results": [{"action": "click", "ok": True}]},
    )

    result = json.loads(
        ComputerActionTool()._run(actions=[{"action": "click", "x": 1, "y": 1}])
    )

    assert "screenshot_url" not in result
    assert "screenshot_saved" not in result
    assert "screenshot_base64" not in result
    assert result["results"] == [{"action": "click", "ok": True}]


def test_computer_action_invalid_base64_marks_unsaved(monkeypatch):
    """非法 base64：真实 _persist_screenshot 在解码处抛错 → screenshot_saved=False，无 base64。"""
    monkeypatch.setattr(
        module,
        "_call_worker",
        lambda payload: {"ok": True, "screenshot_base64": "not-valid-base64!!!"},
    )

    result = json.loads(
        ComputerActionTool(requester="acct-1")._run(
            actions=[{"action": "screenshot", "return_base64": True}]
        )
    )

    assert "screenshot_base64" not in result
    assert result["screenshot_saved"] is False
