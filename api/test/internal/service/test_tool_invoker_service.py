from internal.entity.runtime_tool_entity import RuntimeToolCallRequest, RuntimeToolDescriptor
from internal.service.tool_invoker_service import ToolInvokerService


def _descriptor(runtime_name="search_docs", risk_level="safe", permission_scope="public"):
    return RuntimeToolDescriptor(
        tool_id="provider-1:search_docs",
        runtime_name=runtime_name,
        name="search_docs",
        description="Search docs",
        source_type="mcp",
        provider_id="provider-1",
        provider_name="Docs MCP",
        input_schema=[{"name": "query", "type": "str", "required": True}],
        metadata={
            "tool_pool": "mcp",
            "risk_level": risk_level,
            "permission_scope": permission_scope,
            "cost_level": "low",
            "health_status": "healthy",
        },
        audit_context={
            "tool_id": "provider-1:search_docs",
            "runtime_name": runtime_name,
            "source_type": "mcp",
        },
    )


def _request(runtime_name="search_docs", arguments=None):
    return RuntimeToolCallRequest(
        runtime_name=runtime_name,
        arguments={"query": "phase 4"} if arguments is None else arguments,
        account_id="account-1",
        agent_id="agent-1",
        request_id="request-1",
    )


def test_tool_invoker_should_reject_unmounted_tool():
    result = ToolInvokerService().invoke(
        mounted_tools=[],
        request=_request(runtime_name="delete_database"),
        executors={},
    )

    assert result.success is False
    assert result.error_code == "tool_not_mounted"


def test_tool_invoker_should_reject_missing_required_argument():
    result = ToolInvokerService().invoke(
        mounted_tools=[_descriptor()],
        request=_request(arguments={}),
        executors={"search_docs": lambda arguments, tool: {"items": []}},
    )

    assert result.success is False
    assert result.error_code == "invalid_arguments"
    assert "query" in result.error_message


def test_tool_invoker_should_require_confirmation_for_high_risk_tool():
    result = ToolInvokerService().invoke(
        mounted_tools=[_descriptor(risk_level="high")],
        request=_request(),
        executors={"search_docs": lambda arguments, tool: {"items": []}},
        confirmed=False,
    )

    assert result.success is False
    assert result.error_code == "confirmation_required"


def test_tool_invoker_should_reject_sensitive_tool_without_confirmation():
    result = ToolInvokerService().invoke(
        mounted_tools=[_descriptor(risk_level="sensitive")],
        request=_request(),
        executors={"search_docs": lambda arguments, tool: {"items": []}},
        confirmed=False,
    )

    assert result.success is False
    assert result.error_code == "confirmation_required"


def test_tool_invoker_should_reject_dangerous_tool_even_with_confirmation():
    result = ToolInvokerService().invoke(
        mounted_tools=[_descriptor(risk_level="dangerous")],
        request=_request(),
        executors={"search_docs": lambda arguments, tool: {"items": []}},
        confirmed=True,
    )

    assert result.success is False
    assert result.error_code == "forbidden"


def test_tool_invoker_should_reject_private_tool_for_other_owner():
    tool = _descriptor(permission_scope="user")
    tool.metadata["user_scope"] = "owner"
    tool.metadata["owner"] = "other-account"

    result = ToolInvokerService().invoke(
        mounted_tools=[tool],
        request=_request(),
        executors={"search_docs": lambda arguments, tool: {"items": []}},
    )

    assert result.success is False
    assert result.error_code == "permission_scope_denied"


def test_tool_invoker_should_call_executor_for_mounted_safe_tool():
    calls = []

    def executor(arguments, tool):
        calls.append((arguments, tool.runtime_name))
        return {"items": ["doc-1"]}

    result = ToolInvokerService().invoke(
        mounted_tools=[_descriptor()],
        request=_request(),
        executors={"search_docs": executor},
    )

    assert result.success is True
    assert result.output == {"items": ["doc-1"]}
    assert calls == [({"query": "phase 4"}, "search_docs")]
    assert result.audit_payload["runtime_name"] == "search_docs"
    assert result.audit_payload["status"] == "success"
    assert result.audit_payload["input_summary"] == {
        "keys": ["query"],
        "redacted_keys": [],
    }


def test_tool_invoker_should_return_standard_failure_when_executor_raises():
    def executor(arguments, tool):
        raise RuntimeError("upstream timeout")

    result = ToolInvokerService().invoke(
        mounted_tools=[_descriptor()],
        request=_request(),
        executors={"search_docs": executor},
    )

    assert result.success is False
    assert result.error_code == "tool_execution_failed"
    assert result.error_message == "upstream timeout"
    assert result.audit_payload["status"] == "failure"
    assert result.audit_payload["failure_reason"] == "tool_execution_failed"
