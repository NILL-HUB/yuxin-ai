from internal.service.mcp_runtime_adapter import McpRuntimeAdapter


def test_mcp_runtime_adapter_should_convert_mcp_candidate_to_runtime_descriptor():
    candidate = {
        "id": "provider-1:search_docs",
        "name": "search_docs",
        "description": "Search docs",
        "source_type": "mcp",
        "provider_id": "provider-1",
        "provider_name": "Docs MCP",
        "inputs": [{"name": "query", "type": "str", "required": True}],
        "metadata": {
            "tool_pool": "mcp",
            "risk_level": "safe",
            "permission_scope": "public",
            "cost_level": "low",
            "health_status": "healthy",
        },
    }

    descriptor = McpRuntimeAdapter().to_runtime_tool(
        candidate,
        mount_reason="matches document search task",
    )

    assert descriptor.runtime_name == "mcp__provider_1__search_docs"
    assert descriptor.tool_id == "provider-1:search_docs"
    assert descriptor.source_type == "mcp"
    assert descriptor.audit_context["provider_id"] == "provider-1"
    assert descriptor.audit_context["risk_level"] == "safe"
    assert descriptor.audit_context["permission_scope"] == "public"


def test_mcp_runtime_adapter_should_skip_non_mcp_candidate():
    candidate = {
        "id": "builtin:read_file",
        "name": "read_file",
        "source_type": "builtin",
        "provider_id": "builtin",
        "provider_name": "Builtin",
        "metadata": {"tool_pool": "builtin"},
    }

    assert McpRuntimeAdapter().can_handle(candidate) is False
    assert McpRuntimeAdapter().to_runtime_tool(candidate) is None


def test_mcp_runtime_adapter_should_generate_stable_safe_runtime_names():
    candidate = {
        "id": "provider a:search-docs.v1",
        "name": "search-docs.v1",
        "source_type": "mcp",
        "provider_id": "provider a",
        "provider_name": "Provider A",
        "metadata": {"tool_pool": "mcp"},
    }

    descriptor = McpRuntimeAdapter().to_runtime_tool(candidate)

    assert descriptor.runtime_name == "mcp__provider_a__search_docs_v1"
