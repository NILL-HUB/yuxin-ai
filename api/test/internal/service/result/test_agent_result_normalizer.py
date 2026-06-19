from internal.entity.execution_orchestration_entity import OrchestratedAgentResult
from internal.service.result.agent_result_normalizer import AgentResultNormalizer


def test_agent_result_normalizer_should_normalize_dict_into_entity():
    normalizer = AgentResultNormalizer()

    normalized = normalizer.normalize(
        {
            "agent_id": "agent-1",
            "task_id": "task-1",
            "answer": "答案",
            "confidence": 0.5,
            "sources": ["doc-a"],
        }
    )

    assert isinstance(normalized, OrchestratedAgentResult)
    assert normalized.agent_id == "agent-1"
    assert normalized.task_id == "task-1"
    assert normalized.answer == "答案"
    assert normalized.confidence == 0.5
    assert normalized.sources == ["doc-a"]


def test_agent_result_normalizer_should_pass_through_entity_unchanged():
    normalizer = AgentResultNormalizer()
    original = OrchestratedAgentResult(
        agent_id="agent-1",
        task_id="task-1",
        answer="答案",
        confidence=0.8,
        sources=["doc-a"],
        warnings=["w1"],
    )

    normalized = normalizer.normalize(original)

    assert normalized.agent_id == "agent-1"
    assert normalized.confidence == 0.8
    assert normalized.sources == ["doc-a"]
    assert normalized.warnings == ["w1"]


def test_agent_result_normalizer_should_fill_defaults_for_missing_fields():
    normalizer = AgentResultNormalizer()

    normalized = normalizer.normalize({"agent_id": "agent-1"})

    assert normalized.agent_id == "agent-1"
    assert normalized.confidence == 0.0
    assert normalized.sources == []
    assert normalized.warnings == []
    assert normalized.errors == []
    assert normalized.tool_calls == []


def test_agent_result_normalizer_should_coerce_invalid_confidence_to_zero():
    normalizer = AgentResultNormalizer()
    original = OrchestratedAgentResult(
        agent_id="agent-1",
        task_id="task-1",
        answer="答案",
        confidence="invalid",
    )

    normalized = normalizer.normalize(original)

    assert normalized.confidence == 0.0


def test_agent_result_normalizer_should_return_default_on_invalid_input():
    normalizer = AgentResultNormalizer()

    normalized = normalizer.normalize("invalid")

    assert normalized.agent_id == ""
    assert normalized.confidence == 0.0
    assert normalized.sources == []
