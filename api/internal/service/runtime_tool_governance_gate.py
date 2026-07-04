"""治理注入门：BaseTool 列表 → 治理过滤 → 返回过滤后列表 + 审计上下文。

注入到 AppRuntimeService.build_runtime_tools_for_config 的 return 前，把裸 BaseTool 列表
经 ToolPolicyFilter 治理过滤。详见架构文档 10.5.2 节。

渐进式启用：observe_only=True 时只记录审计不实际阻断（阶段1）。
"""

from dataclasses import dataclass
from typing import Any
from uuid import UUID

from injector import inject
from pkg.sqlalchemy import SQLAlchemy

from internal.entity.tool_inventory_entity import RiskLevel, normalize_tool_metadata
from internal.model import App
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

# 阶段2（block_sensitive_only）仅阻断的风险等级集合
_SENSITIVE_BLOCK_RISK_LEVELS = {RiskLevel.SENSITIVE.value, RiskLevel.DANGEROUS.value}


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
        block_sensitive_only: bool = False,
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
            observe_only: True 时只记录审计不实际过滤（阶段1渐进式启用）；
                observe_only=True 时 block_sensitive_only 不生效
            block_sensitive_only: True 时（阶段2）仅对 risk_level ∈ {sensitive, dangerous}
                的工具应用过滤结果，safe/low/medium/high 放行；observe_only=False 且
                block_sensitive_only=False 时（阶段3）全量按过滤结果阻断
        """
        if not tools:
            empty = self._empty_audit_context()
            empty["observe_only"] = observe_only
            empty["block_sensitive_only"] = block_sensitive_only
            return [], empty

        hints = tool_id_hints or {}
        candidates: list[dict[str, Any]] = []
        # 保留 (BaseTool, tool_id, composite_resolved, skip_reason, composite_blocking)
        # 以便后续筛选与审计
        tool_index: list[tuple[Any, str, list | None, str | None, dict | None]] = []

        for tool in tools:
            runtime_name = self._extract_runtime_name(tool)
            tool_id, source_type = self._resolve_tool_id_and_source_type(
                tool, runtime_name, hints
            )

            # 查询组合工具层级策略（双层叠加用）；原子工具复用同一次查询
            composite_policy = self._query_policy(tool_id)
            metadata = self._metadata_from_policy(composite_policy, source_type)

            # 组合工具：解析成员，双层叠加计算有效风险 + 部分阻断评估
            composite_resolved: list | None = None
            skip_reason: str | None = None
            composite_blocking: dict | None = None
            if source_type in _COMPOSITE_SOURCE_TYPES:
                composite_resolved, effective_risk, effective_confirmation, skip_reason, member_metadata_list = (
                    self._resolve_composite_risk(tool_id, composite_policy)
                )
                # skip_reason 非 None（公开 App 黑盒）时不覆盖 metadata，沿用 app_id 层级策略
                if skip_reason is None and effective_risk is not None:
                    metadata = dict(metadata)
                    metadata["risk_level"] = effective_risk
                    metadata["requires_confirmation"] = effective_confirmation
                # 部分阻断策略：评估成员 dangerous/disabled/unhealthy/sensitive
                if skip_reason is None and composite_resolved:
                    composite_blocking = self._evaluate_composite_blocking(
                        member_metadata_list
                    )
                    # sensitive 成员 → 强制需用户确认（即使成员策略未标记 require_confirmation）
                    if composite_blocking["requires_confirmation"]:
                        metadata = dict(metadata)
                        metadata["requires_confirmation"] = True

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
            tool_index.append((tool, tool_id, composite_resolved, skip_reason, composite_blocking))

        # 调用 ToolPolicyFilter 过滤
        filter_result = ToolPolicyFilter().filter(
            candidates,
            account_id=account_id,
            agent_pool=agent_pool,
            budget_level=budget_level,
            allow_confirmation=allow_confirmation,
        )
        accepted_ids = {c["id"] for c in filter_result["candidates"]}
        filtered_out_items = list(filter_result["filtered_out_tools"])

        # tool_id → effective risk_level（用于 block_sensitive_only 阶段2 判定）
        risk_by_tool_id: dict[str, str] = {
            c["id"]: str(c.get("metadata", {}).get("risk_level", RiskLevel.MEDIUM.value))
            for c in candidates
        }

        # 组合工具部分阻断后处理（observe_only=False 时生效）
        # dangerous/disabled/unhealthy 成员 → 整体阻断，即使 ToolPolicyFilter 已放行；
        # block_sensitive_only=True 时部分阻断策略仍然生效
        composite_blocked_ids: set[str] = set()
        if not observe_only:
            for tool, tid, _cr, skip_reason, composite_blocking in tool_index:
                if skip_reason is not None or composite_blocking is None:
                    continue
                if not composite_blocking["should_block"]:
                    continue
                # ToolPolicyFilter 已放行但部分阻断策略要求阻断 → 移出 accepted
                if tid in accepted_ids:
                    accepted_ids.discard(tid)
                    composite_blocked_ids.add(tid)
                    filtered_out_items.append({
                        "id": tid,
                        "name": self._extract_runtime_name(tool),
                        "reason": composite_blocking["block_reason"],
                    })

        # 根据过滤结果筛选 BaseTool 列表
        if observe_only:
            # 阶段1：只观测不阻断，保留全部工具（block_sensitive_only 不生效，
            # 部分阻断策略也不阻断，仅记录审计）
            filtered_tools = [tool for tool, _tid, _cr, _sr, _cb in tool_index]
        elif block_sensitive_only:
            # 阶段2：仅对 risk_level ∈ {sensitive, dangerous} 的工具应用过滤结果，
            # safe/low/medium/high 风险工具一律放行（即便被 ToolPolicyFilter 过滤）；
            # 但组合工具部分阻断（dangerous/disabled/unhealthy 成员）仍生效
            filtered_tools = [
                tool
                for tool, tid, _cr, _sr, _cb in tool_index
                if tid not in composite_blocked_ids
                and (
                    tid in accepted_ids
                    or risk_by_tool_id.get(tid) not in _SENSITIVE_BLOCK_RISK_LEVELS
                )
            ]
        else:
            # 阶段3：全量按过滤结果阻断
            filtered_tools = [
                tool for tool, tid, _cr, _sr, _cb in tool_index if tid in accepted_ids
            ]

        # 生成审计上下文
        audit_accepted = [
            {"tool_id": tid, "name": self._extract_runtime_name(tool)}
            for tool, tid, _cr, _sr, _cb in tool_index
            if tid in accepted_ids
        ]
        audit_filtered_out = [
            {"tool_id": item["id"], "name": item.get("name", ""), "reason": item["reason"]}
            for item in filtered_out_items
        ]
        composite_audit: dict[str, dict[str, Any]] = {}
        for _tool, tid, composite_resolved, skip_reason, composite_blocking in tool_index:
            if skip_reason is not None:
                # 公开 App A2A 黑盒：未展开成员，用 app_id 层级策略
                composite_audit[tid] = {
                    "composite_resolved": False,
                    "reason": skip_reason,
                    "member_count": 0,
                    "member_tool_ids": [],
                    "partial_blocking": None,
                }
            elif composite_resolved is not None:
                composite_audit[tid] = {
                    "composite_resolved": True,
                    "member_count": len(composite_resolved),
                    "member_tool_ids": [ref.tool_id for ref in composite_resolved],
                    "partial_blocking": composite_blocking,
                }

        audit_context = {
            "accepted": audit_accepted,
            "filtered_out": audit_filtered_out,
            "composite_resolved": composite_audit,
            "observe_only": observe_only,
            "block_sensitive_only": block_sensitive_only,
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
            "block_sensitive_only": False,
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
        return self._metadata_from_policy(policy, source_type)

    def _metadata_from_policy(
        self, policy: ToolGovernancePolicy | None, source_type: str
    ) -> dict:
        """从 ToolGovernancePolicy 构建归一化治理元数据。

        policy=None 时按 normalize_tool_metadata 默认值降级。
        health_status 不在 ToolGovernancePolicy 表结构中，通过 getattr 透传，
        便于测试桩与未来扩展；真实策略默认为 "healthy"。
        """
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
            "health_status": getattr(policy, "health_status", "healthy"),
        })

    def _query_policy(self, tool_id: str) -> ToolGovernancePolicy | None:
        return (
            self.db.session.query(ToolGovernancePolicy)
            .filter(ToolGovernancePolicy.tool_id == tool_id)
            .one_or_none()
        )

    def _resolve_composite_risk(
        self,
        tool_id: str,
        composite_policy: ToolGovernancePolicy | None = None,
    ) -> tuple[list, str | None, bool | None, str | None, list[dict]]:
        """组合工具：解析成员，双层叠加计算有效风险等级 + 确认要求。

        治理策略双层叠加（架构文档 10.2.3）：
            - 组合工具层级策略（composite_policy）与成员层级策略（max 成员风险）
              同时存在时取更严格（max 风险等级）
            - require_confirmation = 组合工具层级 OR 成员层级 any
            - 仅一层存在时用该层；均不存在时返回 None 由调用方沿用默认

        agent_binding 公开 App（is_public=True）走 A2A 黑盒，不展开成员，
        返回 skip_reason="public_app_a2a_blackbox"。

        Returns:
            (members, effective_risk, effective_requires_confirmation,
             skip_reason, member_metadata_list)
            - skip_reason 非 None 时 members 为空、effective_* 为 None
            - member_metadata_list 为每个成员的归一化治理元数据，供部分阻断评估复用
        """
        # 公开 App 走 A2A 黑盒：不展开成员，用 app_id 层级策略
        if self._is_agent_binding_public_app(tool_id):
            return [], None, None, "public_app_a2a_blackbox", []

        try:
            members = self.composite_tool_resolver.resolve(tool_id)
        except Exception:
            members = []
        if not members:
            return [], None, None, None, []

        member_metadata_list: list[dict] = []
        member_risks: list[str] = []
        member_confirmations: list[bool] = []
        for ref in members:
            member_metadata = self._load_governance_metadata(ref.tool_id, ref.source_type)
            member_metadata_list.append(member_metadata)
            member_risks.append(
                str(member_metadata.get("risk_level", RiskLevel.MEDIUM.value))
            )
            member_confirmations.append(
                bool(member_metadata.get("requires_confirmation", False))
            )

        # 成员层级有效风险 = max(成员风险)
        member_max_risk = max(
            member_risks,
            key=lambda r: _RISK_ORDER.get(r, _RISK_ORDER[RiskLevel.MEDIUM.value]),
        )
        member_any_confirmation = any(member_confirmations)

        # 双层叠加：组合工具层级 + 成员层级取更严格
        composite_risk = (
            composite_policy.risk_level if composite_policy is not None else None
        )
        composite_confirmation = (
            bool(composite_policy.require_confirmation)
            if composite_policy is not None
            else False
        )
        if composite_risk is not None:
            effective_risk = max(
                [composite_risk, member_max_risk],
                key=lambda r: _RISK_ORDER.get(r, _RISK_ORDER[RiskLevel.MEDIUM.value]),
            )
        else:
            effective_risk = member_max_risk
        effective_confirmation = composite_confirmation or member_any_confirmation

        return members, effective_risk, effective_confirmation, None, member_metadata_list

    def _evaluate_composite_blocking(self, member_metadata_list: list[dict]) -> dict:
        """评估组合工具的部分阻断策略（架构文档 10.2.3）。

        基于成员元数据判断是否整体阻断或需用户确认，按优先级：
            1. 成员含 dangerous → 整体阻断（block_reason="member_dangerous"）
            2. 成员含 disabled → 整体阻断（block_reason="member_disabled"）
            3. 成员含 unhealthy → 整体阻断（block_reason="member_unhealthy"，保守策略）
            4. 成员含 sensitive → 需用户确认（confirmation_reason="member_sensitive"）
            5. 其余 → 正常放行

        Returns:
            {
                "should_block": bool,
                "block_reason": str,
                "requires_confirmation": bool,
                "confirmation_reason": str,
                "member_risks": list[str],
            }
        """
        member_risks: list[str] = []
        has_dangerous = False
        has_sensitive = False
        has_disabled = False
        has_unhealthy = False

        for metadata in member_metadata_list:
            risk = str(metadata.get("risk_level", RiskLevel.MEDIUM.value))
            member_risks.append(risk)
            if risk == RiskLevel.DANGEROUS.value:
                has_dangerous = True
            if risk == RiskLevel.SENSITIVE.value:
                has_sensitive = True
            if metadata.get("enabled") is False:
                has_disabled = True
            if metadata.get("health_status") == "unhealthy":
                has_unhealthy = True

        if has_dangerous:
            return {
                "should_block": True,
                "block_reason": "member_dangerous",
                "requires_confirmation": False,
                "confirmation_reason": "",
                "member_risks": member_risks,
            }
        if has_disabled:
            return {
                "should_block": True,
                "block_reason": "member_disabled",
                "requires_confirmation": False,
                "confirmation_reason": "",
                "member_risks": member_risks,
            }
        if has_unhealthy:
            return {
                "should_block": True,
                "block_reason": "member_unhealthy",
                "requires_confirmation": False,
                "confirmation_reason": "",
                "member_risks": member_risks,
            }
        if has_sensitive:
            return {
                "should_block": False,
                "block_reason": "",
                "requires_confirmation": True,
                "confirmation_reason": "member_sensitive",
                "member_risks": member_risks,
            }
        return {
            "should_block": False,
            "block_reason": "",
            "requires_confirmation": False,
            "confirmation_reason": "",
            "member_risks": member_risks,
        }

    def _is_agent_binding_public_app(self, tool_id: str) -> bool:
        """检查 agent_binding 目标 App 是否为公开 App（is_public=True，走 A2A 黑盒）。

        非 agent_binding 工具、entity_id 缺失、App 不存在或查询异常时返回 False，
        由调用方走常规组合工具解析路径。
        """
        source_type, entity_id = parse_tool_id(tool_id)
        if source_type != "agent_binding" or not entity_id:
            return False
        try:
            app_uuid = UUID(entity_id)
        except (ValueError, AttributeError, TypeError):
            return False
        try:
            app = (
                self.db.session.query(App)
                .filter(App.id == app_uuid)
                .one_or_none()
            )
        except Exception:
            return False
        return bool(app is not None and getattr(app, "is_public", False))
