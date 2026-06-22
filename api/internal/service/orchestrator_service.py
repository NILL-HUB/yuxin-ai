import logging
logger = logging.getLogger(__name__)
from types import SimpleNamespace

from injector import inject

from internal.entity.orchestrator_entity import ExecutionMode, RiskLevel, RoutingDecision
from internal.service.billing_metering_service import BillingUsageAggregator
from internal.service.cost_policy_service import CostPolicyService
from internal.service.execution_mode_selector_service import ExecutionModeSelectorService
from internal.service.model_assignment_policy_service import ModelAssignmentPolicy
from internal.service.model_gateway_service import ModelGatewayService
from internal.service.request_context_builder_service import RequestContextBuilder
from internal.service.routing_observability_service import RoutingObservabilityService
from internal.service.task_planner_service import TaskPlannerService
from .agent_pool_service import CrossPoolAgentSubsetBuilder
from .agent_pool_aggregate_service import AgentPoolService
from .tool_inventory_service import CrossPoolToolSubsetBuilder
from .pool_intent_resolver_service import PoolIntentResolver
from .task_classifier_service import TaskClassifierService


class OrchestratorService:
    @inject
    def __init__(
        self,
        task_classifier_service: TaskClassifierService,
        pool_intent_resolver: PoolIntentResolver | None = None,
        subset_builder: CrossPoolAgentSubsetBuilder | None = None,
        tool_subset_builder: CrossPoolToolSubsetBuilder | None = None,
        task_planner: TaskPlannerService | None = None,
        feature_flag_service=None,
        event_logger=None,
        request_context_builder: RequestContextBuilder | None = None,
        model_assignment_policy: ModelAssignmentPolicy | None = None,
        model_gateway_service: ModelGatewayService | None = None,
        cost_policy_service: CostPolicyService | None = None,
        execution_mode_selector: ExecutionModeSelectorService | None = None,
        routing_observability_service: RoutingObservabilityService | None = None,
        agent_pool_service: AgentPoolService | None = None,
    ):
        self.task_classifier_service = task_classifier_service
        self.pool_intent_resolver = pool_intent_resolver or PoolIntentResolver()
        self.subset_builder = subset_builder
        self.tool_subset_builder = tool_subset_builder
        self.task_planner = task_planner or TaskPlannerService()
        self.feature_flag_service = feature_flag_service
        self.event_logger = event_logger
        self.request_context_builder = request_context_builder or RequestContextBuilder()
        self.model_assignment_policy = model_assignment_policy or ModelAssignmentPolicy()
        self.model_gateway_service = model_gateway_service
        self.agent_pool_service = agent_pool_service
        self.cost_policy_service = cost_policy_service or CostPolicyService()
        self.execution_mode_selector = execution_mode_selector or ExecutionModeSelectorService()
        self.routing_observability_service = routing_observability_service

    def decide(self, query: str, **context) -> RoutingDecision:
        ctx = self.request_context_builder.build(query, **context)
        routing_log_id = ctx.routing_log_id
        budget_allowed = ctx.budget_allowed and bool(context.get("budget_allowed", True))
        try:
            self._emit("routing_started", routing_log_id, {"query": ctx.query})
            if not self._flag_enabled("ENABLE_ORCHESTRATOR", default=True):
                return self._feature_disabled_decision()
            decision = self.task_classifier_service.classify(query, budget_allowed=budget_allowed)
            self._emit(
                "task_classified",
                routing_log_id,
                {
                    "intent": decision.intent,
                    "complexity": decision.complexity,
                    "execution_mode": decision.execution_mode,
                },
            )
            if not self._flag_enabled("ENABLE_MULTI_AGENT_EXECUTION", default=True):
                decision.needs_multi_agent = False
                if decision.execution_mode in (
                    ExecutionMode.MULTI_AGENT.value,
                    ExecutionMode.MULTI_AGENT_PARALLEL.value,
                    ExecutionMode.MULTI_AGENT_SEQUENTIAL.value,
                ):
                    decision.execution_mode = ExecutionMode.SINGLE_AGENT.value
            pool_result = self.pool_intent_resolver.resolve(
                query, classifier_result=decision.to_dict()
            )
            self._emit(
                "agent_candidates_found",
                routing_log_id,
                {"matched_pools": pool_result.get("matched_pools", [])},
            )
            subset = self._build_agent_subset(pool_result, ctx.account_id)
            decision.agent_subset = subset
            self._emit(
                "agent_selected",
                routing_log_id,
                {"selected_agents": subset.get("selected_agents", [])},
            )
            decision.execution_mode = self.execution_mode_selector.select(
                risk_level=decision.risk_level,
                needs_deep_thinking=decision.needs_deep_thinking,
                deep_thinking_requested=ctx.deep_thinking_requested,
                needs_multi_agent=decision.needs_multi_agent,
                needs_tools=decision.needs_tools,
                needs_agent=decision.needs_agent,
                available_pool_count=len(pool_result.get("matched_pools", [])),
                image_count=len(ctx.image_urls),
                preliminary_mode=decision.execution_mode,
            )
            decision.tool_subset = self._build_tool_subset(ctx.account_id)
            self._emit(
                "tool_candidates_found",
                routing_log_id,
                {"selected_tools": decision.tool_subset.get("selected_tools", [])},
            )
            self._emit(
                "tool_selected",
                routing_log_id,
                {"selected_tools": decision.tool_subset.get("selected_tools", [])},
            )
            self._attach_cost_policy(decision, ctx)
            self._attach_model_assignment(decision, ctx)
            self._emit(
                "model_selected",
                routing_log_id,
                {
                    "recommended_model_tier": decision.recommended_model_tier,
                    "cost_policy": decision.cost_policy,
                },
            )
            self._attach_phase6_summaries(ctx.query, decision)
            self._record_observability(routing_log_id, decision, ctx)
            return decision
        except Exception as exc:
            logger.warning("调度决策失败，回退到原 Assistant Agent 流程: %s", exc)
            self._emit("routing_failed", routing_log_id, {"error": str(exc)})
            self._emit("fallback_triggered", routing_log_id, {"reason": "classifier_error"})
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

    def _emit(self, event_type: str, routing_log_id, detail: dict | None = None) -> None:
        if self.event_logger is None or routing_log_id is None:
            return
        try:
            self.event_logger.log_event(event_type, routing_log_id, detail or {})
        except Exception:
            logger.warning("记录路由离散事件失败: %s", event_type, exc_info=True)

    def _record_observability(self, routing_log_id, decision: RoutingDecision, ctx) -> None:
        if routing_log_id is None:
            return
        try:
            self._emit(
                "routing_completed",
                routing_log_id,
                {
                    "intent": decision.intent,
                    "execution_mode": decision.execution_mode,
                    "complexity": decision.complexity,
                    "risk_level": decision.risk_level,
                    "recommended_model_tier": decision.recommended_model_tier,
                    "needs_deep_thinking": decision.needs_deep_thinking,
                    "needs_multi_agent": decision.needs_multi_agent,
                    "cost_policy_allowed": decision.cost_policy.get("allowed", True) if decision.cost_policy else True,
                },
            )
        except Exception:
            logger.warning("记录路由事件失败", exc_info=True)
        if self.routing_observability_service is not None:
            try:
                agent_subset = decision.agent_subset or {}
                tool_subset = decision.tool_subset or {}
                self.routing_observability_service.summarize([
                    SimpleNamespace(
                        status="success",
                        routing_log_id=str(routing_log_id),
                        intent=decision.intent,
                        execution_mode=decision.execution_mode,
                        complexity=decision.complexity,
                        risk_level=decision.risk_level,
                        fallback_reason="",
                        latency_ms=0,
                        cost_summary={"total_credits": 0},
                        agent_pool_hits=agent_subset.get("selected_agents", []) if isinstance(agent_subset, dict) else [],
                        tool_pool_hits=tool_subset.get("selected_tools", []) if isinstance(tool_subset, dict) else [],
                        agent_candidates=agent_subset.get("selected_agents", []) if isinstance(agent_subset, dict) else [],
                        tool_candidates=tool_subset.get("selected_tools", []) if isinstance(tool_subset, dict) else [],
                    )
                ])
            except Exception:
                logger.warning("路由可观测摘要记录失败", exc_info=True)

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

    def _attach_cost_policy(self, decision: RoutingDecision, ctx) -> None:
        if not self._flag_enabled("ENABLE_COST_MODEL_ROUTING", default=True):
            decision.cost_policy = self._safe_cost_policy()
            decision.billing_events = self._billing_started_events()
            return
        decision.cost_policy = self.cost_policy_service.build_policy(
            task_complexity=decision.complexity,
            budget_level=ctx.budget_level,
            balance_credits=ctx.balance_credits,
            deep_thinking_requested=ctx.deep_thinking_requested,
        )
        decision.billing_events = self._billing_started_events()

    def _attach_model_assignment(self, decision: RoutingDecision, ctx) -> None:
        if not self._flag_enabled("ENABLE_MODEL_ASSIGNMENT_POLICY", default=True):
            return
        if self.model_gateway_service is not None:
            try:
                decision.recommended_model_tier = self.model_gateway_service.resolve_model_tier(decision, ctx)
                return
            except Exception:
                logger.warning("ModelGateway 档位解析失败，回退直接策略", exc_info=True)
        decision.recommended_model_tier = self.model_assignment_policy.assign(decision, ctx)

    def _safe_cost_policy(self) -> dict:
        return self.cost_policy_service.build_policy(
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

    def _build_tool_subset(self, account_id=None) -> dict:
        if not self._flag_enabled("ENABLE_TOOL_POOL_RETRIEVAL", default=True):
            return self._empty_tool_subset("feature_flag_disabled")
        if self.tool_subset_builder is None:
            return self._empty_tool_subset("no_tool_subset_builder")
        candidates = []
        if account_id is not None:
            try:
                collected = self.tool_subset_builder.build(account_id)
                candidates = collected.get("candidates", []) if isinstance(collected, dict) else []
            except Exception:
                logger.warning("工具候选收集失败，使用空候选列表", exc_info=True)
        return self.tool_subset_builder.build_ranked_subset(candidates)

    @staticmethod
    def _empty_tool_subset(selection_reason: str) -> dict:
        return {
            "selected_tools": [],
            "backup_tools": [],
            "filtered_out_tools": [],
            "selection_reason": selection_reason,
        }

    def _build_agent_subset(self, pool_result: dict, account_id=None) -> dict:
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
        candidates = []
        if account_id is not None:
            try:
                collected = self.subset_builder.build(account_id)
                candidates = collected.get("candidates", []) if isinstance(collected, dict) else []
            except Exception:
                logger.warning("Agent 候选收集失败，尝试 AgentPoolService fallback", exc_info=True)
                if self.agent_pool_service is not None:
                    try:
                        candidates = self.agent_pool_service.list_agents()
                    except Exception:
                        logger.warning("AgentPoolService fallback 失败", exc_info=True)
                        candidates = []
        return self.subset_builder.build_subset_from_candidates(
            candidates, matched_pools=matched_pools
        )
