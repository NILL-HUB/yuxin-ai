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
