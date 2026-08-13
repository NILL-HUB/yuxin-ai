import json
import importlib
from types import SimpleNamespace

from internal.core.tools.builtin_tools.providers.code_execution_tool.execute_code import (
    ExecuteCodeTool,
    _enabled,
)


def test_disabled_by_default(monkeypatch):
    monkeypatch.delenv("ENABLE_CODE_EXECUTION_TOOL", raising=False)
    assert _enabled() is False


def test_disabled_without_credentials(monkeypatch):
    monkeypatch.setenv("ENABLE_CODE_EXECUTION_TOOL", "1")
    monkeypatch.delenv("E2B_API_KEY", raising=False)
    monkeypatch.delenv("E2B_DOMAIN", raising=False)
    assert _enabled() is False


def test_enabled_with_credentials(monkeypatch):
    monkeypatch.setenv("ENABLE_CODE_EXECUTION_TOOL", "1")
    monkeypatch.setenv("E2B_API_KEY", "e2b_test")
    monkeypatch.setenv("E2B_DOMAIN", "sandbox.example.com")
    assert _enabled() is True


def test_tool_returns_disabled_message(monkeypatch):
    monkeypatch.delenv("ENABLE_CODE_EXECUTION_TOOL", raising=False)
    result = json.loads(ExecuteCodeTool()._run(command="python3 -c 'print(1)'"))
    assert result["ok"] is False
    assert "未启用" in result["error"]


def test_tool_executes_via_backend(monkeypatch):
    monkeypatch.setenv("ENABLE_CODE_EXECUTION_TOOL", "1")
    monkeypatch.setenv("E2B_API_KEY", "e2b_test")
    monkeypatch.setenv("E2B_DOMAIN", "sandbox.example.com")

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
    result = json.loads(ExecuteCodeTool()._run(command="python3 -c 'print(1+1)'"))
    assert result["ok"] is True
    assert result["output"] == "2\n"


def _enabled_env(monkeypatch):
    monkeypatch.setenv("ENABLE_CODE_EXECUTION_TOOL", "1")
    monkeypatch.setenv("E2B_API_KEY", "e2b_test")
    monkeypatch.setenv("E2B_DOMAIN", "sandbox.example.com")


def test_tool_prefetches_tool_calls_into_env(monkeypatch):
    _enabled_env(monkeypatch)
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
    _enabled_env(monkeypatch)

    class _FakeBackend:
        def __init__(self, *args, **kwargs):
            pass

        def execute(self, command):
            return SimpleNamespace(exit_code=0, output="", truncated=False, error=None)

    module = importlib.import_module(
        "internal.core.tools.builtin_tools.providers.code_execution_tool.execute_code"
    )
    monkeypatch.setattr(module, "_BACKEND_CLS", _FakeBackend)

    result = json.loads(
        ExecuteCodeTool()._run(
            command="echo done",
            tool_calls=[{"name": "missing_tool", "arguments": {}}],
        )
    )

    assert result["tool_results"][0]["ok"] is False
    assert result["tool_results"][0]["error"] == "tool_not_available"
