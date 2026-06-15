from internal.entity.runtime_tool_entity import (
    RuntimeToolCallRequest,
    RuntimeToolCallResult,
    RuntimeToolDescriptor,
)


def test_runtime_tool_descriptor_should_normalize_defaults_and_audit_context():
    descriptor = RuntimeToolDescriptor.from_candidate(
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
                "risk_level": "safe",
                "permission_scope": "public",
                "cost_level": "low",
                "health_status": "healthy",
            },
        },
        runtime_name="mcp__provider_1__search_docs",
        mount_reason="matches document search task",
    )

    assert descriptor.tool_id == "provider-1:search_docs"
    assert descriptor.runtime_name == "mcp__provider_1__search_docs"
    assert descriptor.source_type == "mcp"
    assert descriptor.input_schema == [{"name": "query", "type": "str", "required": True}]
    assert descriptor.audit_context == {
        "tool_id": "provider-1:search_docs",
        "runtime_name": "mcp__provider_1__search_docs",
        "source_type": "mcp",
        "provider_id": "provider-1",
        "provider_name": "Docs MCP",
        "tool_pool": "mcp",
        "risk_level": "safe",
        "permission_scope": "public",
        "mount_reason": "matches document search task",
    }


def test_runtime_tool_call_request_should_sanitize_arguments_and_identity():
    request = RuntimeToolCallRequest(
        runtime_name=" search_docs ",
        arguments={"query": "phase 4", "limit": 3},
        account_id=" account-1 ",
        agent_id=" agent-1 ",
        request_id=" request-1 ",
    )

    assert request.runtime_name == "search_docs"
    assert request.arguments == {"query": "phase 4", "limit": 3}
    assert request.account_id == "account-1"
    assert request.agent_id == "agent-1"
    assert request.request_id == "request-1"


def test_runtime_tool_call_result_should_build_success_and_failure_payloads():
    success = RuntimeToolCallResult.success_result(
        output={"items": ["doc-1"]},
        latency_ms=35,
        audit_payload={"runtime_name": "search_docs"},
    )
    failure = RuntimeToolCallResult.failure_result(
        error_code="tool_not_mounted",
        error_message="工具未挂载",
        latency_ms=5,
        audit_payload={"runtime_name": "missing_tool"},
    )

    assert success.to_dict() == {
        "success": True,
        "output": {"items": ["doc-1"]},
        "error_code": "",
        "error_message": "",
        "latency_ms": 35,
        "audit_payload": {"runtime_name": "search_docs"},
    }
    assert failure.to_dict() == {
        "success": False,
        "output": None,
        "error_code": "tool_not_mounted",
        "error_message": "工具未挂载",
        "latency_ms": 5,
        "audit_payload": {"runtime_name": "missing_tool"},
    }
