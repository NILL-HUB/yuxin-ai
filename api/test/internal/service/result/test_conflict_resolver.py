from internal.entity.execution_orchestration_entity import OrchestratedAgentResult
from internal.service.result.conflict_resolver import ConflictResolver


def test_conflict_resolver_should_detect_conflict_pairs():
    resolver = ConflictResolver()

    result = resolver.resolve(
        {
            "results": [
                OrchestratedAgentResult(
                    agent_id="agent-1", task_id="task-1", answer="应该使用方案 A"
                ),
                OrchestratedAgentResult(
                    agent_id="agent-2", task_id="task-2", answer="不应该使用方案 A"
                ),
            ]
        }
    )

    assert result["conflicts"] == ["conflict:agent-1_vs_agent-2:应该/不应该"]
    assert result["resolved"] is False
    assert result["resolution_strategy"] == "requires_manual_review"


def test_conflict_resolver_should_return_empty_when_no_conflict():
    resolver = ConflictResolver()

    result = resolver.resolve(
        {
            "results": [
                OrchestratedAgentResult(
                    agent_id="agent-1", task_id="task-1", answer="方案 A 可行"
                ),
                OrchestratedAgentResult(
                    agent_id="agent-2", task_id="task-2", answer="方案 B 也可行"
                ),
            ]
        }
    )

    assert result["conflicts"] == []
    assert result["resolved"] is True
    assert result["resolution_strategy"] == "none"


def test_conflict_resolver_should_return_empty_for_single_result():
    resolver = ConflictResolver()

    result = resolver.resolve(
        {
            "results": [
                OrchestratedAgentResult(
                    agent_id="agent-1", task_id="task-1", answer="应该使用方案 A"
                ),
            ]
        }
    )

    assert result["conflicts"] == []


def test_conflict_resolver_should_support_dict_results():
    resolver = ConflictResolver()

    result = resolver.resolve(
        {
            "results": [
                {"agent_id": "a1", "answer": "推荐方案 A"},
                {"agent_id": "a2", "answer": "不推荐方案 A"},
            ]
        }
    )

    assert result["conflicts"] == ["conflict:a1_vs_a2:推荐/不推荐"]


def test_conflict_resolver_should_not_raise_on_invalid_input():
    resolver = ConflictResolver()

    result = resolver.resolve(None)

    assert result["conflicts"] == []
    assert result["resolved"] is True
    assert result["resolution_strategy"] == "none"
