"""CLI 工具进入运行时装配（选中候选 → LangChain 工具）。

验证 `AssistantAgentService._load_non_mcp_tool` 对 `source_type="cli"` 的分派：
按 provider_id 取 cli_provider，并以选中工具名装配（复用 McpToolFactory 的 raw 通道）。
"""

from __future__ import annotations

from types import SimpleNamespace

from internal.entity.runtime_tool_entity import RuntimeToolDescriptor
from internal.service.assistant_agent_service import AssistantAgentService


def _service(cli_service):
    return AssistantAgentService(
        db=None,
        faiss_service=None,
        conversation_service=None,
        redis_client=None,
        app_config_service=SimpleNamespace(),
        cli_service=cli_service,
    )


def _cli_descriptor() -> RuntimeToolDescriptor:
    return RuntimeToolDescriptor(
        tool_id="cli:p1:caption",
        runtime_name="cli__caption",
        name="caption",
        description="一站式生成字幕并烧录",
        source_type="cli",
        provider_id="p1",
        provider_name="VideoCaptioner",
    )


def test_load_non_mcp_tool_dispatches_cli():
    calls: dict = {}

    class _FakeCliService:
        def get_provider(self, provider_id):
            calls["provider_id"] = provider_id
            return SimpleNamespace(id=provider_id)

        def build_selected_tools(self, providers, tool_names=None):
            calls["providers"] = providers
            calls["tool_names"] = tool_names
            return ["cli-tool-obj"]

    svc = _service(_FakeCliService())

    result = svc._load_non_mcp_tool(_cli_descriptor(), account_id="acct")

    assert result == "cli-tool-obj"
    assert calls["provider_id"] == "p1"
    assert calls["tool_names"] == ["caption"]
    assert len(calls["providers"]) == 1


def test_load_non_mcp_tool_cli_requires_service():
    svc = _service(None)

    assert svc._load_non_mcp_tool(_cli_descriptor(), account_id="acct") is None


def test_load_non_mcp_tool_cli_missing_provider_returns_none():
    class _FakeCliService:
        def get_provider(self, provider_id):
            return None

    svc = _service(_FakeCliService())

    assert svc._load_non_mcp_tool(_cli_descriptor(), account_id="acct") is None


def test_load_non_mcp_tool_cli_missing_tool_name_returns_none():
    class _FakeCliService:
        def get_provider(self, provider_id):  # pragma: no cover - 不应被调用
            raise AssertionError("不应在缺少 tool_name 时查询 provider")

    svc = _service(_FakeCliService())
    descriptor = _cli_descriptor()
    descriptor.name = ""

    assert svc._load_non_mcp_tool(descriptor, account_id="acct") is None


def test_load_non_mcp_tool_cli_empty_tools_returns_none():
    class _FakeCliService:
        def get_provider(self, provider_id):
            return SimpleNamespace(id=provider_id)

        def build_selected_tools(self, providers, tool_names=None):
            return []

    svc = _service(_FakeCliService())

    assert svc._load_non_mcp_tool(_cli_descriptor(), account_id="acct") is None
