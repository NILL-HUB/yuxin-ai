import json
import importlib
from types import SimpleNamespace

from internal.core.tools.builtin_tools.providers.codex_os.run_os_task import (
    RunOsTaskTool,
    run_os_task,
)


def test_run_os_task_tool_calls_host_worker(monkeypatch):
    monkeypatch.setenv("OS_AUTOMATION_URL", "http://127.0.0.1:8765")
    monkeypatch.setenv("OS_AUTOMATION_TOKEN", "test-token")
    captured = {}

    class _FakeResponse:
        def read(self):
            return json.dumps(
                {
                    "ok": True,
                    "mode": "preview",
                    "summary": "计划完成",
                    "approval_token": "token-123",
                }
            ).encode("utf-8")

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

    def _fake_urlopen(request, timeout):
        captured["request"] = request
        captured["timeout"] = timeout
        return _FakeResponse()

    module = importlib.import_module(
        "internal.core.tools.builtin_tools.providers.codex_os.run_os_task"
    )

    monkeypatch.setattr(module.urllib.request, "urlopen", _fake_urlopen)
    tool = RunOsTaskTool(requester="user-1")

    result = json.loads(tool._run(task="清理 C 盘垃圾"))

    assert result["ok"] is True
    assert result["approval_token"] == "token-123"
    body = json.loads(captured["request"].data)
    assert body["task"] == "清理 C 盘垃圾"
    assert body["requester"] == "user-1"
    assert captured["request"].headers["Authorization"] == "Bearer test-token"


def test_run_os_task_tool_returns_config_error_when_unconfigured(monkeypatch):
    monkeypatch.delenv("OS_AUTOMATION_URL", raising=False)
    monkeypatch.delenv("OS_AUTOMATION_TOKEN", raising=False)

    result = json.loads(run_os_task()._run(task="清理 C 盘垃圾"))

    assert result["ok"] is False
    assert "未配置" in result["error"]


def test_run_os_task_apply_rejects_delete_command(monkeypatch):
    """apply 任务含终端删除命令时，本地直接拦截，不调用 worker。"""
    module = importlib.import_module(
        "internal.core.tools.builtin_tools.providers.codex_os.run_os_task"
    )
    called = {}

    def _fake_urlopen(request, timeout):
        called["called"] = True
        raise AssertionError("不应调用 worker")

    monkeypatch.setenv("OS_AUTOMATION_URL", "http://127.0.0.1:8765")
    monkeypatch.setenv("OS_AUTOMATION_TOKEN", "test-token")
    monkeypatch.setattr(module.urllib.request, "urlopen", _fake_urlopen)
    tool = RunOsTaskTool(requester="user-1")

    result = json.loads(
        tool._run(
            task="清理过期文件\nRemove-Item C:\\temp\\x.txt",
            mode="apply",
            approval_token="some-token",
        )
    )

    assert result["ok"] is False
    assert result["blocked"] == "delete_command"
    assert "回收站" in result["error"]
    assert "Remove-Item" in result["detail"]
    assert called.get("called") is None


def test_run_os_task_preview_delete_task_not_blocked(monkeypatch):
    """preview 任务含删除命令时不拦截，正常调用 worker（仅 apply 拦截）。"""
    module = importlib.import_module(
        "internal.core.tools.builtin_tools.providers.codex_os.run_os_task"
    )
    captured = {}

    class _FakeResponse:
        def read(self):
            return json.dumps(
                {
                    "ok": True,
                    "mode": "preview",
                    "summary": "计划完成",
                    "approval_token": "token-123",
                }
            ).encode("utf-8")

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

    def _fake_urlopen(request, timeout):
        captured["called"] = True
        return _FakeResponse()

    monkeypatch.setenv("OS_AUTOMATION_URL", "http://127.0.0.1:8765")
    monkeypatch.setenv("OS_AUTOMATION_TOKEN", "test-token")
    monkeypatch.setattr(module.urllib.request, "urlopen", _fake_urlopen)
    tool = RunOsTaskTool(requester="user-1")

    result = json.loads(
        tool._run(
            task="扫描 C:\\temp 并输出清理计划（示例命令：Remove-Item C:\\temp\\x.txt）",
            mode="preview",
        )
    )

    assert captured.get("called") is True
    assert result["ok"] is True
