import importlib
import json

from internal.core.tools.builtin_tools.providers.host_os.os_terminal import (
    OsTerminalTool,
    os_terminal,
)


module = importlib.import_module(
    "internal.core.tools.builtin_tools.providers.host_os.os_terminal"
)


def test_os_terminal_returns_disabled_error_when_not_configured(monkeypatch):
    monkeypatch.delenv("OS_AUTOMATION_URL", raising=False)
    monkeypatch.delenv("OS_AUTOMATION_TOKEN", raising=False)

    result = json.loads(OsTerminalTool()._run(command="echo hi"))

    assert result["ok"] is False
    # 统一文案（DESKTOP_UNAVAILABLE_MESSAGE）：引导安装/登录桌面客户端
    assert "桌面客户端" in result["error"]


def test_os_terminal_passes_payload(monkeypatch):
    captured = {}

    def fake_call_worker(payload, *, timeout=60):
        captured.update(payload)
        captured["_timeout"] = timeout
        return {"ok": True, "exit_code": 0, "stdout": "hi\n", "stderr": ""}

    monkeypatch.setattr(module, "_call_worker", fake_call_worker)

    result = json.loads(
        OsTerminalTool(requester="user-1")._run(
            command="echo hi",
            shell="gitbash",
            working_dir="D:/work",
            timeout_seconds=120,
        )
    )

    assert result["ok"] is True
    assert captured["command"] == "echo hi"
    assert captured["shell"] == "gitbash"
    assert captured["working_dir"] == "D:/work"
    assert captured["timeout_seconds"] == 120
    assert captured["requester"] == "user-1"
    # urllib 超时必须大于命令自身超时，否则超时结果在回传前被客户端掐断
    assert captured["_timeout"] == 150


def test_os_terminal_defaults_to_gitbash(monkeypatch):
    """默认 gitbash：Unix 语法对模型更友好，Windows 原生命令需显式 shell=cmd。"""
    captured = {}

    def fake_call_worker(payload, *, timeout=60):
        captured.update(payload)
        return {"ok": True}

    monkeypatch.setattr(module, "_call_worker", fake_call_worker)

    OsTerminalTool()._run(command="ls -la")

    assert captured["shell"] == "gitbash"
    assert captured["timeout_seconds"] == 60


def test_os_terminal_clamps_timeout(monkeypatch):
    captured = {}

    def fake_call_worker(payload, *, timeout=60):
        captured.update(payload)
        return {"ok": True}

    monkeypatch.setattr(module, "_call_worker", fake_call_worker)

    OsTerminalTool()._run(command="dir", timeout_seconds=9999)

    assert captured["timeout_seconds"] == 300


def test_os_terminal_passes_blocked_result_through(monkeypatch):
    """删除守卫拒绝结果原样透传（含 blocked/reason 引导），Agent 据此改用 os_recycle_bin。"""
    blocked = {
        "ok": False,
        "blocked": True,
        "command": "rm -rf build",
        "reason": "终端删除命令已被系统阻断（rm）。请调用 os_recycle_bin(...)",
        "error": "终端删除命令已被系统阻断（rm）。请调用 os_recycle_bin(...)",
    }

    def fake_call_worker(payload, *, timeout=60):
        return blocked

    monkeypatch.setattr(module, "_call_worker", fake_call_worker)

    result = json.loads(OsTerminalTool()._run(command="rm -rf build"))

    assert result["blocked"] is True
    assert "os_recycle_bin" in result["reason"]


def test_os_terminal_http_path_uses_worker_client(monkeypatch):
    """真实 HTTP 路径：经 worker_client 发往 /exec，携带 Bearer worker token。"""
    monkeypatch.setenv("OS_AUTOMATION_URL", "http://127.0.0.1:8765")
    monkeypatch.setenv("OS_AUTOMATION_TOKEN", "test-token")
    captured = {}

    class _FakeResponse:
        def read(self):
            return json.dumps({"ok": True, "exit_code": 0, "stdout": "ok\n"}).encode("utf-8")

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

    def _fake_urlopen(request, timeout):
        captured["request"] = request
        captured["timeout"] = timeout
        return _FakeResponse()

    worker_client = importlib.import_module(
        "internal.core.tools.builtin_tools.providers.worker_client"
    )
    monkeypatch.setattr(worker_client.urllib.request, "urlopen", _fake_urlopen)

    result = json.loads(OsTerminalTool(requester="user-1")._run(command="echo ok"))

    assert result["ok"] is True
    assert captured["request"].full_url.endswith("/exec")
    body = json.loads(captured["request"].data)
    assert body["command"] == "echo ok"
    assert body["requester"] == "user-1"
    assert captured["request"].headers["Authorization"] == "Bearer test-token"
    assert captured["timeout"] >= 60


def test_os_terminal_factory_binds_requester():
    tool = os_terminal(requester="user-1")
    assert tool.requester == "user-1"
    assert tool.name == "os_terminal"
