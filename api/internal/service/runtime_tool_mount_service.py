from dataclasses import dataclass

from internal.entity.runtime_tool_entity import RuntimeToolDescriptor


@dataclass
class RuntimeToolMountService:
    def mount_tools(
        self,
        *,
        selected_tools: list[RuntimeToolDescriptor],
        prebound_tools: list[RuntimeToolDescriptor],
        account_id: str,
        agent_id: str,
        request_id: str,
        max_tool_count: int,
    ) -> dict:
        merged_tools = []
        seen_runtime_names = set()
        for tool in [*selected_tools, *prebound_tools]:
            if tool.runtime_name in seen_runtime_names:
                continue
            seen_runtime_names.add(tool.runtime_name)
            merged_tools.append(tool)

        mounted_tools = merged_tools[:max_tool_count]
        hidden_tools = [
            {
                "tool_id": tool.tool_id,
                "runtime_name": tool.runtime_name,
                "reason": "max_tool_count_exceeded",
            }
            for tool in merged_tools[max_tool_count:]
        ]
        return {
            "mounted_tools": mounted_tools,
            "hidden_tools": hidden_tools,
            "audit_context": {
                "account_id": account_id,
                "agent_id": agent_id,
                "request_id": request_id,
                "mounted_tool_count": len(mounted_tools),
                "mounted_runtime_names": [tool.runtime_name for tool in mounted_tools],
            },
        }

    @staticmethod
    def get_mounted_tool(
        mounted_tools: list[RuntimeToolDescriptor], runtime_name: str
    ) -> RuntimeToolDescriptor | None:
        for tool in mounted_tools:
            if tool.runtime_name == runtime_name:
                return tool
        return None
