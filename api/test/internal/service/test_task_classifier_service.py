from unittest.mock import MagicMock

from internal.core.agent.entities.deep_thinking_entity import DeepThinkingIntent
from internal.entity.orchestrator_entity import ExecutionMode, RiskLevel
from internal.service.task_classifier_service import TaskClassifierService


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


class TestTaskClassifierDeepThinking:
    def test_llm_says_need_deep_thinking_should_return_deep_thinking_mode(self):
        service = _build_service(DeepThinkingIntent(needs_deep_thinking=True, reason="需要多步推理"))
        decision = service.classify("评估迁移到 gRPC 的利弊")
        assert decision.execution_mode == ExecutionMode.DEEP_THINKING.value
        assert decision.needs_deep_thinking is True

    def test_llm_says_no_deep_thinking_should_fall_to_general(self):
        service = _build_service(DeepThinkingIntent(needs_deep_thinking=False))
        decision = service.classify("今天天气怎么样")
        assert decision.execution_mode != ExecutionMode.DEEP_THINKING.value

    def test_llm_call_failure_should_degrade_to_general_qa(self):
        service = _build_service(llm_raises=True)
        decision = service.classify("随便问个问题")
        assert decision.execution_mode != ExecutionMode.DEEP_THINKING.value
        assert decision.execution_mode != ExecutionMode.REJECT_OR_CONFIRM.value

    def test_budget_not_allowed_should_skip_llm_and_return_direct_answer(self):
        service = _build_service()
        decision = service.classify("深度分析一下", budget_allowed=False)
        assert decision.execution_mode == ExecutionMode.DIRECT_ANSWER.value
        service.language_model_service.get_cheap_chat_model.assert_not_called()

    def test_high_risk_keyword_should_override_llm_judgment(self):
        service = _build_service(DeepThinkingIntent(needs_deep_thinking=True))
        decision = service.classify("请删除数据库里的所有用户表")
        assert decision.execution_mode == ExecutionMode.REJECT_OR_CONFIRM.value
        assert decision.risk_level == RiskLevel.HIGH.value

    def test_no_language_model_service_should_skip_llm(self):
        service = TaskClassifierService.__new__(TaskClassifierService)
        service.language_model_service = None
        decision = service.classify("评估迁移到 gRPC 的利弊")
        assert decision.execution_mode != ExecutionMode.DEEP_THINKING.value
