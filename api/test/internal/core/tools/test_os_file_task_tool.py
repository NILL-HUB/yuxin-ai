import importlib
import json
import urllib.request

from internal.core.tools.builtin_tools.providers.host_os.os_file_task import (
    OsFileTaskTool,
    os_file_task,
)


module = importlib.import_module(
    "internal.core.tools.builtin_tools.providers.host_os.os_file_task"
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
        "internal.core.tools.builtin_tools.providers.host_os.os_file_task"
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


def test_os_file_task_passes_session_context_to_worker(monkeypatch):
    """工具把 session_id / conversation_turn 随 payload 传给 worker（快照按轮回滚的链路）。"""
    monkeypatch.setenv("OS_AUTOMATION_URL", "http://127.0.0.1:8765")
    monkeypatch.setenv("OS_AUTOMATION_TOKEN", "test-token")
    captured = {}

    class _FakeResponse:
        def read(self):
            return json.dumps({"ok": True, "results": [], "errors": []}).encode("utf-8")

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

    def _fake_urlopen(request, timeout):
        captured["request"] = request
        return _FakeResponse()

    module = importlib.import_module(
        "internal.core.tools.builtin_tools.providers.host_os.os_file_task"
    )
    monkeypatch.setattr(module.urllib.request, "urlopen", _fake_urlopen)
    tool = OsFileTaskTool(
        requester="user-1",
        session_id="conv-9",
        conversation_turn="conv-9:msg-1",
    )

    result = json.loads(tool._run(op="patch", patch="*** Begin Patch\n*** End Patch\n"))

    assert result["ok"] is True
    body = json.loads(captured["request"].data)
    assert body["session_id"] == "conv-9"
    assert body["conversation_turn"] == "conv-9:msg-1"
    assert body["requester"] == "user-1"


def test_os_file_task_factory_binds_session_context(monkeypatch):
    """工厂透传：os_file_task(session_id=..., conversation_turn=...) 绑定到工具实例。"""
    tool = os_file_task(
        requester="user-1",
        session_id="conv-9",
        conversation_turn="conv-9:msg-1",
    )
    assert tool.requester == "user-1"
    assert tool.session_id == "conv-9"
    assert tool.conversation_turn == "conv-9:msg-1"


def test_os_file_task_returns_config_error_when_unconfigured(monkeypatch):
    monkeypatch.delenv("OS_AUTOMATION_URL", raising=False)
    monkeypatch.delenv("OS_AUTOMATION_TOKEN", raising=False)

    result = json.loads(
        os_file_task()._run(op="patch", patch="*** Begin Patch\n*** End Patch\n")
    )

    assert result["ok"] is False
    assert "未配置" in result["error"]


def test_os_file_task_uses_desktop_bridge(monkeypatch):
    """三 os 工具统一：桥优先，/file 经 DESKTOP_BRIDGE_URL/TOKEN 转发。"""
    monkeypatch.setenv("DESKTOP_BRIDGE_URL", "http://127.0.0.1:9876")
    monkeypatch.setenv("DESKTOP_BRIDGE_TOKEN", "bridge-token")
    captured = {}

    class _FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def read(self):
            return b'{"ok":true,"content":"hello","truncated":false}'

    def fake_urlopen(request, timeout=None):
        captured["url"] = request.full_url
        captured["auth"] = request.headers.get("Authorization")
        return _FakeResponse()

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)

    result = json.loads(OsFileTaskTool()._run(op="read", path="C:/tmp/notes.txt"))

    assert result["ok"] is True
    assert captured["url"] == "http://127.0.0.1:9876/file"
    assert captured["auth"] == "Bearer bridge-token"


def test_os_file_task_appends_file_path_for_os_automation_url(monkeypatch):
    """OS_AUTOMATION_URL 分支必须拼接 /file。"""
    monkeypatch.delenv("DESKTOP_BRIDGE_URL", raising=False)
    monkeypatch.delenv("DESKTOP_BRIDGE_TOKEN", raising=False)
    monkeypatch.setenv("OS_AUTOMATION_URL", "http://worker:8765")
    monkeypatch.setenv("OS_AUTOMATION_TOKEN", "os-token")
    captured = {}

    class _FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def read(self):
            return b'{"ok":true,"content":"hello","truncated":false}'

    def fake_urlopen(request, timeout=None):
        captured["url"] = request.full_url
        captured["auth"] = request.headers.get("Authorization")
        return _FakeResponse()

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)

    result = json.loads(OsFileTaskTool()._run(op="read", path="C:/tmp/notes.txt"))

    assert result["ok"] is True
    assert captured["url"] == "http://worker:8765/file"
    assert captured["auth"] == "Bearer os-token"
