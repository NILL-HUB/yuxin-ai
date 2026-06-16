from internal.entity.execution_orchestration_entity import (
    OrchestratedAgentResult,
)
from internal.service.result_quality_checker_service import ResultQualityCheckerService


def _result(**kwargs):
    defaults = {
        "agent_id": "agent-1",
        "task_id": "task-1",
        "answer": "建议采用方案 A。",
        "confidence": 0.8,
        "warnings": [],
        "metadata": {"agent_config": "internal"},
    }
    defaults.update(kwargs)
    return OrchestratedAgentResult.from_dict(defaults)


def test_quality_checker_should_detect_conflicting_answers():
    warnings = ResultQualityCheckerService().check(
        [
            _result(answer="建议采用方案 A。"),
            _result(task_id="task-2", answer="不建议采用方案 A。"),
        ]
    )

    assert warnings == ["conflict:contradictory_answers"]


def test_quality_checker_should_warn_for_low_confidence_and_high_risk():
    warnings = ResultQualityCheckerService().check(
        [
            _result(
                confidence=0.2,
                warnings=["high_risk_requires_confirmation"],
            )
        ]
    )

    assert warnings == [
        "quality:low_confidence",
        "high_risk_requires_confirmation",
    ]


def test_quality_checker_should_not_leak_internal_metadata():
    warnings = ResultQualityCheckerService().check([_result()])

    assert "agent_config" not in str(warnings)
