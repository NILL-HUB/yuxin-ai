import logging
from dataclasses import dataclass

from injector import inject

from internal.core.agent.entities.deep_thinking_entity import DeepThinkingIntent
from internal.entity.orchestrator_entity import ExecutionMode, RiskLevel, RoutingDecision
from internal.service.language_model_service import LanguageModelService


logger = logging.getLogger(__name__)


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

    def classify(self, query: str, *, budget_allowed: bool = True) -> RoutingDecision:
        normalized = (query or "").strip()
        lowered = normalized.lower()
        if self._contains_any(normalized, self.HIGH_RISK_KEYWORDS) or self._contains_any(
            lowered, self.HIGH_RISK_KEYWORDS
        ):
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

        if budget_allowed and self._needs_deep_thinking(normalized):
            return RoutingDecision(
                intent="deep_thinking_task",
                complexity="complex",
                execution_mode=ExecutionMode.DEEP_THINKING.value,
                needs_tools=True,
                needs_agent=True,
                needs_deep_thinking=True,
                recommended_model_tier="strong",
                risk_level=RiskLevel.SAFE.value,
                reason="LLM 判断用户请求需要深度思考和多阶段推理",
            )

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
        return RoutingDecision(
            intent="general_qa",
            complexity="simple",
            execution_mode=ExecutionMode.DIRECT_ANSWER.value,
            needs_tools=False,
            needs_agent=False,
            recommended_model_tier="cheap",
            risk_level=RiskLevel.SAFE.value,
            reason="用户问题可由基础模型直接回答",
        )

    def _needs_deep_thinking(self, query: str) -> bool:
        if not query or self.language_model_service is None:
            return False
        try:
            intent = self._classify_deep_thinking_intent(query)
            return bool(intent.needs_deep_thinking)
        except Exception:
            logger.warning("LLM 深度思考意图判断失败，降级为非深度思考", exc_info=True)
            return False

    def _classify_deep_thinking_intent(self, query: str) -> DeepThinkingIntent:
        llm = self.language_model_service.get_cheap_chat_model()
        structured = llm.with_structured_output(DeepThinkingIntent)
        return structured.invoke(self._build_intent_prompt(query))

    @staticmethod
    def _build_intent_prompt(query: str) -> str:
        return (
            "判断以下用户问题是否需要深度思考（多步推理、调研、对比分析、"
            "可行性评估、结构化报告生成、长文摘要提炼等复杂认知任务）。\n\n"
            f"用户问题：{query}\n\n"
            "请返回 needs_deep_thinking（布尔）和 reason（简短理由）。"
        )

    def _looks_like_vertical_agent_task(self, query: str) -> bool:
        has_agent_hint = self._contains_any(query, self.AGENT_KEYWORDS)
        has_vertical_hint = self._contains_any(query, self.VERTICAL_HINTS)
        return has_agent_hint and has_vertical_hint

    @staticmethod
    def _contains_any(query: str, keywords: tuple[str, ...]) -> bool:
        return any(keyword in query for keyword in keywords)
