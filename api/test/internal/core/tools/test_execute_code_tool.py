import json
import importlib
from contextlib import contextmanager
from types import SimpleNamespace

from internal.core.tools.builtin_tools.providers.code_execution_tool.execute_code import (
    ExecuteCodeTool,
    _enabled,
)


@contextmanager
def _code_interpreter_runtime(enabled=True):
    """注册一个确定性的 code_interpreter 运行时（替代真实 service/DB）。"""
    from internal.core.agent import sandbox_runtime_registry as registry
    from internal.core.agent.entities.sandbox_runtime_entity import (
        BACKEND_BAIDU_CFC,
        BACKEND_DISABLED,
        CAPABILITY_CODE_INTERPRETER,
        SandboxRuntime,
    )

    def _loader(capability):
        if capability != CAPABILITY_CODE_INTERPRETER:
            return SandboxRuntime(capability=capability, enabled=False)
        return SandboxRuntime(
            capability=capability,
            backend=BACKEND_BAIDU_CFC if enabled else BACKEND_DISABLED,
            enabled=enabled,
        )

    registry.register_sandbox_runtime_loader(_loader)
    registry.invalidate_sandbox_runtime_cache()
    try:
        yield registry
    finally:
        registry._loader = None
        registry.invalidate_sandbox_runtime_cache()


def test_disabled_by_default(monkeypatch):
    monkeypatch.delenv("ENABLE_CODE_EXECUTION_TOOL", raising=False)
    assert _enabled() is False


def test_disabled_without_runtime(monkeypatch):
    monkeypatch.setenv("ENABLE_CODE_EXECUTION_TOOL", "1")
    with _code_interpreter_runtime(enabled=False):
        assert _enabled() is False


def test_enabled_when_runtime_enabled(monkeypatch):
    monkeypatch.setenv("ENABLE_CODE_EXECUTION_TOOL", "1")
    with _code_interpreter_runtime(enabled=True):
        assert _enabled() is True


def test_tool_returns_disabled_message(monkeypatch):
    monkeypatch.delenv("ENABLE_CODE_EXECUTION_TOOL", raising=False)
    result = json.loads(ExecuteCodeTool()._run(command="python3 -c 'print(1)'"))
    assert result["ok"] is False
    assert "未启用" in result["error"]


def test_tool_executes_via_backend(monkeypatch):
    monkeypatch.setenv("ENABLE_CODE_EXECUTION_TOOL", "1")

    class _FakeBackend:
        def __init__(self, *args, **kwargs):
            pass

        def execute(self, command):
            assert command == "python3 -c 'print(1+1)'"
            return SimpleNamespace(exit_code=0, output="2\n", truncated=False, error=None)

    module = importlib.import_module(
        "internal.core.tools.builtin_tools.providers.code_execution_tool.execute_code"
    )
    monkeypatch.setattr(module, "_BACKEND_CLS", _FakeBackend)
    with _code_interpreter_runtime(enabled=True):
        result = json.loads(ExecuteCodeTool()._run(command="python3 -c 'print(1+1)'"))
    assert result["ok"] is True
    assert result["output"] == "2\n"


def test_tool_prefetches_tool_calls_into_env(monkeypatch):
    monkeypatch.setenv("ENABLE_CODE_EXECUTION_TOOL", "1")
    captured = {}

    class _FakeBackend:
        def __init__(self, *args, **kwargs):
            pass

        def execute(self, command):
            captured["command"] = command
            return SimpleNamespace(exit_code=0, output="ok\n", truncated=False, error=None)

    module = importlib.import_module(
        "internal.core.tools.builtin_tools.providers.code_execution_tool.execute_code"
    )
    monkeypatch.setattr(module, "_BACKEND_CLS", _FakeBackend)

    fake_tool = SimpleNamespace(
        name="web_search",
        invoke=lambda arguments: {"results": [{"title": "结果"}]},
    )
    tool = ExecuteCodeTool(tool_registry={"web_search": fake_tool})

    with _code_interpreter_runtime(enabled=True):
        result = json.loads(
            tool._run(
                command="python3 -c 'import os; print(os.environ.get(\"TOOL_RESULTS_JSON\"))'",
                tool_calls=[{"name": "web_search", "arguments": {"query": "测试"}}],
            )
        )

    assert result["ok"] is True
    assert result["tool_results"][0]["ok"] is True
    assert result["tool_results"][0]["name"] == "web_search"
    assert captured["command"].startswith("export TOOL_RESULTS_JSON=")


def test_tool_reports_missing_prefetched_tool(monkeypatch):
    monkeypatch.setenv("ENABLE_CODE_EXECUTION_TOOL", "1")

    class _FakeBackend:
        def __init__(self, *args, **kwargs):
            pass

        def execute(self, command):
            return SimpleNamespace(exit_code=0, output="", truncated=False, error=None)

    module = importlib.import_module(
        "internal.core.tools.builtin_tools.providers.code_execution_tool.execute_code"
    )
    monkeypatch.setattr(module, "_BACKEND_CLS", _FakeBackend)

    with _code_interpreter_runtime(enabled=True):
        result = json.loads(
            ExecuteCodeTool()._run(
                command="echo done",
                tool_calls=[{"name": "missing_tool", "arguments": {}}],
            )
        )

    assert result["tool_results"][0]["ok"] is False
    assert result["tool_results"][0]["error"] == "tool_not_available"


# ── 沙箱产物回收 ───────────────────────────────────────────────────────────


