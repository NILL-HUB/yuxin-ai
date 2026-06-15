from internal.entity.orchestrator_entity import ExecutionMode, RoutingDecision, RiskLevel
from internal.service.orchestrator_service import OrchestratorService
from internal.service.task_classifier_service import TaskClassifierService


def test_simple_question_should_route_to_direct_answer():
    decision = TaskClassifierService().classify("Python 中 list 和 tuple 有什么区别？")

    assert isinstance(decision, RoutingDecision)
    assert decision.intent == "general_qa"
    assert decision.complexity == "simple"
    assert decision.execution_mode == ExecutionMode.DIRECT_ANSWER.value
    assert decision.needs_tools is False
    assert decision.needs_agent is False
    assert decision.needs_multi_agent is False
    assert decision.recommended_model_tier == "cheap"
    assert decision.risk_level == RiskLevel.SAFE.value


def test_vertical_agent_request_should_route_to_single_agent():
    decision = TaskClassifierService().classify("请使用护肤智能体回答我油痘肌该怎么护肤")

    assert decision.intent == "vertical_agent_task"
    assert decision.execution_mode == ExecutionMode.SINGLE_AGENT.value
    assert decision.needs_agent is True
    assert decision.needs_tools is True
    assert decision.needs_multi_agent is False


def test_tool_request_should_mark_needs_tools():
    decision = TaskClassifierService().classify("帮我查询今天北京天气并整理成表格")

    assert decision.intent == "tool_task"
    assert decision.needs_tools is True
    assert decision.execution_mode == ExecutionMode.SINGLE_AGENT.value
    assert decision.reason


def test_high_risk_request_should_require_reject_or_confirm():
    decision = TaskClassifierService().classify("帮我删除数据库所有用户数据")

    assert decision.intent == "high_risk_operation"
    assert decision.risk_level == RiskLevel.HIGH.value
    assert decision.execution_mode == ExecutionMode.REJECT_OR_CONFIRM.value
    assert decision.needs_agent is False


def test_orchestrator_should_fallback_when_classifier_fails():
    class _BrokenClassifier:
        def classify(self, _query):
            raise RuntimeError("boom")

    decision = OrchestratorService(task_classifier_service=_BrokenClassifier()).decide("任意问题")

    assert decision.intent == "fallback"
    assert decision.execution_mode == ExecutionMode.SINGLE_AGENT.value
    assert decision.needs_agent is True
    assert decision.risk_level == RiskLevel.UNKNOWN.value


def test_routing_decision_should_dump_stable_dict():
    decision = RoutingDecision(
        intent="general_qa",
        complexity="simple",
        execution_mode=ExecutionMode.DIRECT_ANSWER.value,
        reason="简单问答",
    )

    dumped = decision.to_dict()

    assert dumped == {
        "intent": "general_qa",
        "complexity": "simple",
        "execution_mode": "direct_answer",
        "needs_tools": False,
        "needs_agent": False,
        "needs_multi_agent": False,
        "recommended_model_tier": "cheap",
        "risk_level": "safe",
        "reason": "简单问答",
    }
