import logging
import time
logger = logging.getLogger(__name__)
from types import SimpleNamespace

from injector import inject

from internal.entity.orchestrator_entity import ExecutionMode, RiskLevel, RoutingDecision
from internal.service.billing_metering_service import BillingUsageAggregator
from internal.service.cost_policy_service import CostPolicyService
from internal.service.tool_selector_service import ToolSelectorService
from internal.service.execution_mode_selector_service import ExecutionModeSelectorService
from internal.service.model_assignment_policy_service import ModelAssignmentPolicy
from internal.service.model_gateway_service import ModelGatewayService
from internal.service.orchestration_feature_flag_service import OrchestrationFeatureFlagService
from internal.service.request_context_builder_service import RequestContextBuilder
from internal.service.routing_event_logger import RoutingEventLogger
from internal.service.routing_log_service import RoutingLogService
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
        feature_flag_service: OrchestrationFeatureFlagService | None = None,
        event_logger: RoutingEventLogger | None = None,
        routing_log_service: RoutingLogService | None = None,
        request_context_builder: RequestContextBuilder | None = None,
        model_assignment_policy: ModelAssignmentPolicy | None = None,
        model_gateway_service: ModelGatewayService | None = None,
        cost_policy_service: CostPolicyService | None = None,
        execution_mode_selector: ExecutionModeSelectorService | None = None,
        routing_observability_service: RoutingObservabilityService | None = None,
        agent_pool_service: AgentPoolService | None = None,
        tool_selector_service: ToolSelectorService | None = None,
    ):
        self.task_classifier_service = task_classifier_service
        self.pool_intent_resolver = pool_intent_resolver
        self.subset_builder = subset_builder
        self.tool_subset_builder = tool_subset_builder
        self.task_planner = task_planner
        self.feature_flag_service = feature_flag_service
        self.event_logger = event_logger
        self.routing_log_service = routing_log_service
        self.request_context_builder = request_context_builder
        self.model_assignment_policy = model_assignment_policy
        self.model_gateway_service = model_gateway_service
        self.agent_pool_service = agent_pool_service
        self.cost_policy_service = cost_policy_service
        self.execution_mode_selector = execution_mode_selector
        self.routing_observability_service = routing_observability_service
        self.tool_selector_service = tool_selector_service

    def decide(self, query: str, **context) -> RoutingDecision:
        start_time = time.monotonic()
        ctx = self.request_context_builder.build(query, **context) if self.request_context_builder is not None else SimpleNamespace(
            query=query,
            routing_log_id=context.get("routing_log_id"),
            budget_allowed=bool(context.get("budget_allowed", True)),
            account_id=context.get("account_id"),
            budget_level=context.get("budget_level", "normal"),
            balance_credits=context.get("balance_credits", 1.0),
            deep_thinking_requested=bool(context.get("enable_deep_thinking")),
            image_urls=context.get("image_urls", []),
        )
        routing_log_id = ctx.routing_log_id
        # ENABLE_ROUTING_LOGS 开启且调用方未传 routing_log_id 时，自动创建 pending 记录
        routing_log_created = False
        if routing_log_id is None and self._flag_enabled("ENABLE_ROUTING_LOGS", default=False):
            if self.routing_log_service is not None and ctx.account_id is not None:
                try:
                    routing_log = self.routing_log_service.create_pending(
                        account_id=ctx.account_id,
                        user_query=ctx.query,
                    )
                    routing_log_id = routing_log.id
                    routing_log_created = True
                except Exception:
                    logger.warning("创建 routing_log 记录失败", exc_info=True)
        budget_allowed = ctx.budget_allowed and bool(context.get("budget_allowed", True))
        try:
            self._emit("routing_started", routing_log_id, {"query": ctx.query})
            if not self._flag_enabled("ENABLE_ORCHESTRATOR", default=True):
                return self._feature_disabled_decision()
            decision = self.task_classifier_service.classify(query, budget_allowed=budget_allowed)
            # ENABLE_AUTO_DEEP_THINKING 关闭时，不自动触发深度思考（用户手动请求仍生效）
            if not self._flag_enabled("ENABLE_AUTO_DEEP_THINKING", default=True):
                decision.needs_deep_thinking = False
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
            pool_result = (
                self.pool_intent_resolver.resolve(query, classifier_result=decision.to_dict())
                if self.pool_intent_resolver is not None
                else {"matched_pools": ["general"]}
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
            if self.execution_mode_selector is not None:
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
            decision.tool_subset = self._build_tool_subset(ctx.account_id, query=ctx.query)
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
            self._record_observability(routing_log_id, decision, ctx, start_time)
            # 更新 routing_log 记录为最终状态
            if routing_log_created and self.routing_log_service is not None:
                try:
                    agent_subset = decision.agent_subset or {}
                    tool_subset = decision.tool_subset or {}
                    latency_ms = int((time.monotonic() - start_time) * 1000)
                    self.routing_log_service.finalize(
                        routing_log_id,
                        routing_decision=decision.to_dict(),
                        agent_candidates=agent_subset.get("selected_agents", []),
                        filtered_out_agents=agent_subset.get("filtered_out_agents", []),
                        tool_candidates=tool_subset.get("selected_tools", []),
                        filtered_out_tools=tool_subset.get("filtered_out_tools", []),
                        knowledge_hits=[],
                        billing_events=decision.billing_events or [],
                        status="success",
                        agent_pool_hits=agent_subset.get("selected_agents", []) if isinstance(agent_subset, dict) else [],
                        tool_pool_hits=tool_subset.get("selected_tools", []) if isinstance(tool_subset, dict) else [],
                        latency_ms=latency_ms,
                    )
                except Exception:
                    logger.warning("更新 routing_log 记录失败", exc_info=True)
            return decision
        except Exception as exc:
            logger.warning("调度决策失败，回退到原 Assistant Agent 流程: %s", exc)
            self._emit("routing_failed", routing_log_id, {"error": str(exc)})
            self._emit("fallback_triggered", routing_log_id, {"reason": "classifier_error"})
            # 更新 routing_log 记录为 fallback 状态
            if routing_log_created and self.routing_log_service is not None:
                try:
                    latency_ms = int((time.monotonic() - start_time) * 1000)
                    self.routing_log_service.finalize(
                        routing_log_id,
                        status="fallback",
                        fallback_reason="classifier_error",
                        latency_ms=latency_ms,
                    )
                except Exception:
                    logger.warning("更新 routing_log fallback 记录失败", exc_info=True)
            return RoutingDecision(
                intent="fallback",
                complexity="unknown",
                execution_mode=ExecutionMode.DIRECT_ANSWER.value,
                needs_tools=False,
                needs_agent=False,
                needs_multi_agent=False,
                recommended_model_tier="1",
                risk_level=RiskLevel.UNKNOWN.value,
                reason=f"路由决策异常，回退到直接回答: {exc}",
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
            recommended_model_tier="1",
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
        if not self._flag_enabled("ENABLE_ROUTING_LOGS", default=False):
            return
        if self.event_logger is None or routing_log_id is None:
            return
        try:
            self.event_logger.log_event(event_type, routing_log_id, detail or {})
        except Exception:
            logger.warning("记录路由离散事件失败: %s", event_type, exc_info=True)

    def _record_observability(self, routing_log_id, decision: RoutingDecision, ctx, start_time: float | None = None) -> None:
        if routing_log_id is None:
            return
        if not self._flag_enabled("ENABLE_ROUTING_LOGS", default=False):
            return
        latency_ms = int((time.monotonic() - start_time) * 1000) if start_time is not None else 0
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
                    "latency_ms": latency_ms,
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
                        latency_ms=latency_ms,
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
        # ENABLE_RESULT_SYNTHESIZER 关闭时，跳过 TaskPlanner 详细规划，使用简化摘要
        if not self._flag_enabled("ENABLE_RESULT_SYNTHESIZER", default=False):
            decision.task_plan_summary = self._safe_task_plan_summary()
            decision.synthesis_summary = self._empty_synthesis_summary()
            return
        if self.task_planner is not None:
            task_plan = self.task_planner.plan(query, decision)
            decision.task_plan_summary = task_plan.to_summary()
        else:
            decision.task_plan_summary = self._safe_task_plan_summary()
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
        if self.cost_policy_service is not None:
            decision.cost_policy = self.cost_policy_service.build_policy(
                task_complexity=decision.complexity,
                budget_level=ctx.budget_level,
                balance_credits=ctx.balance_credits,
                deep_thinking_requested=ctx.deep_thinking_requested,
            )
        else:
            decision.cost_policy = self._safe_cost_policy()
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
        if self.model_assignment_policy is not None:
            decision.recommended_model_tier = self.model_assignment_policy.assign(decision, ctx)

    def _safe_cost_policy(self) -> dict:
        if self.cost_policy_service is not None:
            return self.cost_policy_service.build_policy(
                task_complexity="simple",
                budget_level="normal",
                balance_credits=1,
                deep_thinking_requested=False,
            )
        return {
            "allowed": True,
            "model_tier": "cheap",
            "max_agent_count": 0,
            "max_tool_count": 0,
            "deep_thinking": False,
            "reason": "fallback:no_cost_policy_service",
        }

    @staticmethod
    def _billing_started_events() -> list[dict]:
        event = BillingUsageAggregator(
            task_id="orchestrator-routing"
        ).started().to_dict()
        event["event"] = event["event_type"]
        return [event]

    def _build_tool_subset(self, account_id=None, query: str = "") -> dict:
        """构建工具子集（方案A：关键词快通道 + LLM 兜底）。

        ToolSelectorService 已重构为全 source_type 覆盖：
        - 关键词快通道：匹配 task_keywords + tool_name + description
        - LLM 兜底：对 builtin + mcp + skill + workflow + api_tool 做语义选择
        """
        if not self._flag_enabled("ENABLE_TOOL_POOL_RETRIEVAL", default=True):
            return self._empty_tool_subset("feature_flag_disabled")
        if self.tool_subset_builder is None:
            return self._empty_tool_subset("no_tool_subset_builder")
        candidates = []
        if account_id is not None:
            try:
                collected = self.tool_subset_builder.build(account_id)
                candidates = collected.get("candidates", []) if isinstance(collected, dict) else []
            except Exception as exc:
                logger.warning("工具候选收集失败，使用空候选列表: %s", exc, exc_info=True)

        # 工具选择器：关键词快通道 + LLM 语义兜底（覆盖全 source_type）
        if query and self.tool_selector_service is not None and candidates:
            try:
                selected = self.tool_selector_service.select_tools(
                    query, candidates=candidates, max_tools=5,
                )
                if selected:
                    return self._merge_llm_selection_with_ranked(
                        candidates, selected, max_tools=5,
                    )
                # 选择器返回空（如 query="你好"），回退到默认排序
                logger.info(
                    "工具选择器返回空列表，回退默认排序 query=%s",
                    query[:80],
                )
            except Exception as exc:
                logger.warning("工具选择异常，回退到默认排序: %s", exc, exc_info=True)

        # fallback: 默认排序（无查询感知）
        return self.tool_subset_builder.build_ranked_subset(candidates)

    def _merge_llm_selection_with_ranked(
        self,
        candidates: list,
        selected: list[dict[str, str]],
        *,
        max_tools: int = 5,
    ) -> dict:
        """将选中的工具与默认排序结果合并。

        选中的工具（关键词或 LLM 命中）排在前面，其余按默认排序补充。
        使用 (source_type, provider_id, tool_name) 三元组 key 匹配，
        适配全 source_type（builtin/mcp/skill/workflow/api_tool）。
        """
        ranked = self.tool_subset_builder.build_ranked_subset(candidates)
        all_tools = ranked.get("selected_tools", []) + ranked.get("backup_tools", [])

        # 构建选中工具的三元组 key 查找表
        selected_keys: set[tuple[str, str, str]] = set()
        for sel in selected:
            selected_keys.add((
                str(sel.get("source_type", "")),
                str(sel.get("provider_id", "")),
                str(sel.get("tool_name", "")),
            ))

        # 分离选中的工具和其他工具
        matched_tools = []
        other_tools = []
        for tool in all_tools:
            if not isinstance(tool, dict):
                continue
            key = (
                str(tool.get("source_type", "")),
                str(tool.get("provider_id", "")),
                str(tool.get("name", "")),
            )
            if key in selected_keys:
                matched_tools.append(tool)
            else:
                other_tools.append(tool)

        # 选中的工具排在前面
        top_selected = matched_tools[:max_tools]
        # 用其他工具补充到 max_tools
        if len(top_selected) < max_tools:
            top_selected.extend(other_tools[:max_tools - len(top_selected)])

        backup = all_tools[max_tools:] if len(all_tools) > max_tools else []

        return {
            "selected_tools": top_selected,
            "backup_tools": backup,
            "filtered_out_tools": ranked.get("filtered_out_tools", []),
            "selection_reason": "keyword_fast_path_then_llm_then_ranked",
            "matched_count": len(matched_tools),
        }

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
