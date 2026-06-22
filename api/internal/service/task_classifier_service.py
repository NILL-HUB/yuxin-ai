import logging
from dataclasses import dataclass

from injector import inject
from pydantic import BaseModel, Field

from internal.entity.orchestrator_entity import ExecutionMode, RiskLevel, RoutingDecision
from internal.service.language_model_service import LanguageModelService


logger = logging.getLogger(__name__)


class TaskClassificationResult(BaseModel):
    """LLM 驱动的任务分类结构化输出。"""

    intent: str = Field(
        description="任务意图：deep_thinking_task / vertical_agent_task / multi_agent_task / tool_task / general_qa"
    )
    execution_mode: str = Field(
        description="执行模式：DEEP_THINKING / SINGLE_AGENT_WITH_TOOLS / MULTI_AGENT_PARALLEL / DIRECT_ANSWER"
    )
    needs_deep_thinking: bool = Field(default=False, description="是否需要深度思考")
    needs_multi_agent: bool = Field(default=False, description="是否需要多智能体协作")
    needs_tools: bool = Field(default=False, description="是否需要调用工具")
    confidence: float = Field(default=0.0, description="分类置信度，0 到 1 之间")
    reason: str = Field(default="", description="简短分类理由")


@inject
@dataclass
class TaskClassifierService:
    language_model_service: LanguageModelService = None

    HIGH_RISK_KEYWORDS = (
        "删除数据库",
        "清空数据库",
        "删除所有",
        "清空所有",
        "drop table",
        "truncate",
        "rm -rf",
        "删库",
    )
    TOOL_KEYWORDS = (
        "查询",
        "搜索",
        "查一下",
        "天气",
        "股票",
        "联网",
        "下载",
        "生成文件",
        "整理成表格",
        "调用",
    )
    AGENT_KEYWORDS = (
        "智能体",
        "agent",
        "Agent",
        "使用",
        "交给",
        "让",
    )
    VERTICAL_HINTS = (
        "护肤",
        "法务",
        "财务",
        "招聘",
        "客服",
        "运营",
        "投研",
        "代码",
        "设计",
    )
    MULTI_AGENT_KEYWORDS = (
        "分别",
        "多个角度",
        "同时",
        "并行",
        "协作",
        "综合",
        "多维度",
    )

    _VALID_INTENTS = {
        "deep_thinking_task",
        "vertical_agent_task",
        "multi_agent_task",
        "tool_task",
        "general_qa",
    }
    _INTENT_TO_EXECUTION_MODE = {
        "deep_thinking_task": ExecutionMode.DEEP_THINKING.value,
        "vertical_agent_task": ExecutionMode.SINGLE_AGENT_WITH_TOOLS.value,
        "multi_agent_task": ExecutionMode.MULTI_AGENT_PARALLEL.value,
        "tool_task": ExecutionMode.SINGLE_AGENT_WITH_TOOLS.value,
        "general_qa": ExecutionMode.DIRECT_ANSWER.value,
    }
    _COMPLEXITY_BY_INTENT = {
        "deep_thinking_task": "complex",
        "multi_agent_task": "complex",
        "vertical_agent_task": "medium",
        "tool_task": "medium",
        "general_qa": "simple",
    }
    _TIER_BY_COMPLEXITY = {
        "complex": "strong",
        "medium": "balanced",
        "simple": "cheap",
    }

    def classify(self, query: str, *, budget_allowed: bool = True) -> RoutingDecision:
        normalized = self._normalize(query)

        if self._contains_high_risk(normalized):
            return RoutingDecision(
                intent="high_risk_operation",
                complexity="complex",
                execution_mode=ExecutionMode.REJECT_OR_CONFIRM.value,
                needs_tools=False,
                needs_agent=False,
                recommended_model_tier="strong",
                risk_level=RiskLevel.HIGH.value,
                reason="用户请求包含高风险操作，需要拒绝或二次确认",
            )

        if budget_allowed and self.language_model_service is not None:
            try:
                llm_result = self._classify_with_llm(normalized)
                if llm_result is not None:
                    return self._build_decision_from_llm(llm_result, normalized)
            except Exception:
                logger.warning("LLM 任务分类失败，降级到关键词匹配", exc_info=True)

        return self._classify_with_keywords(normalized)

    def _classify_with_llm(self, query: str) -> TaskClassificationResult:
        llm = self.language_model_service.get_cheap_chat_model()
        structured = llm.with_structured_output(TaskClassificationResult)
        return structured.invoke(self._build_classification_prompt(query))

    @staticmethod
    def _build_classification_prompt(query: str) -> str:
        return (
            "你是一名任务分类专家，负责对用户查询进行路由分类。\n\n"
            "输入：用户查询\n"
            f"用户查询：{query}\n\n"
            "分类规则（从下列类别中选择最匹配的一项）：\n"
            "- deep_thinking_task：需要深度分析、多步推理、长文创作、复杂规划、可行性评估或结构化报告。\n"
            "- vertical_agent_task：明确需要使用特定领域智能体（如护肤、法务、财务、招聘、客服、运营、投研、代码、设计等）。\n"
            "- multi_agent_task：需要多个角度、并行、协作或多维度综合处理。\n"
            "- tool_task：需要调用工具（搜索、天气、股票、联网、下载、文件生成、表格整理等）。\n"
            "- general_qa：简单问答、闲聊、知识查询等可直接回答的问题。\n\n"
            "请输出：\n"
            "- intent：上述类别之一\n"
            "- execution_mode：DEEP_THINKING / SINGLE_AGENT_WITH_TOOLS / MULTI_AGENT_PARALLEL / DIRECT_ANSWER\n"
            "- needs_deep_thinking：是否需要深度思考\n"
            "- needs_multi_agent：是否需要多智能体协作\n"
            "- needs_tools：是否需要调用工具\n"
            "- confidence：0 到 1 之间的分类置信度\n"
            "- reason：简短分类理由\n"
        )

    def _build_decision_from_llm(
        self, llm_result: TaskClassificationResult, query: str
    ) -> RoutingDecision:
        intent = (
            llm_result.intent
            if llm_result.intent in self._VALID_INTENTS
            else "general_qa"
        )

        if llm_result.needs_deep_thinking and intent != "deep_thinking_task":
            intent = "deep_thinking_task"

        execution_mode = self._INTENT_TO_EXECUTION_MODE.get(
            intent, ExecutionMode.DIRECT_ANSWER.value
        )
        complexity = self._COMPLEXITY_BY_INTENT.get(intent, "simple")
        recommended_model_tier = self._TIER_BY_COMPLEXITY.get(complexity, "cheap")

        needs_tools = intent != "general_qa"
        needs_agent = intent != "general_qa"
        needs_multi_agent = intent == "multi_agent_task"
        needs_deep_thinking = intent == "deep_thinking_task"

        confidence = max(0.0, min(1.0, float(llm_result.confidence or 0.0)))
        reason = llm_result.reason or f"LLM 分类结果：{intent}"
        reason = f"{reason}（置信度: {confidence:.2f}）"

        return RoutingDecision(
            intent=intent,
            complexity=complexity,
            execution_mode=execution_mode,
            needs_tools=needs_tools,
            needs_agent=needs_agent,
            needs_multi_agent=needs_multi_agent,
            needs_deep_thinking=needs_deep_thinking,
            recommended_model_tier=recommended_model_tier,
            risk_level=RiskLevel.SAFE.value,
            reason=reason,
        )

    def _classify_with_keywords(self, normalized: str) -> RoutingDecision:
        if self._looks_like_vertical_agent_task(normalized):
            return RoutingDecision(
                intent="vertical_agent_task",
                complexity="medium",
                execution_mode=ExecutionMode.SINGLE_AGENT_WITH_TOOLS.value,
                needs_tools=True,
                needs_agent=True,
                recommended_model_tier="balanced",
                risk_level=RiskLevel.SAFE.value,
                reason="用户明确要求使用垂直智能体或问题适合路由到单个专业 Agent",
            )
        if self._contains_any(normalized, self.MULTI_AGENT_KEYWORDS) and self._contains_any(
            normalized, self.TOOL_KEYWORDS
        ):
            return RoutingDecision(
                intent="multi_agent_task",
                complexity="complex",
                execution_mode=ExecutionMode.MULTI_AGENT_PARALLEL.value,
                needs_tools=True,
                needs_agent=True,
                needs_multi_agent=True,
                recommended_model_tier="strong",
                risk_level=RiskLevel.SAFE.value,
                reason="用户请求需要多个 Agent 并行协作",
            )
        if self._contains_any(normalized, self.TOOL_KEYWORDS):
            return RoutingDecision(
                intent="tool_task",
                complexity="medium",
                execution_mode=ExecutionMode.SINGLE_AGENT_WITH_TOOLS.value,
                needs_tools=True,
                needs_agent=True,
                recommended_model_tier="balanced",
                risk_level=RiskLevel.SAFE.value,
                reason="用户请求需要查询、联网、文件或工具类能力",
            )
        return self._build_general_qa_decision("用户问题可由基础模型直接回答")

    @staticmethod
    def _build_general_qa_decision(reason: str) -> RoutingDecision:
        return RoutingDecision(
            intent="general_qa",
            complexity="simple",
            execution_mode=ExecutionMode.DIRECT_ANSWER.value,
            needs_tools=False,
            needs_agent=False,
            recommended_model_tier="cheap",
            risk_level=RiskLevel.SAFE.value,
            reason=reason,
        )

    def _looks_like_vertical_agent_task(self, query: str) -> bool:
        has_agent_hint = self._contains_any(query, self.AGENT_KEYWORDS)
        has_vertical_hint = self._contains_any(query, self.VERTICAL_HINTS)
        return has_agent_hint and has_vertical_hint

    def _contains_high_risk(self, normalized: str) -> bool:
        lowered = normalized.lower()
        return self._contains_any(
            normalized, self.HIGH_RISK_KEYWORDS
        ) or self._contains_any(lowered, self.HIGH_RISK_KEYWORDS)

    @staticmethod
    def _contains_any(query: str, keywords: tuple[str, ...]) -> bool:
        return any(keyword in query for keyword in keywords)

    @staticmethod
    def _normalize(query: str) -> str:
        return (query or "").strip()
