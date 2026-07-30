from unittest.mock import MagicMock

from internal.entity.orchestrator_entity import ExecutionMode, RiskLevel
from internal.service.task_classifier_service import (
    TaskClassificationResult,
    TaskClassifierService,
)


def _build_service(llm_response=None, llm_raises=False):
    service = TaskClassifierService.__new__(TaskClassifierService)
    service.language_model_service = MagicMock()
    mock_structured = MagicMock()
    mock_llm = MagicMock()
    mock_llm.with_structured_output.return_value = mock_structured
    if llm_raises:
        mock_structured.invoke.side_effect = RuntimeError("timeout")
    elif llm_response is not None:
        mock_structured.invoke.return_value = llm_response
    service.language_model_service.get_cheap_chat_model.return_value = mock_llm
    return service


class TestTaskClassifierHighRiskIntercept:
    def test_high_risk_keyword_should_intercept_before_llm(self):
        service = _build_service(
            TaskClassificationResult(
                intent="general_qa", execution_mode="DIRECT_ANSWER", confidence=0.9
            )
        )
        decision = service.classify("请删除数据库里的所有用户表")
        assert decision.intent == "high_risk_operation"
        assert decision.execution_mode == ExecutionMode.REJECT_OR_CONFIRM.value
        assert decision.risk_level == RiskLevel.HIGH.value
        assert decision.needs_agent is False
        service.language_model_service.get_cheap_chat_model.assert_not_called()

    def test_high_risk_keyword_case_insensitive(self):
        service = _build_service()
        decision = service.classify("DROP TABLE users")
        assert decision.execution_mode == ExecutionMode.REJECT_OR_CONFIRM.value
        assert decision.risk_level == RiskLevel.HIGH.value

    def test_high_risk_keyword_rm_rf(self):
        service = _build_service()
        decision = service.classify("执行 rm -rf / 删除一切")
        assert decision.execution_mode == ExecutionMode.REJECT_OR_CONFIRM.value


class TestTaskClassifierLLMDriven:
    def test_llm_deep_thinking_should_route_to_deep_thinking(self):
        service = _build_service(
            TaskClassificationResult(
                intent="deep_thinking_task",
                execution_mode="DEEP_THINKING",
                needs_deep_thinking=True,
                needs_tools=True,
                confidence=0.9,
                reason="需要多步推理与可行性评估",
            )
        )
        decision = service.classify("评估迁移到 gRPC 的利弊并给出迁移计划")
        assert decision.intent == "deep_thinking_task"
        assert decision.execution_mode == ExecutionMode.DEEP_THINKING.value
        assert decision.needs_deep_thinking is True
        assert decision.complexity == "complex"
        assert decision.recommended_model_tier == "strong"

    def test_llm_vertical_agent_should_route_to_single_agent(self):
        service = _build_service(
            TaskClassificationResult(
                intent="vertical_agent_task",
                execution_mode="SINGLE_AGENT_WITH_TOOLS",
                needs_tools=True,
                confidence=0.85,
                reason="护肤领域智能体",
            )
        )
        decision = service.classify("油痘肌怎么护肤")
        assert decision.intent == "vertical_agent_task"
        assert decision.execution_mode == ExecutionMode.SINGLE_AGENT_WITH_TOOLS.value
        assert decision.needs_agent is True
        assert decision.needs_tools is True
        assert decision.needs_multi_agent is False

    def test_llm_multi_agent_should_route_to_parallel(self):
        service = _build_service(
            TaskClassificationResult(
                intent="multi_agent_task",
                execution_mode="MULTI_AGENT_PARALLEL",
                needs_multi_agent=True,
                needs_tools=True,
                confidence=0.8,
            )
        )
        decision = service.classify("从多个角度分析市场并综合结论")
        assert decision.intent == "multi_agent_task"
        assert decision.execution_mode == ExecutionMode.MULTI_AGENT_PARALLEL.value
        assert decision.needs_multi_agent is True

    def test_llm_tool_task_should_route_to_single_agent_with_tools(self):
        service = _build_service(
            TaskClassificationResult(
                intent="tool_task",
                execution_mode="SINGLE_AGENT_WITH_TOOLS",
                needs_tools=True,
                confidence=0.88,
            )
        )
        decision = service.classify("查一下北京天气")
        assert decision.intent == "tool_task"
        assert decision.execution_mode == ExecutionMode.SINGLE_AGENT_WITH_TOOLS.value
        assert decision.needs_tools is True

    def test_llm_general_qa_should_route_to_direct_answer(self):
        service = _build_service(
            TaskClassificationResult(
                intent="general_qa",
                execution_mode="DIRECT_ANSWER",
                confidence=0.95,
                reason="简单问答",
            )
        )
        decision = service.classify("你好")
        assert decision.intent == "general_qa"
        assert decision.execution_mode == ExecutionMode.DIRECT_ANSWER.value
        assert decision.needs_tools is False
        assert decision.needs_agent is False
        assert decision.complexity == "simple"
        assert decision.recommended_model_tier == "cheap"

    def test_llm_needs_deep_thinking_flag_overrides_intent(self):
        service = _build_service(
            TaskClassificationResult(
                intent="tool_task",
                execution_mode="SINGLE_AGENT_WITH_TOOLS",
                needs_deep_thinking=True,
                needs_tools=True,
                confidence=0.7,
            )
        )
        # query 不含工具/agent 关键词，确保走 LLM 路径验证 needs_deep_thinking 覆盖逻辑
        decision = service.classify("评估迁移到 gRPC 的利弊并给出迁移计划")
        assert decision.intent == "deep_thinking_task"
        assert decision.execution_mode == ExecutionMode.DEEP_THINKING.value
        assert decision.needs_deep_thinking is True

    def test_llm_invalid_intent_falls_back_to_general_qa(self):
        service = _build_service(
            TaskClassificationResult(
                intent="unknown_intent",
                execution_mode="DIRECT_ANSWER",
                confidence=0.3,
            )
        )
        decision = service.classify("随便问个问题")
        assert decision.intent == "general_qa"
        assert decision.execution_mode == ExecutionMode.DIRECT_ANSWER.value


