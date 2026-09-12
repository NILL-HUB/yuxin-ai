from scripts import computer_control_worker as ccw
from scripts.computer_control_worker import _run_actions, _validate_actions


def test_validate_actions_normalizes_mixed_sequence():
    actions, error = _validate_actions(
        [
            {"action": "move", "x": 100, "y": 200},
            {"action": "click", "x": 100, "y": 200, "button": "right"},
            {"action": "type", "text": "hello"},
            {"action": "hotkey", "keys": ["ctrl", "c"]},
        ]
    )

    assert error == ""
    assert [item["action"] for item in actions] == ["move", "click", "type", "hotkey"]
    assert actions[1]["button"] == "right"


def test_validate_actions_rejects_unsupported_action():
    _, error = _validate_actions([{"action": "shell", "command": "rm -rf"}])
    assert "不支持的计算机操作" in error


def test_validate_actions_rejects_bad_coordinate():
    _, error = _validate_actions([{"action": "click", "x": "abc", "y": 1}])
    assert "需要整数 x/y" in error


def test_validate_actions_rejects_unknown_key():
    _, error = _validate_actions([{"action": "press", "key": "super-secret-key"}])
    assert "不支持的按键" in error


def test_run_actions_returns_install_error_when_no_backend(monkeypatch):
    """两个后端都不可用时返回明确错误（强制 pyautogui 后端 + 模拟依赖缺失）。"""
    actions, _ = _validate_actions([{"action": "move", "x": 1, "y": 1}])
    monkeypatch.setattr(ccw, "_resolve_backend", lambda explicit="": "pyautogui")
    monkeypatch.setattr(ccw, "_run_actions_pyautogui", lambda acts: {
        "ok": False,
        "error": "计算机控制 worker 未安装 pyautogui，且 cua-driver 后端不可用；"
                 "请安装 cua-driver 或 pip install pyautogui pillow",
    })
    result = _run_actions(actions)
    assert result["ok"] is False
    assert "pyautogui" in result["error"]


def test_cua_only_action_fails_without_cua_driver(monkeypatch):
    """cua 专有能力（如 capture）在无 cua-driver 时返回明确错误。"""
    monkeypatch.setattr(ccw.cua_driver_client, "is_available", lambda: False)
    actions, error = _validate_actions([{"action": "capture", "pid": 1, "window_id": 2}])
    assert error == ""
    result = _run_actions(actions)
    assert result["ok"] is False
    assert "cua-driver" in result["error"]


def test_capture_action_normalizes_cua_params():
    """capture 动作应保留 pid/window_id 与截图开关。"""
    actions, error = _validate_actions([
        {"action": "capture", "pid": 100, "window_id": 200, "include_screenshot": False},
    ])
    assert error == ""
    assert actions[0]["pid"] == 100
    assert actions[0]["window_id"] == 200
    assert actions[0]["include_screenshot"] is False
    assert actions[0]["include_accessibility_tree"] is True


def test_click_action_accepts_element_index_without_coordinates():
    """cua 元素寻址：带 element_index 时不需要 x/y。"""
    actions, error = _validate_actions([
        {"action": "click", "pid": 1, "window_id": 2, "element_index": 7},
    ])
    assert error == ""
    assert actions[0]["element_index"] == 7
    assert "x" not in actions[0]


def test_launch_app_requires_target():
    _, error = _validate_actions([{"action": "launch_app"}])
    assert "launch_app" in error
