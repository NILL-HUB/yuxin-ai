"""指挥官（Conductor）决策层服务。

职责：
1. 接收用户请求，判断是直接回复还是派发 Agent；
2. 为每个 Agent 子任务匹配合适的模型档位和能力要求；
3. 输出结构化的 ConductorPlan，由下游执行器执行。

设计原则：
- 不把爆炸长度的工具列表塞进指挥官上下文（工具选择交给 Agent）；
- 仅暴露模型池摘要（名称+能力+档位+成本）和 Agent 池摘要（名称+能力）；
- 硬约束校验失败回退到 single_agent，保证系统可用性；
- 指挥官模型通过 public_ai_feature_config 表的 feature_key="conductor" 配置。
"""
import json
import logging
from dataclasses import dataclass
from typing import Any

from injector import inject
from pydantic import BaseModel, Field

from internal.entity.agent_pool_entity import AgentSubPoolRegistry
from internal.entity.conductor_entity import (
    AggregationStrategy,
    ConductorAgentTask,
    ConductorMode,
    ConductorPlan,
    ConductorPlanValidator,
    ConductorRiskLevel,
    EscalationAction,
    EscalationDecision,
    MAX_AGENTS_PER_PLAN,
)
from internal.service.language_model_service import LanguageModelService
from internal.service.prompt_sync_service import PromptSyncService
from internal.service.resource_vector_index_service import ResourceVectorIndexService

logger = logging.getLogger(__name__)


# =========================================================
# Pydantic Schema：用于 LLM with_structured_output
# =========================================================

class ConductorAgentTaskModel(BaseModel):
    """子任务 schema（LLM 输出契约）。"""
    task_id: str = Field(description="任务唯一 ID，如 t1、t2")
    title: str = Field(description="子任务标题（简短）")
    description: str = Field(description="子任务描述，交给 Agent 执行的具体指令")
    agent_pool: str = Field(
        default="general",
        description="Agent 池归属：general/coding/office/data/research/customer_service/internal_admin",
    )
    required_capabilities: list[str] = Field(
        default_factory=list,
        description="所需能力标签，如 coding/translation/data_analysis",
    )
    model_tier: str = Field(
        default="1",
        description="模型档位：1=轻量省钱 2=标准 3=强模型贵",
    )
    depends_on: list[str] = Field(
        default_factory=list,
        description="依赖的 task_id 列表（multi_agent_parallel 必须为空）",
    )
    risk_level: str = Field(
        default="safe",
        description="风险等级：safe/medium/high",
    )
    expected_output: str = Field(
        default="",
        description="期望输出说明，供 Agent 参考",
    )


class ConductorPlanModel(BaseModel):
    """指挥官编排计划 schema（LLM 输出契约）。"""
    execution_mode: str = Field(
        description=(
            "执行模式：direct_answer | single_agent | multi_agent_parallel | "
            "multi_agent_sequential | reject_or_confirm"
        )
    )
    intent: str = Field(description="任务意图简述（一句话）")
    complexity: str = Field(description="复杂度：simple | moderate | complex")
    reason: str = Field(description="决策原因（一句话）")

    direct_answer: str | None = Field(
        default=None,
        description="execution_mode=direct_answer 时，指挥官直接给出的完整回复",
    )

    agents: list[ConductorAgentTaskModel] = Field(
        default_factory=list,
        description="Agent 子任务列表（direct_answer/reject_or_confirm 模式为空）",
    )
    aggregation_strategy: str = Field(
        default="summarize",
        description="多 Agent 结果聚合策略：concat | summarize | best_of",
    )

    needs_clarification: bool = Field(
        default=False,
        description="execution_mode=reject_or_confirm 时，是否需要用户澄清",
    )
    clarification_question: str | None = Field(
        default=None,
        description="需澄清时给用户的问题",
    )
    reject_reason: str | None = Field(
        default=None,
        description="拒绝执行的原因（不合规/超出能力等）",
    )

    risk_level: str = Field(default="safe", description="整体风险等级")
    estimated_cost_tier: str = Field(
        default="low",
        description="预估成本档位：low | medium | high",
    )


# =========================================================
# 系统提示词（从 DB prompt_template 表加载，YAML→DB 同步由 PromptSyncService 负责）
# =========================================================

# prompt_key 常量，与 internal/core/prompts/routing/conductor.yaml 对应
CONDUCTOR_PROMPT_KEY = "conductor"


