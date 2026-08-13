import importlib
import json

from internal.core.tools.builtin_tools.providers.codex_os.os_file_task import (
    OsFileTaskTool,
    os_file_task,
)


def test_os_file_task_read_calls_host_worker(monkeypatch):
    monkeypatch.setenv("OS_AUTOMATION_URL", "http://127.0.0.1:8765")
    monkeypatch.setenv("OS_AUTOMATION_TOKEN", "test-token")
    captured = {}

    class _FakeResponse:
        def read(self):
            return json.dumps(
                {
                    "ok": True,
                    "path": "C:/tmp/notes.txt",
                    "content": "hello",
                    "truncated": False,
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
        "internal.core.tools.builtin_tools.providers.codex_os.os_file_task"
    )
    monkeypatch.setattr(module.urllib.request, "urlopen", _fake_urlopen)
    tool = OsFileTaskTool(requester="user-1")

    result = json.loads(tool._run(op="read", path="C:/tmp/notes.txt"))

    assert result["ok"] is True
    assert result["content"] == "hello"
    assert captured["request"].full_url.endswith("/file")
    body = json.loads(captured["request"].data)
    assert body["op"] == "read"
    assert body["path"] == "C:/tmp/notes.txt"
    assert body["requester"] == "user-1"
    assert captured["request"].headers["Authorization"] == "Bearer test-token"


def test_os_file_task_returns_config_error_when_unconfigured(monkeypatch):
    monkeypatch.delenv("OS_AUTOMATION_URL", raising=False)
    monkeypatch.delenv("OS_AUTOMATION_TOKEN", raising=False)

    result = json.loads(
        os_file_task()._run(op="patch", patch="*** Begin Patch\n*** End Patch\n")
    )

    assert result["ok"] is False
    assert "未配置" in result["error"]