class _ArtifactBackend:
    """带文件下载能力的假后端：记录命令、返回标记/扫描/执行三类响应。"""

    marker_name = ".yujianwo_artifact_marker_artifacts"

    def __init__(self, *args, **kwargs):
        self.commands: list[str] = []
        self.downloaded: list[list[str]] = []
        self.closed = False
        self.scan_paths: list[str] = ["/mnt/data/report.csv"]
        self.download_error = None

    def execute(self, command, timeout=None):
        self.commands.append(command)
        if " -type f" in command:  # 产物扫描
            output = "\n".join(self.scan_paths)
            return SimpleNamespace(exit_code=0, output=output, truncated=False, error=None)
        if self.marker_name in command:  # 执行前打标记
            return SimpleNamespace(
                exit_code=0,
                output=f"/mnt/data/{self.marker_name}\n",
                truncated=False,
                error=None,
            )
        return SimpleNamespace(exit_code=0, output="ok\n", truncated=False, error=None)

    def download_files(self, paths):
        self.downloaded.append(list(paths))
        return [
            SimpleNamespace(
                path=path,
                content=None if self.download_error else b"a,b\n1,2\n",
                error=self.download_error,
            )
            for path in paths
        ]

    def close(self):
        self.closed = True


def _patch_artifact_backend(monkeypatch, backend):
    module = importlib.import_module(
        "internal.core.tools.builtin_tools.providers.code_execution_tool.execute_code"
    )
    monkeypatch.setattr(module, "_BACKEND_CLS", lambda *_args, **_kwargs: backend)
    return module


def _patch_file_center(monkeypatch):
    saved = SimpleNamespace(
        id="f1", name="report.csv", size=8, extension="csv", mime_type="text/csv"
    )
    calls: list[dict] = []

    def _save_generated_asset(account_id, *, filename, content, mime_type="", folder=""):
        calls.append({"account_id": account_id, "filename": filename, "folder": folder})
        return {"upload_file": saved, "url": f"https://cdn.example.com/{filename}"}

    monkeypatch.setattr(
        "app.http.module.injector",
        SimpleNamespace(get=lambda _cls: SimpleNamespace(save_generated_asset=_save_generated_asset)),
    )
    return calls


def test_tool_collects_artifacts_and_closes_sandbox(monkeypatch):
    monkeypatch.setenv("ENABLE_CODE_EXECUTION_TOOL", "1")
    backend = _ArtifactBackend()
    _patch_artifact_backend(monkeypatch, backend)
    calls = _patch_file_center(monkeypatch)

    with _code_interpreter_runtime(enabled=True):
        result = json.loads(
            ExecuteCodeTool(account_id="acc-1")._run(command="python3 gen_report.py")
        )

    assert result["ok"] is True
    assert result["output"] == "ok\n"
    assert len(result["artifacts"]) == 1
    assert result["artifacts"][0]["name"] == "report.csv"
    assert result["artifacts"][0]["url"] == "https://cdn.example.com/report.csv"
    assert calls[0]["account_id"] == "acc-1"
    assert calls[0]["folder"] == "artifacts"
    # 每次调用都是独立沙箱：执行完必须销毁，否则会一直挂到沙箱超时
    assert backend.closed is True
    # 打标记 → 执行 → 扫描，且真实命令在标记之后执行
    assert backend.commands[1] == "python3 gen_report.py"


def test_tool_reports_artifact_failure_without_breaking_command_result(monkeypatch):
    monkeypatch.setenv("ENABLE_CODE_EXECUTION_TOOL", "1")
    backend = _ArtifactBackend()
    backend.download_error = "sandbox gone"
    _patch_artifact_backend(monkeypatch, backend)
    _patch_file_center(monkeypatch)

    with _code_interpreter_runtime(enabled=True):
        result = json.loads(
            ExecuteCodeTool(account_id="acc-1")._run(command="python3 gen_report.py")
        )

    assert result["ok"] is True  # 命令本身成功
    assert "artifacts" not in result
    assert result["artifact_failures"] == [
        {"path": "/mnt/data/report.csv", "error": "sandbox gone"}
    ]
    assert backend.closed is True


def test_tool_skips_collection_without_account(monkeypatch):
    monkeypatch.setenv("ENABLE_CODE_EXECUTION_TOOL", "1")
    backend = _ArtifactBackend()
    _patch_artifact_backend(monkeypatch, backend)

    with _code_interpreter_runtime(enabled=True):
        result = json.loads(ExecuteCodeTool()._run(command="python3 gen_report.py"))

    assert result["ok"] is True
    assert "artifacts" not in result
    assert "artifact_failures" not in result
    # 无账号即不入库：不下载、也不额外打标记/扫描
    assert backend.downloaded == []
    assert backend.commands == ["python3 gen_report.py"]
    assert backend.closed is True


def test_tool_closes_sandbox_even_when_command_raises(monkeypatch):
    monkeypatch.setenv("ENABLE_CODE_EXECUTION_TOOL", "1")

    class _ExplodingBackend(_ArtifactBackend):
        def execute(self, command, timeout=None):
            self.commands.append(command)
            if self.marker_name in command:
                return SimpleNamespace(exit_code=0, output="", truncated=False, error=None)
            raise RuntimeError("sandbox execute failed")

    backend = _ExplodingBackend()
    _patch_artifact_backend(monkeypatch, backend)

    with _code_interpreter_runtime(enabled=True):
        result = json.loads(
            ExecuteCodeTool(account_id="acc-1")._run(command="python3 gen_report.py")
        )

    assert result["ok"] is False
    assert "sandbox execute failed" in result["error"]
    assert backend.closed is True

