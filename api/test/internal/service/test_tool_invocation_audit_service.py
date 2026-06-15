from internal.service.tool_invocation_audit_service import ToolInvocationAuditService


def test_audit_service_should_build_success_audit_payload_with_input_summary():
    payload = ToolInvocationAuditService().build_payload(
        audit_context={
            "tool_id": "provider-1:search_docs",
            "runtime_name": "search_docs",
            "source_type": "mcp",
            "provider_id": "provider-1",
        },
        account_id="account-1",
        agent_id="agent-1",
        request_id="request-1",
        arguments={"query": "phase 4", "api_key": "secret-value"},
        latency_ms=42,
        status="success",
        failure_reason="",
    )

    assert payload == {
        "tool_id": "provider-1:search_docs",
        "runtime_name": "search_docs",
        "source_type": "mcp",
        "provider_id": "provider-1",
        "account_id": "account-1",
        "agent_id": "agent-1",
        "request_id": "request-1",
        "input_summary": {"keys": ["api_key", "query"], "redacted_keys": ["api_key"]},
        "latency_ms": 42,
        "status": "success",
        "failure_reason": "",
    }


def test_audit_service_should_build_failure_payload_with_stable_reason():
    payload = ToolInvocationAuditService().build_payload(
        audit_context={"runtime_name": "missing_tool"},
        account_id="account-1",
        agent_id="agent-1",
        request_id="request-1",
        arguments={"password": "secret"},
        latency_ms=-1,
        status="failure",
        failure_reason="tool_not_mounted",
    )

    assert payload["runtime_name"] == "missing_tool"
    assert payload["tool_id"] == ""
    assert payload["latency_ms"] == 0
    assert payload["status"] == "failure"
    assert payload["failure_reason"] == "tool_not_mounted"
    assert payload["input_summary"] == {"keys": ["password"], "redacted_keys": ["password"]}
