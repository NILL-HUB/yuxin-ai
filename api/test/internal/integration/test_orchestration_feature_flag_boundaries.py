from internal.entity.orchestrator_entity import ExecutionMode
from internal.service.orchestrator_service import (
    OrchestratorService,
    TaskClassifierService,
)


class _DisabledFlags:
    def __init__(self, disabled_codes):
        self.disabled_codes = set(disabled_codes)

    def is_enabled(self, code):
        return code not in self.disabled_codes


def test_disabled_orchestrator_should_return_user_safe_fallback():
    service = OrchestratorService(
        task_classifier_service=TaskClassifierService(),
        feature_flag_service=_DisabledFlags(["ENABLE_ORCHESTRATOR"]),
    )

    decision = service.decide("帮我执行一个复杂任务")
    payload = decision.to_dict()

    assert decision.execution_mode == ExecutionMode.DIRECT_ANSWER.value
    assert payload["reason"] == "feature_flag_disabled"
    assert "raw_prompt" not in str(payload)
    assert "api_key" not in str(payload)
    assert "secret" not in str(payload)


def test_disabled_multi_agent_should_downgrade_complex_task():
    service = OrchestratorService(
        task_classifier_service=TaskClassifierService(),
        feature_flag_service=_DisabledFlags(["ENABLE_MULTI_AGENT_EXECUTION"]),
    )

    decision = service.decide("帮我分析市场、竞品和技术路线")

    assert decision.needs_multi_agent is False
    assert decision.execution_mode != ExecutionMode.MULTI_AGENT.value


def test_disabled_agent_and_tool_routing_should_skip_subsets():
    service = OrchestratorService(
        task_classifier_service=TaskClassifierService(),
        feature_flag_service=_DisabledFlags([
            "ENABLE_AGENT_METADATA_ROUTING",
            "ENABLE_TOOL_POOL_RETRIEVAL",
        ]),
    )

    decision = service.decide("帮我查询资料并生成总结")

    assert decision.agent_subset["selection_reason"] == "feature_flag_disabled"
    assert decision.tool_subset["selection_reason"] == "feature_flag_disabled"
