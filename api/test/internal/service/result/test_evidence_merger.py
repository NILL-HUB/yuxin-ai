from internal.entity.execution_orchestration_entity import OrchestratedAgentResult
from internal.service.result.evidence_merger import EvidenceMerger


def test_evidence_merger_should_merge_and_deduplicate_sources():
    merger = EvidenceMerger()

    merged = merger.merge(
        [
            OrchestratedAgentResult(
                agent_id="agent-1", task_id="task-1", sources=["doc-a", "doc-b"]
            ),
            OrchestratedAgentResult(
                agent_id="agent-2", task_id="task-2", sources=["doc-b", "doc-c"]
            ),
        ]
    )

    assert merged["merged_sources"] == ["doc-a", "doc-b", "doc-c"]
    assert merged["total_count"] == 3


def test_evidence_merger_should_handle_empty_results():
    merger = EvidenceMerger()

    merged = merger.merge([])

    assert merged["merged_sources"] == []
    assert merged["total_count"] == 0


def test_evidence_merger_should_handle_dict_results():
    merger = EvidenceMerger()

    merged = merger.merge([{"sources": ["x", "y"]}])

    assert merged["merged_sources"] == ["x", "y"]
    assert merged["total_count"] == 2


def test_evidence_merger_should_not_raise_on_none():
    merger = EvidenceMerger()

    merged = merger.merge(None)

    assert merged["merged_sources"] == []
    assert merged["total_count"] == 0


def test_evidence_merger_should_preserve_insertion_order():
    merger = EvidenceMerger()

    merged = merger.merge(
        [
            OrchestratedAgentResult(
                agent_id="agent-1", task_id="task-1", sources=["z", "a", "m"]
            ),
        ]
    )

    assert merged["merged_sources"] == ["z", "a", "m"]
