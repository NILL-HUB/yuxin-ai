from internal.entity.orchestrator_entity import (
    ExecutionMode,
    RequestContext,
    RiskLevel,
    RoutingDecision,
)
from internal.service.model_assignment_policy_service import ModelAssignmentPolicy


def _decision(execution_mode, complexity="simple", risk=RiskLevel.SAFE.value, tier="cheap"):
    return RoutingDecision(
        intent="test",
        complexity=complexity,
        execution_mode=execution_mode,
        recommended_model_tier=tier,
        risk_level=risk,
    )


def test_assign_should_force_strong_for_deep_thinking_mode():
    decision = _decision(ExecutionMode.DEEP_THINKING.value, tier="cheap")

    assert ModelAssignmentPolicy().assign(decision) == "strong"


def test_assign_should_force_strong_for_multi_agent_parallel():
    decision = _decision(ExecutionMode.MULTI_AGENT_PARALLEL.value, tier="standard")

    assert ModelAssignmentPolicy().assign(decision) == "strong"


def test_assign_should_force_strong_for_high_risk_reject_or_confirm():
    decision = _decision(
        ExecutionMode.REJECT_OR_CONFIRM.value,
        complexity="complex",
        risk=RiskLevel.HIGH.value,
        tier="cheap",
    )

    assert ModelAssignmentPolicy().assign(decision) == "strong"


def test_assign_should_use_standard_for_medium_complexity_tool_task():
    decision = _decision(
        ExecutionMode.SINGLE_AGENT_WITH_TOOLS.value,
        complexity="medium",
        risk=RiskLevel.SAFE.value,
        tier="cheap",
    )

    assert ModelAssignmentPolicy().assign(decision) == "standard"


def test_assign_should_use_cheap_for_simple_direct_answer():
    decision = _decision(ExecutionMode.DIRECT_ANSWER.value, complexity="simple", tier="cheap")

    assert ModelAssignmentPolicy().assign(decision) == "cheap"


def test_assign_should_upgrade_to_strong_when_context_enables_deep_thinking():
    decision = _decision(ExecutionMode.SINGLE_AGENT.value, complexity="simple", tier="cheap")
    ctx = RequestContext(query="q", enable_deep_thinking=True)

    assert ModelAssignmentPolicy().assign(decision, ctx) == "strong"


def test_assign_should_upgrade_unknown_risk_to_standard_at_minimum():
    decision = _decision(
        ExecutionMode.DIRECT_ANSWER.value,
        complexity="simple",
        risk=RiskLevel.UNKNOWN.value,
        tier="cheap",
    )

    assert ModelAssignmentPolicy().assign(decision) == "standard"


def test_assign_should_not_downgrade_classifier_strong_tier():
    decision = _decision(ExecutionMode.SINGLE_AGENT.value, complexity="simple", tier="strong")

    assert ModelAssignmentPolicy().assign(decision) == "strong"
