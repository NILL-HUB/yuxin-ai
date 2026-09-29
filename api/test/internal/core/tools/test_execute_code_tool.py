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
