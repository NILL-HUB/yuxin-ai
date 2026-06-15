from dataclasses import dataclass
from uuid import UUID

from injector import inject

from internal.entity.tool_inventory_entity import RiskLevel, ToolSourceType, normalize_tool_metadata
from internal.extension.database_extension import db
from internal.model import ApiTool, KnowledgeBase, McpProvider
from .builtin_tool_service import BuiltinToolService


class ToolCandidateCollector:
    def __init__(self, session=None, builtin_tool_service: BuiltinToolService | None = None):
        self.session = session or db.session
        self.builtin_tool_service = builtin_tool_service

    def collect(self, account_id: UUID) -> list[dict[str, object]]:
        candidates = []
        candidates.extend(self._collect_api_tools(account_id))
        candidates.extend(self._collect_mcp_tools(account_id))
        candidates.extend(self._collect_builtin_tools())
        candidates.extend(self._collect_knowledge_tools(account_id))
        return candidates

    def _collect_api_tools(self, account_id: UUID) -> list[dict[str, object]]:
        tools = self.session.query(ApiTool).filter(ApiTool.account_id == account_id).all()
        result = []
        for tool in tools:
            provider = tool.provider
            result.append({
                "id": str(tool.id),
                "name": tool.name,
                "description": tool.description,
                "source_type": ToolSourceType.API.value,
                "provider_id": str(provider.id),
                "provider_name": provider.name,
                "inputs": [{key: value for key, value in item.items() if key != "in"} for item in tool.parameters],
                "metadata": normalize_tool_metadata({"tool_pool": "api", "capabilities": [tool.name]}),
            })
        return result

    def _collect_mcp_tools(self, account_id: UUID) -> list[dict[str, object]]:
        providers = (
            self.session.query(McpProvider)
            .filter((McpProvider.account_id == account_id) | (McpProvider.is_public == True))
            .all()
        )
        result = []
        for provider in providers:
            for tool_name in provider.tool_names or []:
                result.append({
                    "id": f"{provider.id}:{tool_name}",
                    "name": tool_name,
                    "description": provider.description,
                    "source_type": ToolSourceType.MCP.value,
                    "provider_id": str(provider.id),
                    "provider_name": provider.label or provider.name,
                    "inputs": [],
                    "metadata": normalize_tool_metadata({
                        "tool_pool": provider.category or "mcp",
                        "capabilities": [tool_name],
                    }),
                })
        return result

    def _collect_builtin_tools(self) -> list[dict[str, object]]:
        if self.builtin_tool_service is None:
            return []
        result = []
        for provider in self.builtin_tool_service.get_builtin_tools():
            for tool in provider.get("tools", []):
                result.append({
                    "id": f"{provider.get('name', '')}:{tool.get('name', '')}",
                    "name": tool.get("name", ""),
                    "description": tool.get("description", ""),
                    "source_type": ToolSourceType.BUILTIN.value,
                    "provider_id": provider.get("name", ""),
                    "provider_name": provider.get("label") or provider.get("name", ""),
                    "inputs": tool.get("inputs", []),
                    "metadata": normalize_tool_metadata({
                        "tool_pool": provider.get("category") or "builtin",
                        "capabilities": [tool.get("name", "")],
                    }),
                })
        return result

    def _collect_knowledge_tools(self, account_id: UUID) -> list[dict[str, object]]:
        bases = (
            self.session.query(KnowledgeBase)
            .filter(
                KnowledgeBase.enabled.is_(True),
                (KnowledgeBase.owner_account_id == account_id) | (KnowledgeBase.knowledge_scope == "system"),
            )
            .all()
        )
        return [{
            "id": str(base.id),
            "name": base.name,
            "description": base.description,
            "source_type": ToolSourceType.KNOWLEDGE.value,
            "provider_id": str(base.id),
            "provider_name": "knowledge_base",
            "inputs": [{"name": "query", "type": "str", "required": True, "description": "检索问题"}],
            "metadata": normalize_tool_metadata({
                "tool_pool": "knowledge",
                "capabilities": [base.knowledge_scope],
                "risk_level": RiskLevel.SAFE.value,
            }),
        } for base in bases]


@inject
@dataclass
class ToolPolicyFilter:
    def filter(
        self,
        candidates: list[dict[str, object]],
        *,
        allow_confirmation: bool = False,
    ) -> dict[str, object]:
        accepted = []
        filtered_out = []
        for candidate in candidates:
            metadata = normalize_tool_metadata(candidate.get("metadata"))
            candidate["metadata"] = metadata
            if metadata["risk_level"] == RiskLevel.HIGH.value and metadata["requires_confirmation"] and not allow_confirmation:
                filtered_out.append({
                    "id": candidate["id"],
                    "name": candidate["name"],
                    "reason": "high_risk_requires_confirmation",
                })
                continue
            accepted.append(candidate)
        return {"candidates": accepted, "filtered_out_tools": filtered_out}


@inject
@dataclass
class ToolSubsetBuilder:
    collector: ToolCandidateCollector
    policy_filter: ToolPolicyFilter

    def build(
        self,
        account_id: UUID,
        *,
        tool_pool: str | None = None,
        agent_pool: str | None = None,
        allow_confirmation: bool = False,
    ) -> dict[str, object]:
        return self.build_subset(
            self.collector.collect(account_id),
            tool_pool=tool_pool,
            agent_pool=agent_pool,
            allow_confirmation=allow_confirmation,
        )

    def build_subset(
        self,
        candidates: list[dict[str, object]],
        *,
        tool_pool: str | None = None,
        agent_pool: str | None = None,
        allow_confirmation: bool = False,
    ) -> dict[str, object]:
        filtered = self.policy_filter.filter(candidates, allow_confirmation=allow_confirmation)
        result = []
        for candidate in filtered["candidates"]:
            metadata = candidate["metadata"]
            if tool_pool and metadata["tool_pool"] != tool_pool:
                continue
            allowed_agent_pools = metadata.get("allowed_agent_pools") or []
            if agent_pool and allowed_agent_pools and agent_pool not in allowed_agent_pools:
                continue
            result.append(candidate)
        return {
            "candidates": result,
            "filtered_out_tools": filtered["filtered_out_tools"],
        }