def _get_fallback_conductor_prompt() -> str:
    """读取指挥官兜底提示词（系统提示词库可管理，YAML 兜底）。

    默认文本集中在 internal/core/prompts/system_prompts.yaml
    （key=conductor_fallback），管理员可在系统提示词库中编辑覆盖。
    """
    from internal.service.system_prompt_library_service import SystemPromptLibraryService
    return SystemPromptLibraryService().get_prompt_or_default("conductor_fallback")


# =========================================================
# 资源摘要构建
# =========================================================

def _build_agent_pool_summary() -> list[dict[str, Any]]:
    """构建 Agent 池摘要（轻量，不含完整工具列表）。

    只暴露：name + label + description + default_capabilities + task_keywords
    仅包含 visible_to_user=True 的池（internal_admin 不暴露给指挥官 LLM）。
    """
    try:
        registry = AgentSubPoolRegistry()
        pools = registry.list_pools()
        return [
            {
                "name": p.get("name", ""),
                "label": p.get("label", p.get("name", "")),
                "description": p.get("description", ""),
                "capabilities": list(p.get("default_capabilities") or []),
                "task_keywords": list(p.get("task_keywords") or [])[:10],
            }
            for p in pools
            if p.get("visible_to_user", True)
        ]
    except Exception:
        logger.warning("构建 Agent 池摘要失败", exc_info=True)
        return []


def _build_model_summary(top_k: int = 12) -> list[dict[str, Any]]:
    """构建模型池摘要（从向量索引查询，轻量）。

    只暴露：resource_id + resource_name + capabilities + sub_pool + metadata.cost_tier
    不暴露完整 description，避免上下文爆炸。
    """
    try:
        svc = ResourceVectorIndexService()
        # 用通用查询词检索，获取代表性模型
        results = svc.search(
            resource_type="model",
            query="general purpose chat coding reasoning text generation",
            top_k=top_k,
        )
        summary = []
        for r in results:
            metadata = r.get("metadata") or {}
            summary.append({
                "model_id": r.get("resource_id"),
                "model_name": r.get("resource_name"),
                "capabilities": list(r.get("capabilities") or []),
                "sub_pool": r.get("sub_pool"),
                "cost_tier": metadata.get("cost_tier", "medium"),
                "model_type": metadata.get("model_type", "chat"),
            })
        return summary
    except Exception:
        logger.warning("构建模型摘要失败，降级为空列表", exc_info=True)
        return []


def _build_user_context_section(
    query: str,
    conversation_summary: str | None = None,
    budget_level: str = "normal",
    balance_credits: float = 1.0,
    image_url_count: int = 0,
) -> str:
    """构建用户上下文段落。"""
    parts = [f"## 用户请求\n{query}"]
    if conversation_summary:
        parts.append(f"## 会话上下文摘要\n{conversation_summary}")
    parts.append(f"## 预算约束\nbudget_level={budget_level}, balance_credits={balance_credits:.2f}")
    if image_url_count > 0:
        parts.append(f"## 输入模态\n包含 {image_url_count} 张图片")
    return "\n\n".join(parts)


def _build_resource_section(
    agent_pools: list[dict[str, Any]],
    models: list[dict[str, Any]],
) -> str:
    """构建资源摘要段落。"""
    return (
        "## 可用 Agent 池\n"
        f"{json.dumps(agent_pools, ensure_ascii=False, indent=2)}\n\n"
        "## 可用模型池摘要（按需选择档位，model_id_hint 可填 model_id）\n"
        f"{json.dumps(models, ensure_ascii=False, indent=2)}"
    )


# =========================================================
# 指挥官服务
# =========================================================

