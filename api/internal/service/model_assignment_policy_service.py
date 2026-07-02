from internal.entity.orchestrator_entity import (
    ExecutionMode,
    RequestContext,
    RiskLevel,
    RoutingDecision,
)

_TIER_RANK = {"cheap": 0, "standard": 1, "strong": 2}
_RANK_TIER = {0: "cheap", 1: "standard", 2: "strong"}


class ModelAssignmentPolicy:
    def assign(self, decision: RoutingDecision, context: RequestContext | None = None) -> str:
        requested_tier = self._normalize_tier(decision.recommended_model_tier)
        tier = self._by_execution_mode(decision.execution_mode, requested_tier)
        tier = self._by_complexity(decision.complexity, tier)
        tier = self._by_risk(decision.risk_level, tier)
        tier = self._by_context(context, decision, tier)
        return _RANK_TIER[_TIER_RANK[tier]]

    @staticmethod
    def _by_execution_mode(execution_mode: str, fallback: str) -> str:
        if execution_mode == ExecutionMode.DEEP_THINKING.value:
            return "strong"
        if execution_mode in (
            ExecutionMode.MULTI_AGENT.value,
            ExecutionMode.MULTI_AGENT_PARALLEL.value,
            ExecutionMode.MULTI_AGENT_SEQUENTIAL.value,
        ):
            return "strong"
        if execution_mode == ExecutionMode.REJECT_OR_CONFIRM.value:
            return "strong"
        if execution_mode == ExecutionMode.SINGLE_AGENT_WITH_TOOLS.value:
            return ModelAssignmentPolicy._upgrade(fallback, "standard")
        return fallback

    @staticmethod
    def _by_complexity(complexity: str, fallback: str) -> str:
        if complexity == "complex":
            return "strong"
        if complexity == "medium":
            return ModelAssignmentPolicy._upgrade(fallback, "standard")
        return fallback

    @staticmethod
    def _by_risk(risk_level: str, fallback: str) -> str:
        if risk_level == RiskLevel.HIGH.value:
            return "strong"
        if risk_level == RiskLevel.UNKNOWN.value:
            return ModelAssignmentPolicy._upgrade(fallback, "standard")
        return fallback

    @staticmethod
    def _by_context(context, decision, fallback: str) -> str:
        if context is None:
            return fallback
        if getattr(context, "enable_deep_thinking", False):
            return "strong"
        return fallback

    @staticmethod
    def _upgrade(current: str, floor: str) -> str:
        return current if _TIER_RANK.get(current, 0) >= _TIER_RANK.get(floor, 0) else floor

    @staticmethod
    def _normalize_tier(tier: str) -> str:
        text = (tier or "").strip()
        return text if text in _TIER_RANK else "cheap"
