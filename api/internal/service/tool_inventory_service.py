from dataclasses import dataclass
from uuid import UUID

from injector import inject

from internal.entity.tool_inventory_entity import RiskLevel, ToolSourceType, normalize_tool_metadata
from internal.extension.database_extension import db
from internal.model import ApiTool, ExternalDataSource, KnowledgeBase, McpProvider
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
        candidates.extend(self._collect_external_data_tools(account_id))
        return candidates

    def _collect_api_tools(self, account_id: UUID) -> list[dict[str, object]]:
        tools = self.session.query(ApiTool).filter(ApiTool.account_id == account_id).all()
        result = []
        for tool in tools:
            provider = tool.provider
            metadata = normalize_tool_metadata({
                **(getattr(tool, "metadata", {}) or {}),
                "tool_pool": "api",
                "capabilities": [tool.name],
                "permission_scope": "user",
            })
            if not self._is_available(metadata):
                continue
            result.append({
                "id": str(tool.id),
                "name": tool.name,
                "description": tool.description,
                "source_type": ToolSourceType.API.value,
                "provider_id": str(provider.id),
                "provider_name": provider.name,
                "inputs": [
                    {key: value for key, value in item.items() if key != "in"}
                    for item in tool.parameters
                ],
                "metadata": metadata,
                "visibility": "private",
                "enabled": True,
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
                metadata = normalize_tool_metadata({
                    **(getattr(provider, "metadata", {}) or {}),
                    "tool_pool": "mcp",
                    "capabilities": [tool_name],
                    "permission_scope": "public" if provider.is_public else "user",
                })
                if not self._is_available(metadata):
                    continue
                result.append({
                    "id": f"{provider.id}:{tool_name}",
                    "name": tool_name,
                    "description": provider.description,
                    "source_type": ToolSourceType.MCP.value,
                    "provider_id": str(provider.id),
                    "provider_name": provider.label or provider.name,
                    "inputs": [],
                    "metadata": metadata,
                    "visibility": "public" if provider.is_public else "private",
                    "enabled": True,
                })
        return result

    def _collect_builtin_tools(self) -> list[dict[str, object]]:
        if self.builtin_tool_service is None:
            return []
        result = []
        for provider in self.builtin_tool_service.get_builtin_tools():
            for tool in provider.get("tools", []):
                metadata = normalize_tool_metadata({
                    **(provider.get("metadata") or {}),
                    **(tool.get("metadata") or {}),
                    "tool_pool": "builtin",
                    "capabilities": [tool.get("name", "")],
                    "permission_scope": "system",
                    "owner": "system",
                })
                if not self._is_available(metadata):
                    continue
                result.append({
                    "id": f"{provider.get('name', '')}:{tool.get('name', '')}",
                    "name": tool.get("name", ""),
                    "description": tool.get("description", ""),
                    "source_type": ToolSourceType.BUILTIN.value,
                    "provider_id": provider.get("name", ""),
                    "provider_name": provider.get("label") or provider.get("name", ""),
                    "inputs": tool.get("inputs", []),
                    "metadata": metadata,
                    "visibility": "system",
                    "enabled": True,
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
        result = []
        for base in bases:
            metadata = normalize_tool_metadata({
                **(getattr(base, "metadata", {}) or {}),
                "tool_pool": "knowledge",
                "capabilities": [base.knowledge_scope],
                "risk_level": RiskLevel.SAFE.value,
                "permission_scope": "system" if base.knowledge_scope == "system" else "user",
                "knowledge_scope": base.knowledge_scope,
                "enabled": getattr(base, "enabled", True),
            })
            if not self._is_available(metadata):
                continue
            result.append({
                "id": str(base.id),
                "name": base.name,
                "description": base.description,
                "source_type": ToolSourceType.KNOWLEDGE.value,
                "provider_id": str(base.id),
                "provider_name": "knowledge_base",
                "inputs": [
                    {
                        "name": "query",
                        "type": "str",
                        "required": True,
                        "description": "检索问题",
                    }
                ],
                "metadata": metadata,
                "visibility": "system" if base.knowledge_scope == "system" else "private",
                "enabled": True,
            })
        return result

    def _collect_external_data_tools(self, account_id: UUID) -> list[dict[str, object]]:
        data_sources = (
            self.session.query(ExternalDataSource)
            .filter(
                ExternalDataSource.owner_account_id == account_id,
                ExternalDataSource.authorization_status == "granted",
            )
            .all()
        )
        result = []
        for ds in data_sources:
            if ds.knowledge_base_id is None:
                continue
            metadata = normalize_tool_metadata({
                "tool_pool": "external_data",
                "capabilities": [ds.source_type],
                "risk_level": RiskLevel.LOW.value,
                "permission_scope": "user",
                "knowledge_scope": "user_content",
                "cost_level": "low",
                "enabled": True,
            })
            if not self._is_available(metadata):
                continue
            result.append({
                "id": f"external_data:{ds.id}",
                "name": "external_data_retrieval",
                "description": "检索用户连接的外部数据源内容",
                "source_type": ToolSourceType.KNOWLEDGE.value,
                "provider_id": str(ds.id),
                "provider_name": ds.source_name or ds.source_type,
                "inputs": [
                    {
                        "name": "query",
                        "type": "str",
                        "required": True,
                        "description": "检索问题",
                    }
                ],
                "metadata": metadata,
                "visibility": "private",
                "enabled": True,
            })
        return result

    @staticmethod
    def _is_available(metadata: dict[str, object]) -> bool:
        return metadata.get("enabled") is True and metadata.get("health_status") != "unhealthy"


@inject
@dataclass
class ToolPolicyFilter:
    def filter(
        self,
        candidates: list[dict[str, object]],
        *,
        account_id: str | None = None,
        agent_pool: str | None = None,
        budget_level: str = "medium",
        allow_confirmation: bool = False,
    ) -> dict[str, object]:
        accepted = []
        filtered_out = []
        for candidate in candidates:
            metadata = normalize_tool_metadata(candidate.get("metadata"))
            candidate["metadata"] = metadata
            reason = self._reject_reason(
                metadata,
                account_id=account_id,
                agent_pool=agent_pool,
                budget_level=budget_level,
                allow_confirmation=allow_confirmation,
            )
            if reason:
                filtered_out.append({
                    "id": candidate["id"],
                    "name": candidate["name"],
                    "reason": reason,
                })
                continue
            accepted.append(candidate)
        return {"candidates": accepted, "filtered_out_tools": filtered_out}

    def _reject_reason(
        self,
        metadata: dict[str, object],
        *,
        account_id: str | None,
        agent_pool: str | None,
        budget_level: str,
        allow_confirmation: bool,
    ) -> str | None:
        if metadata.get("enabled") is False:
            return "tool_disabled"
        if metadata.get("health_status") == "unhealthy":
            return "tool_unhealthy"
        if metadata.get("tool_pool") == "knowledge" and not self._owner_allowed(
            metadata, account_id
        ):
            return "knowledge_scope_denied"
        if metadata.get("permission_scope") == "system":
            return "permission_scope_denied"
        if not self._owner_allowed(metadata, account_id):
            return "user_scope_denied"
        if (
            metadata["risk_level"] in {RiskLevel.HIGH.value, RiskLevel.SENSITIVE.value}
            and metadata["requires_confirmation"]
            and not allow_confirmation
        ):
            return "high_risk_requires_confirmation"
        if not self._cost_allowed(str(metadata.get("cost_level")), budget_level):
            return "cost_level_exceeds_budget"
        allowed_agent_pools = metadata.get("allowed_agent_pools") or []
        if agent_pool and allowed_agent_pools and agent_pool not in allowed_agent_pools:
            return "agent_pool_not_allowed"
        return None

    @staticmethod
    def _owner_allowed(metadata: dict[str, object], account_id: str | None) -> bool:
        if metadata.get("user_scope") != "owner":
            return True
        owner = metadata.get("owner")
        return owner in {"system", account_id}

    @staticmethod
    def _cost_allowed(cost_level: str, budget_level: str) -> bool:
        order = {"low": 1, "medium": 2, "high": 3}
        return order.get(cost_level, 2) <= order.get(budget_level, 2)


class ToolRanker:
    def rank(
        self,
        candidates: list[dict[str, object]],
        *,
        required_capabilities: list[str] | None = None,
    ) -> list[dict[str, object]]:
        ranked = []
        for candidate in candidates:
            item = dict(candidate)
            metadata = normalize_tool_metadata(item.get("metadata"))
            item["metadata"] = metadata
            breakdown = self._score_breakdown(
                metadata, required_capabilities=required_capabilities or []
            )
            item["score_breakdown"] = breakdown
            item["score"] = round(
                breakdown["capability_score"] * 0.35
                + breakdown["success_rate"] * 0.25
                + breakdown["health_score"] * 0.20
                + breakdown["cost_score"] * 0.10
                + breakdown["latency_score"] * 0.10,
                4,
            )
            ranked.append(item)
        return sorted(
            ranked,
            key=lambda item: (
                -item["score"],
                item.get("name", ""),
                item.get("id", ""),
            ),
        )

    def _score_breakdown(
        self, metadata: dict[str, object], *, required_capabilities: list[str]
    ) -> dict[str, float]:
        return {
            "capability_score": self._capability_score(
                metadata.get("capabilities", []), required_capabilities
            ),
            "success_rate": float(metadata.get("success_rate") or 0.0),
            "health_score": self._health_score(str(metadata.get("health_status"))),
            "cost_score": self._cost_score(str(metadata.get("cost_level"))),
            "latency_score": self._latency_score(int(metadata.get("avg_latency") or 0)),
        }

    @staticmethod
    def _capability_score(capabilities: list[str], required: list[str]) -> float:
        if not required:
            return 0.5
        if all(capability in capabilities for capability in required):
            return 1.0
        if any(capability in capabilities for capability in required):
            return 0.5
        return 0.0

    @staticmethod
    def _health_score(health_status: str) -> float:
        return {"healthy": 1.0, "degraded": 0.5, "unhealthy": 0.0}.get(
            health_status, 1.0
        )

    @staticmethod
    def _cost_score(cost_level: str) -> float:
        return {"low": 1.0, "medium": 0.6, "high": 0.2}.get(cost_level, 0.6)

    @staticmethod
    def _latency_score(avg_latency: int) -> float:
        if avg_latency <= 0:
            return 0.5
        if avg_latency <= 500:
            return 1.0
        if avg_latency <= 1500:
            return 0.6
        return 0.2


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

    def build_ranked_subset(
        self,
        candidates: list[dict[str, object]],
        *,
        filtered_out_tools: list[dict] | None = None,
        required_capabilities: list[str] | None = None,
        max_tool_count: int = 5,
    ) -> dict[str, object]:
        ranked = ToolRanker().rank(
            candidates, required_capabilities=required_capabilities or []
        )
        selected_tools = ranked[:max_tool_count]
        backup_tools = ranked[max_tool_count:]
        return {
            "selected_tools": selected_tools,
            "backup_tools": backup_tools,
            "filtered_out_tools": filtered_out_tools or [],
            "selection_reason": "ranked_by_capability_success_health_cost_latency",
        }

    def build_subset(
        self,
        candidates: list[dict[str, object]],
        *,
        tool_pool: str | None = None,
        agent_pool: str | None = None,
        allow_confirmation: bool = False,
    ) -> dict[str, object]:
        filtered = self.policy_filter.filter(
            candidates,
            allow_confirmation=allow_confirmation,
        )
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
