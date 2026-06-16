from internal.entity.execution_orchestration_entity import (
    OrchestratedAgentResult,
)
from internal.service.result_synthesizer_service import ResultSynthesizerService


def _result(**kwargs):
    defaults = {
        "agent_id": "agent-1",
        "task_id": "task-1",
        "answer": "第一条建议。",
        "confidence": 0.8,
        "sources": ["doc-a"],
        "warnings": [],
        "errors": [],
    }
    defaults.update(kwargs)
    return OrchestratedAgentResult.from_dict(defaults)


def test_result_synthesizer_should_merge_results_without_raw_agent_output():
    final = ResultSynthesizerService().synthesize(
        [
            _result(answer="第一条建议。", sources=["doc-a", "doc-b"]),
            _result(
                agent_id="agent-2",
                task_id="task-2",
                answer="第二条建议。",
                confidence=0.6,
                sources=["doc-b", "doc-c"],
            ),
        ]
    )

    assert final == {
        "final_answer": "第一条建议。\n\n第二条建议。",
        "summary": "已整合 2 个 Agent 结果。",
        "confidence": 0.7,
        "visible_sources": ["doc-a", "doc-b", "doc-c"],
        "user_warnings": [],
    }


def test_result_synthesizer_should_turn_failed_results_into_warnings():
    final = ResultSynthesizerService().synthesize(
        [
            _result(answer="成功结果。", confidence=0.9),
            _result(
                task_id="task-2",
                answer="",
                confidence=0,
                errors=["agent_execution_failed"],
                warnings=["fallback:task_failed"],
            ),
        ]
    )

    assert final["final_answer"] == "成功结果。"
    assert final["confidence"] == 0.9
    assert final["user_warnings"] == ["fallback:task_failed"]
    assert "agent_id" not in final
    assert "task_id" not in final


def test_result_synthesizer_should_include_quality_warnings():
    final = ResultSynthesizerService().synthesize(
        [
            _result(answer="建议采用方案 A。", confidence=0.8),
            _result(answer="不建议采用方案 A。", confidence=0.2),
        ]
    )

    assert final["user_warnings"] == [
        "conflict:contradictory_answers",
        "quality:low_confidence",
    ]
    assert final["confidence"] == 0.4


def test_result_synthesizer_should_return_fallback_when_no_valid_result():
    final = ResultSynthesizerService().synthesize(
        [_result(answer="", confidence=0, errors=["agent_execution_failed"])]
    )

    assert final == {
        "final_answer": "当前任务暂时无法完成，请稍后重试或缩小任务范围。",
        "summary": "没有可用的 Agent 结果。",
        "confidence": 0,
        "visible_sources": [],
        "user_warnings": ["fallback:no_valid_agent_result"],
    }
