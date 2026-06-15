from internal.entity.runtime_tool_entity import RuntimeToolDescriptor
from internal.service.runtime_tool_mount_service import RuntimeToolMountService


def _descriptor(tool_id: str, runtime_name: str, source_type: str = "mcp"):
    return RuntimeToolDescriptor(
        tool_id=tool_id,
        runtime_name=runtime_name,
        name=runtime_name,
        description="",
        source_type=source_type,
        provider_id="provider-1",
        provider_name="Provider",
        input_schema=[],
        metadata={
            "tool_pool": source_type,
            "risk_level": "safe",
            "permission_scope": "public",
            "cost_level": "low",
            "health_status": "healthy",
        },
        audit_context={"tool_id": tool_id, "runtime_name": runtime_name},
    )


def test_mount_service_should_merge_dynamic_and_prebound_tools_with_dynamic_priority():
    dynamic = _descriptor("dynamic-1", "search_docs")
    prebound_duplicate = _descriptor("prebound-1", "search_docs")
    prebound_only = _descriptor("prebound-2", "read_file", "builtin")

    result = RuntimeToolMountService().mount_tools(
        selected_tools=[dynamic],
        prebound_tools=[prebound_duplicate, prebound_only],
        account_id="account-1",
        agent_id="agent-1",
        request_id="request-1",
        max_tool_count=5,
    )

    assert [tool.runtime_name for tool in result["mounted_tools"]] == [
        "search_docs",
        "read_file",
    ]
    assert result["mounted_tools"][0].tool_id == "dynamic-1"
    assert result["audit_context"] == {
        "account_id": "account-1",
        "agent_id": "agent-1",
        "request_id": "request-1",
        "mounted_tool_count": 2,
        "mounted_runtime_names": ["search_docs", "read_file"],
    }


def test_mount_service_should_limit_tool_count_and_record_hidden_tools():
    tools = [
        _descriptor("tool-1", "tool_one"),
        _descriptor("tool-2", "tool_two"),
        _descriptor("tool-3", "tool_three"),
    ]

    result = RuntimeToolMountService().mount_tools(
        selected_tools=tools,
        prebound_tools=[],
        account_id="account-1",
        agent_id="agent-1",
        request_id="request-1",
        max_tool_count=2,
    )

    assert [tool.runtime_name for tool in result["mounted_tools"]] == [
        "tool_one",
        "tool_two",
    ]
    assert result["hidden_tools"] == [
        {"tool_id": "tool-3", "runtime_name": "tool_three", "reason": "max_tool_count_exceeded"}
    ]


def test_mount_service_should_check_runtime_visibility():
    mounted = RuntimeToolMountService().mount_tools(
        selected_tools=[_descriptor("tool-1", "search_docs")],
        prebound_tools=[],
        account_id="account-1",
        agent_id="agent-1",
        request_id="request-1",
        max_tool_count=5,
    )

    service = RuntimeToolMountService()

    assert service.get_mounted_tool(mounted["mounted_tools"], "search_docs").tool_id == "tool-1"
    assert service.get_mounted_tool(mounted["mounted_tools"], "delete_database") is None
