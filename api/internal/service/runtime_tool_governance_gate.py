"""治理注入门：BaseTool 列表 → 治理过滤 → 返回过滤后列表 + 审计上下文。

注入到 AppService._build_runtime_tools_for_config 的 return 前，把裸 BaseTool 列表
经 ToolPolicyFilter 治理过滤。详见架构文档 10.5.2 节。

渐进式启用：observe_only=True 时只记录审计不实际阻断（阶段1）。
"""

from dataclasses import dataclass
from typing import Any

from injector import inject
from pkg.sqlalchemy import SQLAlchemy

from internal.entity.tool_inventory_entity import RiskLevel, normalize_tool_metadata
from internal.model.tool_governance_entity import ToolGovernancePolicy
from .composite_tool_resolver import CompositeToolResolver
from .tool_inventory_service import ToolPolicyFilter, parse_tool_id


# 风险等级排序，用于组合工具取成员 max
_RISK_ORDER: dict[str, int] = {
    RiskLevel.SAFE.value: 0,
    RiskLevel.LOW.value: 1,
    RiskLevel.MEDIUM.value: 2,
    RiskLevel.HIGH.value: 3,
    RiskLevel.SENSITIVE.value: 4,
    RiskLevel.DANGEROUS.value: 5,
}

# 组合工具 source_type：需要调 CompositeToolResolver 解析成员
_COMPOSITE_SOURCE_TYPES = {"workflow", "agent_binding"}

# BaseTool.name 前缀 → source_type（无 hints/metadata 时的 best-effort 匹配）
_NAME_PREFIX_TO_SOURCE_TYPE: dict[str, str] = {
    "wf_": "workflow",
    "skill__": "skill",
    "agent_app_": "agent_binding",
}


