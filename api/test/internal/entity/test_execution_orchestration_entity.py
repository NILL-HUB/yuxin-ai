from internal.entity.execution_orchestration_entity import (
    OrchestratedAgentResult,
    TaskPlan,
    TaskPlanItem,
)


def test_task_plan_item_should_normalize_defaults():
    item = TaskPlanItem.from_dict(
        {
            "task_id": " task-1 ",
            "title": " Research ",
            "description": " Collect evidence ",
            "agent_pool": " research ",
            "required_capabilities": ["search", "search", "summarize"],
            "depends_on": ["task-0", "task-0"],
            "execution_order": -1,
            "risk_level": "invalid",
        }
    )

    assert item.task_id == "task-1"
    assert item.title == "Research"
    assert item.description == "Collect evidence"
    assert item.agent_pool == "research"
    assert item.required_capabilities == ["search", "summarize"]
    assert item.depends_on == ["task-0"]
    assert item.execution_order == 0
    assert item.risk_level == "safe"


def test_task_plan_should_dump_summary_without_internal_details():
    plan = TaskPlan(
        original_query="生成市场研究和前端方案",
        execution_mode="multi_agent_parallel",
        reason="complex_multi_domain",
        items=[
            TaskPlanItem(
                task_id="task-1",
                title="研究",
                description="市场研究",
                agent_pool="research",
            )
        ],
    )

    assert plan.to_summary() == {
        "execution_mode": "multi_agent_parallel",
        "reason": "complex_multi_domain",
        "task_count": 1,
        "items": [
            {
                "task_id": "task-1",
                "title": "研究",
                "agent_pool": "research",
                "execution_order": 0,
                "risk_level": "safe",
            }
        ],
    }


def test_agent_result_should_normalize_confidence_and_hide_internal_metadata():
    result = OrchestratedAgentResult.from_dict(
        {
            "agent_id": "agent-1",
            "task_id": "task-1",
            "answer": "最终建议",
            "confidence": 1.5,
            "sources": ["doc-a", "doc-a", "doc-b"],
            "tool_calls": [
                {"name": "search", "arguments": {"secret": "token", "q": "x"}},
            ],
            "warnings": ["低置信度"],
            "errors": [],
            "cost": {"credits": 3},
            "metadata": {"raw_prompt": "internal"},
        }
    )

    assert result.confidence == 1
    assert result.sources == ["doc-a", "doc-b"]
    assert result.to_user_safe_dict() == {
        "answer": "最终建议",
        "confidence": 1,
        "sources": ["doc-a", "doc-b"],
        "tool_calls": [{"name": "search"}],
        "warnings": ["低置信度"],
        "errors": [],
        "cost": {"credits": 3},
    }
