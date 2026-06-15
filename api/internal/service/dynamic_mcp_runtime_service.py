from dataclasses import dataclass
from typing import Any

from internal.entity.runtime_tool_entity import RuntimeToolDescriptor
from internal.service.mcp_runtime_adapter import McpRuntimeAdapter
from internal.service.runtime_tool_mount_service import RuntimeToolMountService
from internal.service.tool_inventory_service import ToolRanker


@dataclass
class DynamicMcpRuntimeService:
    collector: Any
    policy_filter: Any

    def build_runtime(
        self,
        *,
        account_id: str,
        agent_id: str,
        request_id: str,
        required_capabilities: list[str],
        prebound_tools: list[RuntimeToolDescriptor],
        max_tool_count: int,
    ) -> dict:
        try:
            candidates = self.collector.collect(account_id)
            policy_result = self.policy_filter.filter(
                candidates,
                account_id=account_id,
                allow_confirmation=False,
            )
            ranked_candidates = ToolRanker().rank(
                policy_result["candidates"],
                required_capabilities=required_capabilities,
            )
            runtime_tools = self._to_runtime_tools(ranked_candidates)
            mount_result = RuntimeToolMountService().mount_tools(
                selected_tools=runtime_tools,
                prebound_tools=prebound_tools,
                account_id=account_id,
                agent_id=agent_id,
                request_id=request_id,
                max_tool_count=max_tool_count,
            )
            return {
                **mount_result,
                "filtered_out_tools": policy_result["filtered_out_tools"],
                "fallback": False,
            }
        except Exception as exc:
            return self._fallback(account_id, agent_id, request_id, str(exc))

    @staticmethod
    def _to_runtime_tools(
        candidates: list[dict[str, Any]],
    ) -> list[RuntimeToolDescriptor]:
        adapter = McpRuntimeAdapter()
        descriptors = []
        for candidate in candidates:
            descriptor = adapter.to_runtime_tool(candidate)
            if descriptor is not None:
                descriptors.append(descriptor)
        return descriptors

    @staticmethod
    def _fallback(
        account_id: str, agent_id: str, request_id: str, fallback_reason: str
    ) -> dict:
        return {
            "mounted_tools": [],
            "hidden_tools": [],
            "filtered_out_tools": [],
            "audit_context": {
                "account_id": account_id,
                "agent_id": agent_id,
                "request_id": request_id,
                "mounted_tool_count": 0,
                "mounted_runtime_names": [],
            },
            "fallback": True,
            "fallback_reason": fallback_reason,
        }
