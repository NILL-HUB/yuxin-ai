from internal.entity.orchestrator_entity import (
    RoutingDecision,
)


class RoutingObservabilityPayloadService:
    def build(
        self,
        *,
        user_query: str,
        decision: RoutingDecision,
        latency_ms: int,
    ) -> dict:
        return {
            "user_query": user_query,
            "routing_decision": decision.to_dict(),
            "task_classification": self._task_classification(decision),
            "model_selection": self._model_selection(decision),
            "agent_pool_hits": self._agent_pool_hits(decision),
            "tool_pool_hits": self._tool_pool_hits(decision),
            "key_usage": {},
            "cost_summary": self._cost_summary(decision),
            "latency_ms": latency_ms,
            "fallback_reason": self._fallback_reason(decision),
        }

    @staticmethod
    def _task_classification(decision: RoutingDecision) -> dict:
        return {
            "intent": decision.intent,
            "complexity": decision.complexity,
            "execution_mode": decision.execution_mode,
        }

    @staticmethod
    def _model_selection(decision: RoutingDecision) -> dict:
        cost_policy = decision.cost_policy or {}
        return {
            "model_tier": cost_policy.get("model_tier", ""),
            "model_id": cost_policy.get("selected_model", ""),
        }

    @staticmethod
    def _agent_pool_hits(decision: RoutingDecision) -> list[dict]:
        subset = decision.agent_subset or {}
        return [{"pool": pool} for pool in subset.get("matched_pools", [])]

    @staticmethod
    def _tool_pool_hits(decision: RoutingDecision) -> list[dict]:
        subset = decision.tool_subset or {}
        pools = []
        for tool in subset.get("selected_tools", []):
            pool = tool.get("pool") if isinstance(tool, dict) else None
            if pool and pool not in pools:
                pools.append(pool)
        return [{"pool": pool} for pool in pools]

    @staticmethod
    def _cost_summary(decision: RoutingDecision) -> dict:
        events = decision.billing_events or []
        total_credits = 0
        for event in events:
            if isinstance(event, dict):
                total_credits = max(total_credits, event.get("total_credits", 0))
        return {"total_credits": total_credits}

    @staticmethod
    def _fallback_reason(decision: RoutingDecision) -> str:
        synthesis_summary = decision.synthesis_summary or {}
        warnings = synthesis_summary.get("user_warnings") or []
        for warning in warnings:
            if isinstance(warning, str) and warning.startswith("fallback:"):
                return warning
        return decision.reason if decision.reason.startswith("fallback:") else ""