class TestTaskClassifierConfidence:
    def test_confidence_should_be_recorded_in_reason(self):
        service = _build_service(
            TaskClassificationResult(
                intent="general_qa",
                execution_mode="DIRECT_ANSWER",
                confidence=0.92,
                reason="闲聊",
            )
        )
        decision = service.classify("在吗")
        assert "0.92" in decision.reason

    def test_confidence_above_one_should_be_clamped(self):
        service = _build_service(
            TaskClassificationResult(
                intent="general_qa",
                execution_mode="DIRECT_ANSWER",
                confidence=1.5,
            )
        )
        decision = service.classify("在吗")
        assert "1.00" in decision.reason

    def test_confidence_below_zero_should_be_clamped(self):
        service = _build_service(
            TaskClassificationResult(
                intent="general_qa",
                execution_mode="DIRECT_ANSWER",
                confidence=-0.3,
            )
        )
        decision = service.classify("在吗")
        assert "0.00" in decision.reason


class TestTaskClassifierFallback:
    def test_llm_failure_should_degrade_to_tool_keywords(self):
        service = _build_service(llm_raises=True)
        decision = service.classify("帮我查询今天北京天气并整理成表格")
        assert decision.intent == "tool_task"
        assert decision.execution_mode == ExecutionMode.SINGLE_AGENT_WITH_TOOLS.value

    def test_llm_failure_should_degrade_to_vertical_keyword(self):
        service = _build_service(llm_raises=True)
        decision = service.classify("请使用护肤智能体回答我油痘肌该怎么护肤")
        assert decision.intent == "vertical_agent_task"
        assert decision.execution_mode == ExecutionMode.SINGLE_AGENT_WITH_TOOLS.value

    def test_llm_failure_should_degrade_to_general_qa(self):
        service = _build_service(llm_raises=True)
        decision = service.classify("Python 中 list 和 tuple 有什么区别？")
        assert decision.intent == "general_qa"
        assert decision.execution_mode == ExecutionMode.DIRECT_ANSWER.value
        assert decision.execution_mode != ExecutionMode.REJECT_OR_CONFIRM.value


