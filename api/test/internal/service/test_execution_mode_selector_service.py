from internal.entity.orchestrator_entity import ExecutionMode, RiskLevel
from internal.service.execution_mode_selector_service import ExecutionModeSelectorService


def _selector():
    return ExecutionModeSelectorService()


def test_high_risk_should_always_select_reject_or_confirm():
    mode = _selector().select(risk_level=RiskLevel.HIGH.value, needs_deep_thinking=True)
    assert mode == ExecutionMode.REJECT_OR_CONFIRM.value


def test_deep_thinking_keyword_should_select_deep_thinking():
    mode = _selector().select(needs_deep_thinking=True)
    assert mode == ExecutionMode.DEEP_THINKING.value


def test_deep_thinking_requested_flag_should_select_deep_thinking():
    mode = _selector().select(deep_thinking_requested=True)
    assert mode == ExecutionMode.DEEP_THINKING.value


def test_multi_agent_with_multiple_pools_should_select_parallel():
    mode = _selector().select(needs_multi_agent=True, available_pool_count=3)
    assert mode == ExecutionMode.MULTI_AGENT_PARALLEL.value


def test_multi_agent_with_single_pool_should_select_sequential():
    mode = _selector().select(needs_multi_agent=True, available_pool_count=1)
    assert mode == ExecutionMode.MULTI_AGENT_SEQUENTIAL.value


def test_multi_agent_with_zero_pools_should_select_sequential():
    mode = _selector().select(needs_multi_agent=True, available_pool_count=0)
    assert mode == ExecutionMode.MULTI_AGENT_SEQUENTIAL.value


def test_tools_and_agent_should_select_single_agent_with_tools():
    mode = _selector().select(needs_tools=True, needs_agent=True)
    assert mode == ExecutionMode.SINGLE_AGENT_WITH_TOOLS.value


def test_images_with_agent_should_select_single_agent_with_tools():
    mode = _selector().select(image_count=2, needs_agent=True)
    assert mode == ExecutionMode.SINGLE_AGENT_WITH_TOOLS.value


def test_agent_only_should_select_single_agent():
    mode = _selector().select(needs_agent=True)
    assert mode == ExecutionMode.SINGLE_AGENT.value


def test_default_should_return_preliminary_mode():
    mode = _selector().select(preliminary_mode=ExecutionMode.DIRECT_ANSWER.value)
    assert mode == ExecutionMode.DIRECT_ANSWER.value


def test_priority_high_risk_overrides_deep_thinking():
    mode = _selector().select(
        risk_level=RiskLevel.HIGH.value,
        needs_deep_thinking=True,
        deep_thinking_requested=True,
    )
    assert mode == ExecutionMode.REJECT_OR_CONFIRM.value


def test_priority_deep_thinking_overrides_multi_agent():
    mode = _selector().select(
        needs_deep_thinking=True,
        needs_multi_agent=True,
        available_pool_count=5,
    )
    assert mode == ExecutionMode.DEEP_THINKING.value
