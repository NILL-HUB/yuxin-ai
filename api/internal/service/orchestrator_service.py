import logging

from injector import inject

from internal.entity.orchestrator_entity import ExecutionMode, RiskLevel, RoutingDecision
from .pool_intent_resolver_service import PoolIntentResolver
from .task_classifier_service import TaskClassifierService


class OrchestratorService:
    @inject
    def __init__(
        self,
        task_classifier_service: TaskClassifierService,
        pool_intent_resolver=None,
        subset_builder=None,
        tool_subset_builder=None,
    ):
        self.task_classifier_service = task_classifier_service
        self.pool_intent_resolver = pool_intent_resolver or PoolIntentResolver()
        self.subset_builder = subset_builder
        self.tool_subset_builder = tool_subset_builder

    def decide(self, query: str, **context) -> RoutingDecision:
        try:
            decision = self.task_classifier_service.classify(query)
            pool_result = self.pool_intent_resolver.resolve(
                query, classifier_result=decision.to_dict()
            )
            subset = self._build_agent_subset(pool_result)
            decision.agent_subset = subset
            decision.tool_subset = self._build_tool_subset()
            return decision
        except Exception as exc:
            logging.warning("调度决策失败，回退到原 Assistant Agent 流程: %s", exc)
            return RoutingDecision(
                intent="fallback",
                complexity="unknown",
                execution_mode=ExecutionMode.SINGLE_AGENT.value,
                needs_tools=True,
                needs_agent=True,
                needs_multi_agent=False,
                recommended_model_tier="balanced",
                risk_level=RiskLevel.UNKNOWN.value,
                reason="调度决策失败，已回退到原 Assistant Agent 流程",
                agent_subset={
                    "matched_agent_pools": [],
                    "selected_agents": [],
                    "backup_agents": [],
                    "filtered_out_agents": [],
                    "selection_reason": "fallback:classifier_error",
                },
                tool_subset=self._empty_tool_subset("fallback:classifier_error"),
            )

    def _build_tool_subset(self) -> dict:
        if self.tool_subset_builder is None:
            return self._empty_tool_subset("no_tool_subset_builder")
        return self.tool_subset_builder.build_ranked_subset([])

    @staticmethod
    def _empty_tool_subset(selection_reason: str) -> dict:
        return {
            "selected_tools": [],
            "backup_tools": [],
            "filtered_out_tools": [],
            "selection_reason": selection_reason,
        }

    def _build_agent_subset(self, pool_result: dict) -> dict:
        matched_pools = pool_result.get("matched_pools", ["general"])
        if self.subset_builder is None:
            return {
                "matched_agent_pools": matched_pools,
                "selected_agents": [],
                "backup_agents": [],
                "filtered_out_agents": [],
                "selection_reason": f"matched pools: {','.join(matched_pools)}",
            }
        return self.subset_builder.build_subset_from_candidates(
            [], matched_pools=matched_pools
        )