class TestTaskClassifierBudget:
    def test_budget_not_allowed_should_skip_llm_and_use_keywords(self):
        service = _build_service(
            TaskClassificationResult(
                intent="deep_thinking_task",
                execution_mode="DEEP_THINKING",
                confidence=0.9,
            )
        )
        decision = service.classify("帮我查询今天天气", budget_allowed=False)
        service.language_model_service.get_cheap_chat_model.assert_not_called()
        assert decision.intent == "tool_task"
        assert decision.execution_mode == ExecutionMode.SINGLE_AGENT_WITH_TOOLS.value

    def test_budget_not_allowed_general_query_returns_direct_answer(self):
        service = _build_service(
            TaskClassificationResult(
                intent="deep_thinking_task",
                execution_mode="DEEP_THINKING",
            )
        )
        # 选择一个语义上需要深度思考但不命中关键词的 query，验证预算控制下跳过 LLM 降级为 general_qa
        decision = service.classify("评估迁移到 gRPC 的利弊", budget_allowed=False)
        service.language_model_service.get_cheap_chat_model.assert_not_called()
        assert decision.execution_mode == ExecutionMode.DIRECT_ANSWER.value

    def test_no_language_model_service_should_degrade_to_keywords(self):
        service = TaskClassifierService.__new__(TaskClassifierService)
        service.language_model_service = None
        decision = service.classify("帮我查询今天北京天气并整理成表格")
        assert decision.intent == "tool_task"
        assert decision.execution_mode == ExecutionMode.SINGLE_AGENT_WITH_TOOLS.value


class TestTaskClassifierKeywordFirst:
    """验证关键词优先策略：命中明确意图时跳过 LLM 调用，未命中才走 LLM 兜底。"""

    def test_tool_keyword_hit_should_skip_llm_call(self):
        """工具关键词命中时直接返回，不调用 LLM（节省成本与延迟）。"""
        service = _build_service(
            TaskClassificationResult(
                intent="general_qa",
                execution_mode="DIRECT_ANSWER",
                confidence=0.9,
            )
        )
        decision = service.classify("帮我查询今天北京天气")
        assert decision.intent == "tool_task"
        assert decision.execution_mode == ExecutionMode.SINGLE_AGENT_WITH_TOOLS.value
        # 关键词命中明确意图，LLM 不应被调用
        service.language_model_service.get_cheap_chat_model.assert_not_called()

    def test_vertical_agent_keyword_hit_should_skip_llm_call(self):
        """垂直领域 + agent 关键词同时命中时直接返回，不调用 LLM。"""
        service = _build_service(
            TaskClassificationResult(
                intent="general_qa",
                execution_mode="DIRECT_ANSWER",
                confidence=0.9,
            )
        )
        decision = service.classify("请使用护肤智能体回答我油痘肌该怎么护肤")
        assert decision.intent == "vertical_agent_task"
        service.language_model_service.get_cheap_chat_model.assert_not_called()

    def test_multi_agent_keyword_hit_should_skip_llm_call(self):
        """多 agent + tool 关键词同时命中时直接返回，不调用 LLM。"""
        service = _build_service(
            TaskClassificationResult(
                intent="general_qa",
                execution_mode="DIRECT_ANSWER",
                confidence=0.9,
            )
        )
        decision = service.classify("分别从多个角度搜索并综合分析市场趋势")
        assert decision.intent == "multi_agent_task"
        assert decision.execution_mode == ExecutionMode.MULTI_AGENT_PARALLEL.value
        service.language_model_service.get_cheap_chat_model.assert_not_called()

    def test_keyword_miss_should_fallback_to_llm(self):
        """关键词未命中明确意图（general_qa）时走 LLM 兜底。"""
        service = _build_service(
            TaskClassificationResult(
                intent="deep_thinking_task",
                execution_mode="DEEP_THINKING",
                needs_deep_thinking=True,
                confidence=0.85,
                reason="需要深度分析",
            )
        )
        decision = service.classify("评估迁移到 gRPC 的利弊并给出迁移计划")
        assert decision.intent == "deep_thinking_task"
        # 关键词未命中，LLM 应被调用
        service.language_model_service.get_cheap_chat_model.assert_called_once()

    def test_general_qa_keyword_miss_llm_returns_general_should_not_call_llm_again(self):
        """关键词未命中 + LLM 也返回 general_qa，应直接返回（不重复调用）。"""
        service = _build_service(
            TaskClassificationResult(
                intent="general_qa",
                execution_mode="DIRECT_ANSWER",
                confidence=0.95,
            )
        )
        decision = service.classify("你好")
        assert decision.intent == "general_qa"
        assert decision.execution_mode == ExecutionMode.DIRECT_ANSWER.value
        service.language_model_service.get_cheap_chat_model.assert_called_once()