@inject
@dataclass
class ConductorService:
    """指挥官决策层服务。

    入口方法 plan() 接收用户请求和上下文，返回结构化的 ConductorPlan。
    """
    language_model_service: LanguageModelService

    # ── 主入口 ──────────────────────────────────────────────────

    def plan(
        self,
        query: str,
        *,
        conversation_summary: str | None = None,
        budget_level: str = "normal",
        balance_credits: float = 1.0,
        image_url_count: int = 0,
    ) -> ConductorPlan:
        """分析用户请求，输出编排计划。

        Args:
            query: 用户原始请求
            conversation_summary: 会话上下文摘要（可选）
            budget_level: 预算等级 normal/strict/loose
            balance_credits: 用户余额（用于预算判断）
            image_url_count: 输入图片数量

        Returns:
            ConductorPlan: 经过硬约束校验的编排计划。
            LLM 调用或校验失败时回退到 single_agent 模式。
        """
        try:
            plan_model = self._invoke_llm(
                query=query,
                conversation_summary=conversation_summary,
                budget_level=budget_level,
                balance_credits=balance_credits,
                image_url_count=image_url_count,
            )
            plan = self._to_plan(plan_model)
            ok, err = ConductorPlanValidator.validate(plan)
            if not ok:
                logger.warning("指挥官计划校验失败: %s, 回退到 single_agent", err)
                return self._fallback_plan(query, f"validation_failed: {err}")
            return plan
        except Exception as exc:
            logger.exception("指挥官决策失败，回退到 single_agent: %s", exc)
            return self._fallback_plan(query, f"exception: {exc}")

    # ── LLM 调用 ───────────────────────────────────────────────

    def _invoke_llm(
        self,
        query: str,
        conversation_summary: str | None,
        budget_level: str,
        balance_credits: float,
        image_url_count: int,
    ) -> ConductorPlanModel:
        """调用指挥官 LLM，返回结构化计划。"""
        llm = self.language_model_service.get_feature_model("conductor")
        structured_llm = llm.with_structured_output(ConductorPlanModel)

        agent_pools = _build_agent_pool_summary()
        models = _build_model_summary()

        # 从 DB 加载 prompt（admin 可在后台编辑覆盖）
        system_prompt = PromptSyncService.get_prompt(
            CONDUCTOR_PROMPT_KEY,
            max_agents=MAX_AGENTS_PER_PLAN,
        )
        if not system_prompt:
            logger.warning("DB 中未找到 conductor prompt，使用兜底 prompt")
            system_prompt = _get_fallback_conductor_prompt().format(max_agents=MAX_AGENTS_PER_PLAN)

        user_section = _build_user_context_section(
            query=query,
            conversation_summary=conversation_summary,
            budget_level=budget_level,
            balance_credits=balance_credits,
            image_url_count=image_url_count,
        )
        resource_section = _build_resource_section(agent_pools, models)

        from internal.service.system_prompt_library_service import SystemPromptLibraryService
        plan_instruction = SystemPromptLibraryService().get_prompt_or_default(
            "conductor_plan_instruction"
        )
        prompt = f"""{system_prompt}

---

{user_section}

---

{resource_section}

---

{plan_instruction}"""
        # 复用 LLMActivityProbe 探针：用 stream() 替代 invoke() 获取 token 活性，
        # 后台线程每 60s 检测一次，LLM 持续产出 chunk 则不干扰（复杂需求可运行数小时），
        # 仅在 LLM 死机（60s 无 chunk）时才终止调用。
        # 比固定超时更合理：正常长任务不受影响，死机时能快速检测并回退。
        from internal.service.memory.llm_activity_probe import (
            LLMActivityProbe,
            LLMActivityTimeoutError,
        )
        try:
            response = LLMActivityProbe.invoke_structured_with_probe(
                llm,
                ConductorPlanModel,
                prompt,
                feature_key="conductor",
            )
        except LLMActivityTimeoutError:
            raise
        except Exception:
            raise
        # 指挥官 LLM 计费：conductor 是 billable=false 的 feature_key（见
        # public_ai_feature_config 表），不扣用户额度。charge_for_feature 的实际签名为
        # (credit_service, account_id, feature_key, token_count)，需要 credit_service 与
        # account_id，而 _invoke_llm 上下文中不可得，故此处仅记录 token usage 到日志，
        # 供成本统计与对账使用。
        try:
            usage = getattr(response, "usage_metadata", None) or {}
            input_tokens = usage.get("input_tokens", 0) if isinstance(usage, dict) else 0
            output_tokens = usage.get("output_tokens", 0) if isinstance(usage, dict) else 0
            if input_tokens or output_tokens:
                logger.info(
                    "指挥官 LLM token usage: input=%d, output=%d",
                    input_tokens, output_tokens,
                )
        except Exception:
            logger.warning("指挥官 LLM token usage 记录失败", exc_info=True)
        return response

    # ── 计划转换 ───────────────────────────────────────────────

    @staticmethod
    def _to_plan(model: ConductorPlanModel) -> ConductorPlan:
        """将 Pydantic 模型转换为 ConductorPlan dataclass。"""
        agents = [
            ConductorAgentTask(
                task_id=a.task_id,
                title=a.title,
                description=a.description,
                agent_pool=a.agent_pool,
                required_capabilities=list(a.required_capabilities),
                model_tier=a.model_tier,
                model_id_hint=None,  # 不直接信任 LLM 选的 model_id，由下游匹配
                depends_on=list(a.depends_on),
                risk_level=a.risk_level,
                expected_output=a.expected_output,
            )
            for a in model.agents
        ]
        return ConductorPlan(
            execution_mode=model.execution_mode,
            intent=model.intent,
            complexity=model.complexity,
            reason=model.reason,
            direct_answer=model.direct_answer,
            agents=agents,
            aggregation_strategy=model.aggregation_strategy,
            needs_clarification=model.needs_clarification,
            clarification_question=model.clarification_question,
            reject_reason=model.reject_reason,
            risk_level=model.risk_level,
            estimated_cost_tier=model.estimated_cost_tier,
        )

    @staticmethod
    def _fallback_plan(query: str, reason: str) -> ConductorPlan:
        """校验或调用失败时回退到 direct_answer 模式。

        回退到 direct_answer 而非 single_agent，避免 FunctionCallAgent 循环
        导致持续烧 token 且前端无内容回显的问题。direct_answer 路径直接调用
        LLM 流式生成回答，简单高效。
        """
        return ConductorPlan(
            execution_mode=ConductorMode.DIRECT_ANSWER.value,
            intent="fallback",
            complexity="simple",
            reason=f"指挥官回退: {reason}",
            agents=[],
            aggregation_strategy=AggregationStrategy.CONCAT.value,
            risk_level=ConductorRiskLevel.SAFE.value,
            estimated_cost_tier="low",
        )

    # ── 档位对齐：capability 触发 tier 升级 ────────────────────

    # capability → 升级后的档位映射
    # 指挥官 model_tier 保持 1/2/3（算力档位），
    # required_capabilities 含特定能力时自动升级到 4/5（能力档位），与 fallback_tier 体系对齐
    _CAPABILITY_TIER_UPGRADE = {
        "vision": "4",         # 视觉模型
        "long_context": "5",   # 长上下文模型
    }

    @classmethod
    def _resolve_effective_tier(cls, agent: ConductorAgentTask) -> str:
        """解析 Agent 子任务的实际档位。

        指挥官输出的 model_tier (1/2/3) 是算力档位，
        若 required_capabilities 含 vision/long_context，自动升级到对应能力档位 (4/5)。
        取 model_tier 和 capability 升级档位中的较高值。
        """
        base_tier = int(agent.model_tier) if agent.model_tier in {"1", "2", "3"} else 1
        for cap in agent.required_capabilities or []:
            upgraded = cls._CAPABILITY_TIER_UPGRADE.get(cap)
            if upgraded and int(upgraded) > base_tier:
                base_tier = int(upgraded)
        return str(base_tier)

    # ── 缺能力上报处理 ─────────────────────────────────────────

    # 重试时放宽的阈值
    _RELAXED_SCORE_THRESHOLD = 0.25
    # 低于此分数则认定确实缺能力（即便重试也无用）
    _HARD_FLOOR_SCORE = 0.15

    # ── 转换为 RoutingDecision 兼容格式 ────────────────────────

    # ConductorMode → 现有 ExecutionMode 映射
    _MODE_MAP = {
        ConductorMode.DIRECT_ANSWER.value: "direct_answer",
        ConductorMode.SINGLE_AGENT.value: "single_agent",
        ConductorMode.MULTI_AGENT_PARALLEL.value: "multi_agent_parallel",
        ConductorMode.MULTI_AGENT_SEQUENTIAL.value: "multi_agent_sequential",
        ConductorMode.REJECT_OR_CONFIRM.value: "reject_or_confirm",
    }

    def to_routing_decision_dict(self, plan: ConductorPlan) -> dict[str, Any]:
        """将 ConductorPlan 转换为 RoutingDecision 兼容的 dict。

        使指挥官输出能复用现有 DirectAnswerExecutor/SingleAgentExecutor/MultiAgentExecutor。
        现有执行器通过 routing_decision.get("execution_mode") 等方式消费此 dict。

        指挥官特有字段（direct_answer/clarification_question/reject_reason）
        通过 task_plan_summary 传递，执行器可从中读取。
        """
        execution_mode = self._MODE_MAP.get(plan.execution_mode, "single_agent")
        is_multi_agent = execution_mode in {
            "multi_agent", "multi_agent_parallel", "multi_agent_sequential"
        }
        needs_agent = execution_mode not in {"direct_answer", "reject_or_confirm"}

        # 推荐模型档位：取 agents 中最高档位（含 capability 触发的档位升级）
        # 指挥官 model_tier 保持 1/2/3（算力档位），
        # required_capabilities 含 vision/long_context 时下游自动升级到 4/5（能力档位）
        recommended_tier = "1"
        if plan.agents:
            tiers = [
                int(self._resolve_effective_tier(a))
                for a in plan.agents
                if a.model_tier in {"1", "2", "3"}
            ]
            if tiers:
                recommended_tier = str(max(tiers))

        # agent_subset：供现有执行器读取的 Agent 子集
        selected_agents = [a.to_dict() for a in plan.agents]
        agent_subset = {
            "selected": selected_agents,
            "selected_agents": selected_agents,  # 兼容 MultiAgentExecutor 读取的键名
            "aggregation_strategy": plan.aggregation_strategy,
            "source": "conductor",
        }

        # task_plan_summary：传递指挥官的完整计划
        task_plan_summary = {
            "intent": plan.intent,
            "complexity": plan.complexity,
            "reason": plan.reason,
            "direct_answer": plan.direct_answer,
            "agents": [a.to_dict() for a in plan.agents],
            "aggregation_strategy": plan.aggregation_strategy,
            "needs_clarification": plan.needs_clarification,
            "clarification_question": plan.clarification_question,
            "reject_reason": plan.reject_reason,
            "estimated_cost_tier": plan.estimated_cost_tier,
        }

        return {
            "intent": plan.intent,
            "complexity": plan.complexity,
            "execution_mode": execution_mode,
            "needs_tools": needs_agent and bool(plan.agents),
            "needs_agent": needs_agent,
            "needs_multi_agent": is_multi_agent,
            "needs_deep_thinking": False,
            "recommended_model_tier": recommended_tier,
            "risk_level": plan.risk_level,
            "reason": plan.reason,
            "agent_subset": agent_subset,
            "tool_subset": None,  # 工具由 Agent 自行检索，不由指挥官指定
            "cost_policy": {"allowed": True, "reason": "conductor_default_allow"},
            "billing_events": [],
            "task_plan_summary": task_plan_summary,
            "synthesis_summary": None,
        }

    def handle_escalation(
        self,
        task: ConductorAgentTask,
        find_result,
        *,
        already_retried: bool = False,
    ) -> EscalationDecision:
        """处理 Agent 工具检索上报。

        Agent 通过 AgentToolFinder 检索工具后，若 needs_escalation=True，
        调用此方法由指挥官决策下一步动作。

        Args:
            task: 指挥官分配的子任务
            find_result: AgentToolFinder.find_tools() 返回的 ToolFindResult
            already_retried: 是否已经重试过一次（避免无限重试）

        Returns:
            EscalationDecision: 指挥官的处理决策
        """
        best_score = find_result.best_score if find_result else 0.0
        required_caps = task.required_capabilities or []

        # 已重试过仍失败 → 放弃
        if already_retried:
            return EscalationDecision(
                action=EscalationAction.GIVE_UP.value,
                reason=f"重试后仍无法找到合适工具 (best_score={best_score:.3f})",
            )

        # 分数在 [MIN_SCORE, GOOD_SCORE] 之间 → 可能阈值过高，放宽重试
        if best_score >= self._RELAXED_SCORE_THRESHOLD:
            return EscalationDecision(
                action=EscalationAction.RETRY_RELAXED.value,
                reason=f"初始阈值过高 best={best_score:.3f}，放宽到 {self._RELAXED_SCORE_THRESHOLD}",
                relaxed_threshold=self._RELAXED_SCORE_THRESHOLD,
            )

        # 分数极低 → 确实缺能力
        if not required_caps:
            # 任务未声明所需能力，可能是描述不清 → 请用户澄清
            return EscalationDecision(
                action=EscalationAction.REPORT_USER.value,
                message=(
                    f"任务「{task.title}」未声明所需能力，且系统未检索到匹配工具。"
                    f"请补充更详细的任务描述或所需能力。"
                ),
                reason="未声明所需能力且无工具命中",
            )

        # 声明了所需能力但找不到工具 → 回报用户缺工具
        missing_caps = ", ".join(required_caps)
        return EscalationDecision(
            action=EscalationAction.REPORT_USER.value,
            message=(
                f"任务「{task.title}」需要以下能力但系统暂无匹配工具：{missing_caps}。"
                f"请添加对应的 MCP 工具或 Skill，或调整任务要求。"
            ),
            reason=f"缺能力: {missing_caps} (best_score={best_score:.3f})",
        )
