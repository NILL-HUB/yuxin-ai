import logging

from injector import inject

from internal.entity.orchestrator_entity import ExecutionMode, RiskLevel, RoutingDecision
from internal.service.billing_metering_service import BillingUsageAggregator
from internal.service.cost_policy_service import CostPolicyService
from internal.service.task_planner_service import TaskPlannerService
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
        task_planner=None,
        feature_flag_service=None,
    ):
        self.task_classifier_service = task_classifier_service
        self.pool_intent_resolver = pool_intent_resolver or PoolIntentResolver()
        self.subset_builder = subset_builder
        self.tool_subset_builder = tool_subset_builder
        self.task_planner = task_planner or TaskPlannerService()
        self.feature_flag_service = feature_flag_service

    def decide(self, query: str, **context) -> RoutingDecision:
        try:
            if not self._flag_enabled("ENABLE_ORCHESTRATOR", default=True):
                return self._feature_disabled_decision()
            decision = self.task_classifier_service.classify(query)
            if not self._flag_enabled("ENABLE_MULTI_AGENT_EXECUTION", default=True):
                decision.needs_multi_agent = False
                if decision.execution_mode == ExecutionMode.MULTI_AGENT.value:
                    decision.execution_mode = ExecutionMode.SINGLE_AGENT.value
            pool_result = self.pool_intent_resolver.resolve(
                query, classifier_result=decision.to_dict()
            )
            subset = self._build_agent_subset(pool_result)
            decision.agent_subset = subset
            decision.tool_subset = self._build_tool_subset()
            self._attach_cost_policy(decision, context)
            self._attach_phase6_summaries(query, decision)
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
                cost_policy=self._safe_cost_policy(),
                billing_events=self._billing_started_events(),
                task_plan_summary=self._safe_task_plan_summary(),
                synthesis_summary=self._empty_synthesis_summary(),
            )

    def _feature_disabled_decision(self) -> RoutingDecision:
        return RoutingDecision(
            intent="fallback",
            complexity="simple",
            execution_mode=ExecutionMode.DIRECT_ANSWER.value,
            needs_tools=False,
            needs_agent=False,
            needs_multi_agent=False,
            recommended_model_tier="cheap",
            risk_level=RiskLevel.SAFE.value,
            reason="feature_flag_disabled",
            agent_subset={
                "matched_agent_pools": [],
                "selected_agents": [],
                "backup_agents": [],
                "filtered_out_agents": [],
                "selection_reason": "feature_flag_disabled",
            },
            tool_subset=self._empty_tool_subset("feature_flag_disabled"),
            cost_policy=self._safe_cost_policy(),
            billing_events=self._billing_started_events(),
            task_plan_summary=self._safe_task_plan_summary(),
            synthesis_summary=self._empty_synthesis_summary(),
        )

    def _flag_enabled(self, code: str, *, default: bool) -> bool:
        if self.feature_flag_service is None:
            return default
        return self.feature_flag_service.is_enabled(code)

    def _attach_phase6_summaries(self, query: str, decision: RoutingDecision) -> None:
        task_plan = self.task_planner.plan(query, decision)
        decision.task_plan_summary = task_plan.to_summary()
        decision.synthesis_summary = self._empty_synthesis_summary()

    @staticmethod
    def _safe_task_plan_summary() -> dict:
        return {
            "execution_mode": "direct_answer",
            "reason": "fallback:classifier_error",
            "task_count": 0,
            "items": [],
        }

    @staticmethod
    def _empty_synthesis_summary() -> dict:
        return {
            "final_answer": "",
            "summary": "execution_not_started",
            "confidence": 0,
            "visible_sources": [],
            "user_warnings": [],
        }

    def _attach_cost_policy(self, decision: RoutingDecision, context: dict) -> None:
        if not self._flag_enabled("ENABLE_COST_MODEL_ROUTING", default=True):
            decision.cost_policy = self._safe_cost_policy()
            decision.billing_events = self._billing_started_events()
            return
        decision.cost_policy = CostPolicyService().build_policy(
            task_complexity=decision.complexity,
            budget_level=context.get("budget_level", "normal"),
            balance_credits=context.get("balance_credits", 1),
            deep_thinking_requested=context.get("deep_thinking_requested", False),
        )
        decision.billing_events = self._billing_started_events()

    @staticmethod
    def _safe_cost_policy() -> dict:
        return CostPolicyService().build_policy(
            task_complexity="simple",
            budget_level="normal",
            balance_credits=1,
            deep_thinking_requested=False,
        )

    @staticmethod
    def _billing_started_events() -> list[dict]:
        event = BillingUsageAggregator(
            task_id="orchestrator-routing"
        ).started().to_dict()
        event["event"] = event["event_type"]
        return [event]

    def _build_tool_subset(self) -> dict:
        if not self._flag_enabled("ENABLE_TOOL_POOL_RETRIEVAL", default=True):
            return self._empty_tool_subset("feature_flag_disabled")
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
        if not self._flag_enabled("ENABLE_AGENT_METADATA_ROUTING", default=True):
            return {
                "matched_agent_pools": [],
                "selected_agents": [],
                "backup_agents": [],
                "filtered_out_agents": [],
                "selection_reason": "feature_flag_disabled",
            }
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
