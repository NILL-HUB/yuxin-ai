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
    complexity: str = Field(
        default="simple",
        description="任务复杂度：complex / medium / simple，与 intent 解耦",
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

    # 深度思考关键词：触发复杂推理/多步规划/长文创作等
    DEEP_THINKING_KEYWORDS = (
        "深度分析",
        "深入分析",
        "深度思考",
        "深度研究",
        "深入研究",
        "调研",
        "深度调研",
        "可行性",
        "可行性分析",
        "可行性评估",
        "架构设计",
        "系统设计",
        "技术方案",
        "方案设计",
        "路线图",
        "规划方案",
        "战略规划",
        "长文",
        "长篇",
        "报告",
        "总结报告",
        "分析报告",
        "调研报告",
        "结构化报告",
        "多步",
        "多步骤",
        "分步骤",
        "详细计划",
        "实施方案",
        "落地",
        "拆解",
        "多轮",
        "评估方案",
        "对比分析",
        "权衡",
        "深度对比",
    )

    TOOL_KEYWORDS = (
        "查询",
        "搜索",
        "查一下",
        "查找",
        "检索",
        "天气",
        "股票",
        "汇率",
        "联网",
        "下载",
        "上传",
        "生成文件",
        "整理成表格",
        "调用",
        "发送邮件",
        "发邮件",
        "发送消息",
        "调用API",
        "调用接口",
        "执行命令",
        "运行脚本",
        # 时间/日期相关（需要调用 time 工具获取实时信息）
        "几点",
        "现在几点",
        "当前时间",
        "现在时间",
        "时间",
        "日期",
        "今天几号",
        "今天是几号",
        "星期几",
        "当前日期",
        "今天是",
    )

    AGENT_KEYWORDS = (
        "智能体",
        "agent",
        "Agent",
        "使用",
        "交给",
        "让",
        "调用",
        "委托",
        "转交",
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
        "医疗",
        "教育",
        "翻译",
        "营销",
        "销售",
        "人事",
        "采购",
    )

    MULTI_AGENT_KEYWORDS = (
        "分别",
        "多个角度",
        "多个视角",
        "同时",
        "并行",
        "协作",
        "协同",
        "综合",
        "多维度",
        "多方面",
        "多源",
        "多角色",
        "分工",
        "联合",
        "汇总",
        "整合",
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
        "complex": "3",
        "medium": "2",
        "simple": "1",
    }

    def classify(self, query: str, *, budget_allowed: bool = True) -> RoutingDecision:
        normalized = self._normalize(query)

        # ① 高风险关键词拦截（最高优先级，安全兜底）
        if self._contains_high_risk(normalized):
            return RoutingDecision(
                intent="high_risk_operation",
                complexity="complex",
                execution_mode=ExecutionMode.REJECT_OR_CONFIRM.value,
                needs_tools=False,
                needs_agent=False,
                recommended_model_tier="3",
                risk_level=RiskLevel.HIGH.value,
                reason="用户请求包含高风险操作，需要拒绝或二次确认",
            )

        # ② 关键词匹配优先（命中即返回，速度快、零成本）
        # 命中明确意图（deep_thinking/vertical/multi_agent/tool）时直接返回
        keyword_decision = self._classify_with_keywords(normalized)
        if keyword_decision.intent != "general_qa":
            return keyword_decision

        # ③ LLM 语义识别兜底（关键词未命中明确意图时调用，处理模糊 query）
        if budget_allowed and self.language_model_service is not None:
            try:
                llm_result = self._classify_with_llm(normalized)
                if llm_result is not None:
                    return self._build_decision_from_llm(llm_result, normalized)
            except Exception as exc:
                # LLM 兜底失败时，记录详细错误（含 query 摘要），降级到 general_qa
                query_preview = normalized[:80]
                logger.warning(
                    "LLM 任务分类失败，降级到 general_qa: query=%r error=%s",
                    query_preview,
                    exc,
                    exc_info=True,
                )

        # ④ 最终兜底：general_qa（关键词 + LLM 均未命中明确意图）
        return keyword_decision

    def _classify_with_llm(self, query: str) -> TaskClassificationResult:
        from internal.service.memory.llm_activity_probe import LLMActivityProbe

        llm = self.language_model_service.get_feature_model("task_classification")
        # 用活跃探针替代固定超时：模型持续产出 token 时不干扰，
        # 仅在 60s 无 chunk 产出（死机）时终止
        return LLMActivityProbe.invoke_structured_with_probe(
            llm,
            TaskClassificationResult,
            self._build_classification_prompt(query),
            feature_key="task_classification",
        )

    @staticmethod
    def _build_classification_prompt(query: str) -> str:
        return (
            "你是一名任务分类专家，负责对用户查询进行路由分类。\n\n"
            "## 输入\n"
            f"用户查询：{query}\n\n"
            "## 分类规则（按优先级匹配，选择最匹配的一项）\n"
            "- deep_thinking_task：需要深度分析、多步推理、长文创作、复杂规划、可行性评估、技术方案设计或结构化报告。\n"
            "  关键信号词：调研、深度分析、可行性、架构设计、路线图、规划方案、报告、多步骤、对比分析、权衡\n"
            "- vertical_agent_task：明确需要使用特定领域智能体（如护肤、法务、财务、招聘、客服、运营、投研、代码、设计、医疗、教育、翻译等）。\n"
            "  关键信号词：智能体、agent、交给、委托 + 垂直领域名词\n"
            "- multi_agent_task：需要多个角度、并行、协作、多维度综合处理，或问题明确包含多个子任务需要不同角色/能力处理。\n"
            "  关键信号词：分别、多个角度、同时、并行、协作、综合、多维度、分工、联合\n"
            "- tool_task：需要调用工具（搜索、天气、股票、汇率、联网、下载、文件生成、表格整理、发送邮件、API 调用、时间/日期查询等）才能给出准确答案。\n"
            "  关键信号词：查询、搜索、联网、下载、调用、发送、生成文件、整理成表格、几点、时间、日期、星期几\n"
            "- general_qa：简单问答、闲聊、知识查询、定义解释等可直接由 LLM 回答的问题，无需工具或深度推理。\n\n"
            "## 复杂度判定（与 intent 解耦）\n"
            "- complex：多步推理、跨领域综合、长文创作、深度分析\n"
            "- medium：单一领域的中等问题、需调用工具、需垂直 Agent\n"
            "- simple：直接问答、闲聊、事实查询\n\n"
            "## few-shot 示例\n"
            '查询："帮我调研一下主流大模型的架构对比，并给出选型建议"\n'
            "输出：intent=deep_thinking_task, complexity=complex, needs_deep_thinking=true, "
            "needs_tools=false, confidence=0.95, reason=\"调研+架构对比+选型建议需要深度分析\"\n\n"
            '查询："查一下北京今天的天气"\n'
            "输出：intent=tool_task, complexity=simple, needs_tools=true, "
            "needs_deep_thinking=false, confidence=0.98, reason=\"需要调用天气工具\"\n\n"
            '查询："现在几点了？"\n'
            "输出：intent=tool_task, complexity=simple, needs_tools=true, "
            "needs_deep_thinking=false, confidence=0.98, reason=\"需要调用时间工具获取当前时间\"\n\n"
            '查询："今天星期几？"\n'
            "输出：intent=tool_task, complexity=simple, needs_tools=true, "
            "needs_deep_thinking=false, confidence=0.97, reason=\"需要调用时间工具获取日期信息\"\n\n"
            '查询："让法务Agent审查这份合同"\n'
            "输出：intent=vertical_agent_task, complexity=medium, needs_tools=true, "
            "needs_deep_thinking=false, confidence=0.95, reason=\"明确委托法务 Agent\"\n\n"
            '查询："分别从财务和运营两个角度分析这次并购"\n'
            "输出：intent=multi_agent_task, complexity=complex, needs_multi_agent=true, "
            "needs_deep_thinking=false, confidence=0.9, reason=\"分别+两个角度+分析需要多 Agent 协作\"\n\n"
            '查询："你好，介绍一下你自己"\n'
            "输出：intent=general_qa, complexity=simple, needs_tools=false, "
            "needs_deep_thinking=false, confidence=0.99, reason=\"闲聊型问答\"\n\n"
            "## 输出要求\n"
            "- intent：上述 5 个类别之一（必须严格匹配枚举值）\n"
            "- execution_mode：DEEP_THINKING / SINGLE_AGENT_WITH_TOOLS / MULTI_AGENT_PARALLEL / DIRECT_ANSWER\n"
            "- complexity：complex / medium / simple\n"
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

        # complexity 与 intent 部分解耦：优先采用 LLM 给出的 complexity，回退到 intent 映射
        # 但 deep_thinking_task / multi_agent_task 语义上必然是 complex，强制下限以保证一致性
        llm_complexity = (getattr(llm_result, "complexity", "") or "").strip().lower()
        if llm_complexity in ("complex", "medium", "simple"):
            complexity = llm_complexity
        else:
            complexity = self._COMPLEXITY_BY_INTENT.get(intent, "simple")

        # 强制复杂度下限：deep_thinking_task / multi_agent_task 至少为 complex
        if intent in ("deep_thinking_task", "multi_agent_task") and complexity != "complex":
            complexity = "complex"

        recommended_model_tier = self._TIER_BY_COMPLEXITY.get(complexity, "1")

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
        # 1. 深度思考关键词命中（最高优先级，仅次于高风险）
        if self._contains_any(normalized, self.DEEP_THINKING_KEYWORDS):
            return RoutingDecision(
                intent="deep_thinking_task",
                complexity="complex",
                execution_mode=ExecutionMode.DEEP_THINKING.value,
                needs_tools=False,
                needs_agent=True,
                needs_deep_thinking=True,
                recommended_model_tier="3",
                risk_level=RiskLevel.SAFE.value,
                reason="用户请求包含深度思考信号词（调研/可行性/架构/方案/报告等）",
            )

        # 2. 垂直 Agent 任务
        if self._looks_like_vertical_agent_task(normalized):
            return RoutingDecision(
                intent="vertical_agent_task",
                complexity="medium",
                execution_mode=ExecutionMode.SINGLE_AGENT_WITH_TOOLS.value,
                needs_tools=True,
                needs_agent=True,
                recommended_model_tier="2",
                risk_level=RiskLevel.SAFE.value,
                reason="用户明确要求使用垂直智能体或问题适合路由到单个专业 Agent",
            )

        # 3. 多 Agent 任务：放宽判定，命中 MULTI_AGENT_KEYWORDS 即可（不再要求同时命中 TOOL_KEYWORDS）
        if self._contains_any(normalized, self.MULTI_AGENT_KEYWORDS):
            return RoutingDecision(
                intent="multi_agent_task",
                complexity="complex",
                execution_mode=ExecutionMode.MULTI_AGENT_PARALLEL.value,
                needs_tools=True,
                needs_agent=True,
                needs_multi_agent=True,
                recommended_model_tier="3",
                risk_level=RiskLevel.SAFE.value,
                reason="用户请求需要多角度/并行/协作处理",
            )

        # 4. 工具任务
        if self._contains_any(normalized, self.TOOL_KEYWORDS):
            return RoutingDecision(
                intent="tool_task",
                complexity="medium",
                execution_mode=ExecutionMode.SINGLE_AGENT_WITH_TOOLS.value,
                needs_tools=True,
                needs_agent=True,
                recommended_model_tier="2",
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
            recommended_model_tier="1",
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