@inject
@dataclass
class RuntimeToolGovernanceGate:
    """治理注入门：BaseTool 列表 → 治理过滤 → 返回过滤后列表 + 审计上下文。

    依赖：
        db: SQLAlchemy 数据库实例，用于查询 ToolGovernancePolicy
        composite_tool_resolver: 组合工具成员解析器（P0-2 产出）
    """

    db: SQLAlchemy
    composite_tool_resolver: CompositeToolResolver

    def apply(
        self,
        tools: list,
        *,
        account_id: str | None = None,
        app_id: str | None = None,
        agent_pool: str | None = None,
        budget_level: str = "medium",
        allow_confirmation: bool = False,
        tool_id_hints: dict[str, str] | None = None,
        observe_only: bool = False,
    ) -> tuple[list, dict]:
        """返回 (filtered_tools, audit_context)。

        Args:
            tools: BaseTool 列表（治理前）
            account_id: 调用方账号 id
            app_id: 当前 App id
            agent_pool: Agent 池标识
            budget_level: 预算等级 (low/medium/high)
            allow_confirmation: 是否允许触发用户确认（False 时高风险工具直接过滤）
            tool_id_hints: 可选 {runtime_name: tool_id} 映射，P0-4 注入时提供
            observe_only: True 时只记录审计不实际过滤（阶段1渐进式启用）
        """
        if not tools:
            return [], self._empty_audit_context()

        hints = tool_id_hints or {}
        candidates: list[dict[str, Any]] = []
        # 保留 (BaseTool, tool_id, composite_resolved) 以便后续筛选
        tool_index: list[tuple[Any, str, list | None]] = []

        for tool in tools:
            runtime_name = self._extract_runtime_name(tool)
            tool_id, source_type = self._resolve_tool_id_and_source_type(
                tool, runtime_name, hints
            )
            metadata = self._load_governance_metadata(tool_id, source_type)

            # 组合工具：解析成员并计算有效风险等级 + 确认要求
            composite_resolved: list | None = None
            if source_type in _COMPOSITE_SOURCE_TYPES:
                composite_resolved, effective_risk, effective_confirmation = (
                    self._resolve_composite_risk(tool_id)
                )
                if effective_risk is not None:
                    metadata = dict(metadata)
                    metadata["risk_level"] = effective_risk
                    metadata["requires_confirmation"] = effective_confirmation

            candidate = {
                "id": tool_id,
                "name": runtime_name or tool_id,
                "description": getattr(tool, "description", "") or "",
                "source_type": source_type,
                "provider_id": "",
                "provider_name": "",
                "inputs": [],
                "metadata": metadata,
                "visibility": "private",
                "enabled": metadata.get("enabled", True),
            }
            candidates.append(candidate)
            tool_index.append((tool, tool_id, composite_resolved))

        # 调用 ToolPolicyFilter 过滤
        filter_result = ToolPolicyFilter().filter(
            candidates,
            account_id=account_id,
            agent_pool=agent_pool,
            budget_level=budget_level,
            allow_confirmation=allow_confirmation,
        )
        accepted_ids = {c["id"] for c in filter_result["candidates"]}
        filtered_out_items = filter_result["filtered_out_tools"]

        # 根据过滤结果筛选 BaseTool 列表
        if observe_only:
            # 阶段1：只观测不阻断，保留全部工具
            filtered_tools = [tool for tool, _tid, _cr in tool_index]
        else:
            filtered_tools = [
                tool for tool, tid, _cr in tool_index if tid in accepted_ids
            ]

        # 生成审计上下文
        audit_accepted = [
            {"tool_id": tid, "name": self._extract_runtime_name(tool)}
            for tool, tid, _cr in tool_index
            if tid in accepted_ids
        ]
        audit_filtered_out = [
            {"tool_id": item["id"], "name": item.get("name", ""), "reason": item["reason"]}
            for item in filtered_out_items
        ]
        composite_audit: dict[str, dict[str, Any]] = {}
        for _tool, tid, composite_resolved in tool_index:
            if composite_resolved is not None:
                composite_audit[tid] = {
                    "member_count": len(composite_resolved),
                    "member_tool_ids": [ref.tool_id for ref in composite_resolved],
                }

        audit_context = {
            "accepted": audit_accepted,
            "filtered_out": audit_filtered_out,
            "composite_resolved": composite_audit,
            "observe_only": observe_only,
            "account_id": account_id,
            "app_id": app_id,
            "agent_pool": agent_pool,
            "budget_level": budget_level,
            "input_tool_count": len(tools),
            "output_tool_count": len(filtered_tools),
        }
        return filtered_tools, audit_context

    # ------------------------------------------------------------------ #
    #  私有方法                                                           #
    # ------------------------------------------------------------------ #

    @staticmethod
    def _empty_audit_context() -> dict:
        return {
            "accepted": [],
            "filtered_out": [],
            "composite_resolved": {},
            "observe_only": False,
            "input_tool_count": 0,
            "output_tool_count": 0,
        }

    @staticmethod
    def _extract_runtime_name(tool: Any) -> str:
        name = getattr(tool, "name", "") or ""
        if callable(name):
            try:
                name = name()
            except Exception:
                name = ""
        return str(name).strip()

    def _resolve_tool_id_and_source_type(
        self,
        tool: Any,
        runtime_name: str,
        hints: dict[str, str],
    ) -> tuple[str, str]:
        """解析 (tool_id, source_type)。优先级：hints > metadata > name 模式匹配。"""
        # 1. 优先从 tool_id_hints 映射读取（P0-4 注入时提供）
        if runtime_name and runtime_name in hints:
            tool_id = hints[runtime_name]
            source_type, _ = parse_tool_id(tool_id)
            return tool_id, source_type

        # 2. 从 BaseTool.metadata 读取（底座构建时若存了 tool_id）
        metadata = getattr(tool, "metadata", None)
        if isinstance(metadata, dict):
            tool_id = metadata.get("tool_id")
            if tool_id and isinstance(tool_id, str):
                source_type, _ = parse_tool_id(tool_id)
                return tool_id, source_type

        # 3. 从 BaseTool.name 模式匹配（best-effort，无法还原完整 tool_id）
        if runtime_name:
            for prefix, source_type in _NAME_PREFIX_TO_SOURCE_TYPE.items():
                if runtime_name.startswith(prefix):
                    # 无法从 name 唯一还原 UUID，返回占位标识（治理策略无法精确匹配）
                    return f"{source_type}:__unresolved__{runtime_name}", source_type
        return f"unknown:__unresolved__{runtime_name}", "unknown"

    def _load_governance_metadata(self, tool_id: str, source_type: str) -> dict:
        """按 tool_id 查询 ToolGovernancePolicy，组合 candidate metadata。

        不存在策略记录时按 normalize_tool_metadata 默认值降级。
        """
        policy = self._query_policy(tool_id)
        if policy is None:
            return normalize_tool_metadata({
                "tool_pool": source_type or "general",
                "enabled": True,
            })
        return normalize_tool_metadata({
            "tool_pool": source_type or "general",
            "risk_level": policy.risk_level,
            "enabled": policy.enabled,
            "requires_confirmation": policy.require_confirmation,
            "allowed_agent_pools": policy.allowed_pools or [],
        })

    def _query_policy(self, tool_id: str) -> ToolGovernancePolicy | None:
        return (
            self.db.session.query(ToolGovernancePolicy)
            .filter(ToolGovernancePolicy.tool_id == tool_id)
            .one_or_none()
        )

    def _resolve_composite_risk(
        self, tool_id: str
    ) -> tuple[list, str | None, bool | None]:
        """组合工具：解析成员，取成员风险等级 max 作为有效风险等级。

        agent_binding 公开 App 解析为空 → 返回 (None, None)，由调用方使用默认策略。

        Returns:
            (members, effective_risk, effective_requires_confirmation)
            - members 为空时 effective_risk/effective_confirmation 为 None
        """
        try:
            members = self.composite_tool_resolver.resolve(tool_id)
        except Exception:
            members = []
        if not members:
            return [], None, None

        member_risks: list[str] = []
        member_confirmations: list[bool] = []
        for ref in members:
            member_policy = self._query_policy(ref.tool_id)
            if member_policy is not None:
                member_risks.append(member_policy.risk_level)
                member_confirmations.append(bool(member_policy.require_confirmation))
        if not member_risks:
            return members, None, None

        effective_risk = max(
            member_risks,
            key=lambda r: _RISK_ORDER.get(r, _RISK_ORDER[RiskLevel.MEDIUM.value]),
        )
        effective_confirmation = any(member_confirmations)
        return members, effective_risk, effective_confirmation
