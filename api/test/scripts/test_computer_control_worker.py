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


def test_run_actions_returns_install_error_without_pyautogui():
    actions, _ = _validate_actions([{"action": "move", "x": 1, "y": 1}])
    result = _run_actions(actions)
    assert result["ok"] is False
    assert "pyautogui" in result["error"]
