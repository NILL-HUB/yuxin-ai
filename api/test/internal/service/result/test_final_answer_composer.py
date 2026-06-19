from internal.entity.execution_orchestration_entity import OrchestratedAgentResult
from internal.service.result.final_answer_composer import FinalAnswerComposer


def test_final_answer_composer_should_merge_answers_with_double_newline():
    composer = FinalAnswerComposer()

    composed = composer.compose(
        {"merged_sources": []},
        {"conflicts": []},
        [
            OrchestratedAgentResult(
                agent_id="agent-1", task_id="task-1", answer="第一条建议。", confidence=0.8
            ),
            OrchestratedAgentResult(
                agent_id="agent-2", task_id="task-2", answer="第二条建议。", confidence=0.6
            ),
        ],
    )

    assert composed["final_answer"] == "第一条建议。\n\n第二条建议。"
    assert composed["confidence"] == 0.7


def test_final_answer_composer_should_reduce_confidence_on_low_confidence():
    composer = FinalAnswerComposer()

    composed = composer.compose(
        {},
        {"conflicts": []},
        [
            OrchestratedAgentResult(
                agent_id="agent-1", task_id="task-1", answer="建议 A", confidence=0.8
            ),
            OrchestratedAgentResult(
                agent_id="agent-2", task_id="task-2", answer="建议 B", confidence=0.2
            ),
        ],
    )

    assert composed["confidence"] == 0.4


def test_final_answer_composer_should_reduce_confidence_on_conflicts():
    composer = FinalAnswerComposer()

    composed = composer.compose(
        {},
        {"conflicts": ["conflict:agent-1_vs_agent-2:应该/不应该"]},
        [
            OrchestratedAgentResult(
                agent_id="agent-1", task_id="task-1", answer="应该", confidence=0.8
            ),
            OrchestratedAgentResult(
                agent_id="agent-2", task_id="task-2", answer="不应该", confidence=0.8
            ),
        ],
    )

    assert composed["confidence"] == 0.75
    assert "conflict:agent-1_vs_agent-2:应该/不应该" in composed["warnings"]


def test_final_answer_composer_should_deduplicate_identical_answers():
    composer = FinalAnswerComposer()

    composed = composer.compose(
        {},
        {"conflicts": []},
        [
            OrchestratedAgentResult(
                agent_id="agent-1", task_id="task-1", answer="相同答案。", confidence=0.8
            ),
            OrchestratedAgentResult(
                agent_id="agent-2", task_id="task-2", answer="相同答案。", confidence=0.8
            ),
        ],
    )

    assert composed["final_answer"] == "相同答案。"


def test_final_answer_composer_should_not_raise_on_empty_results():
    composer = FinalAnswerComposer()

    composed = composer.compose({}, {"conflicts": []}, [])

    assert composed["final_answer"] == ""
    assert composed["confidence"] == 0.0
    assert composed["warnings"] == []
