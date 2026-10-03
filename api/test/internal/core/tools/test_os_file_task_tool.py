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

    # HTTP 调用已收敛到 worker_client（builtin provider 单一入口），注入点随之迁移
    worker_client = importlib.import_module(
        "internal.core.tools.builtin_tools.providers.worker_client"
    )
    monkeypatch.setattr(worker_client.urllib.request, "urlopen", _fake_urlopen)
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

    # HTTP 调用已收敛到 worker_client（builtin provider 单一入口），注入点随之迁移
    worker_client = importlib.import_module(
        "internal.core.tools.builtin_tools.providers.worker_client"
    )
    monkeypatch.setattr(worker_client.urllib.request, "urlopen", _fake_urlopen)
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
    # 统一文案（DESKTOP_UNAVAILABLE_MESSAGE）：引导安装/登录桌面客户端，而非只抛内部 env 名
    assert "桌面客户端" in result["error"]


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


def test_os_file_task_passes_bound_device_id_and_targets_it(monkeypatch):
    """会话绑定的设备随 payload 下传，bridge 解析按指定设备进行。"""
    captured = {}

    def fake_resolve(account_id=None, *, purpose="", device_id=None):
        captured["resolved_device"] = device_id
        return "http://host.docker.internal:9876", "bridge-token"

    monkeypatch.setattr(
        "internal.service.desktop_bridge_resolver.resolve_desktop_bridge", fake_resolve
    )

    class _FakeResponse:
        def read(self):
            return json.dumps({"ok": True, "content": "hi", "truncated": False}).encode("utf-8")

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

    def _fake_urlopen(request, timeout):
        captured["request"] = request
        return _FakeResponse()

    worker_client = importlib.import_module(
        "internal.core.tools.builtin_tools.providers.worker_client"
    )
    monkeypatch.setattr(worker_client.urllib.request, "urlopen", _fake_urlopen)

    OsFileTaskTool(requester="user-1", device_id="dev-2")._run(
        op="read", path="C:/tmp/notes.txt"
    )

    body = json.loads(captured["request"].data)
    assert body["device_id"] == "dev-2"
    assert captured["resolved_device"] == "dev-2"
    assert captured["request"].full_url == "http://host.docker.internal:9876/file"


def test_os_file_task_specified_device_offline_reports_device_message(monkeypatch):
    """指定设备解析不命中：返回设备离线文案，不回退静态配置、不发请求。"""
    monkeypatch.setenv("OS_AUTOMATION_URL", "http://worker:8765")
    monkeypatch.setenv("OS_AUTOMATION_TOKEN", "os-token")
    monkeypatch.setattr(
        "internal.service.desktop_bridge_resolver.resolve_desktop_bridge",
        lambda account_id=None, *, purpose="", device_id=None: None,
    )
    called = {"urlopen": False}
    worker_client = importlib.import_module(
        "internal.core.tools.builtin_tools.providers.worker_client"
    )

    def _boom(*_args, **_kwargs):
        called["urlopen"] = True
        raise AssertionError("不应发起 HTTP 请求")

    monkeypatch.setattr(worker_client.urllib.request, "urlopen", _boom)

    result = json.loads(
        OsFileTaskTool(requester="user-1", device_id="dev-2")._run(op="read", path="x")
    )

    assert result["ok"] is False
    assert "指定的设备" in result["error"]
    assert called["urlopen"] is False
