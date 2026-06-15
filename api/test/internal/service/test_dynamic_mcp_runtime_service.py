from internal.entity.runtime_tool_entity import RuntimeToolDescriptor
from internal.service.dynamic_mcp_runtime_service import DynamicMcpRuntimeService


class _Collector:
    def collect(self, account_id):
        return [
            {
                "id": "provider-1:search_docs",
                "name": "search_docs",
                "description": "Search docs",
                "source_type": "mcp",
                "provider_id": "provider-1",
                "provider_name": "Docs MCP",
                "inputs": [{"name": "query", "type": "str", "required": True}],
                "metadata": {
                    "tool_pool": "mcp",
                    "capabilities": ["search"],
                    "risk_level": "safe",
                    "permission_scope": "public",
                    "cost_level": "low",
                    "health_status": "healthy",
                    "success_rate": 0.9,
                },
            },
            {
                "id": "provider-2:delete_docs",
                "name": "delete_docs",
                "description": "Delete docs",
                "source_type": "mcp",
                "provider_id": "provider-2",
                "provider_name": "Danger MCP",
                "inputs": [],
                "metadata": {
                    "tool_pool": "mcp",
                    "capabilities": ["delete"],
                    "risk_level": "dangerous",
                    "permission_scope": "public",
                    "cost_level": "low",
                    "health_status": "healthy",
                },
            },
        ]


class _PolicyFilter:
    def filter(self, candidates, **kwargs):
        accepted = [item for item in candidates if item["metadata"]["risk_level"] != "dangerous"]
        rejected = [
            {"id": item["id"], "name": item["name"], "reason": "forbidden"}
            for item in candidates
            if item["metadata"]["risk_level"] == "dangerous"
        ]
        return {"candidates": accepted, "filtered_out_tools": rejected}


def _prebound_tool():
    return RuntimeToolDescriptor(
        tool_id="provider-1:search_docs-prebound",
        runtime_name="mcp__provider_1__search_docs",
        name="search_docs",
        description="Prebound duplicate",
        source_type="mcp",
        provider_id="provider-1",
        provider_name="Docs MCP",
        input_schema=[],
        metadata={"tool_pool": "mcp", "risk_level": "safe"},
        audit_context={"tool_id": "provider-1:search_docs-prebound"},
    )


def test_dynamic_mcp_runtime_should_mount_public_mcp_and_filter_dangerous_tools():
    result = DynamicMcpRuntimeService(
        collector=_Collector(),
        policy_filter=_PolicyFilter(),
    ).build_runtime(
        account_id="account-1",
        agent_id="agent-1",
        request_id="request-1",
        required_capabilities=["search"],
        prebound_tools=[_prebound_tool()],
        max_tool_count=5,
    )

    assert [tool.runtime_name for tool in result["mounted_tools"]] == [
        "mcp__provider_1__search_docs"
    ]
    assert result["mounted_tools"][0].tool_id == "provider-1:search_docs"
    assert result["filtered_out_tools"] == [
        {"id": "provider-2:delete_docs", "name": "delete_docs", "reason": "forbidden"}
    ]
    assert result["fallback"] is False


def test_dynamic_mcp_runtime_should_return_fallback_when_runtime_build_fails():
    class _BrokenCollector:
        def collect(self, account_id):
            raise RuntimeError("collector failed")

    result = DynamicMcpRuntimeService(
        collector=_BrokenCollector(),
        policy_filter=_PolicyFilter(),
    ).build_runtime(
        account_id="account-1",
        agent_id="agent-1",
        request_id="request-1",
        required_capabilities=["search"],
        prebound_tools=[],
        max_tool_count=5,
    )

    assert result == {
        "mounted_tools": [],
        "hidden_tools": [],
        "filtered_out_tools": [],
        "audit_context": {
            "account_id": "account-1",
            "agent_id": "agent-1",
            "request_id": "request-1",
            "mounted_tool_count": 0,
            "mounted_runtime_names": [],
        },
        "fallback": True,
        "fallback_reason": "collector failed",
    }
