import json
from uuid import uuid4

from internal.entity.execution_orchestration_entity import TaskPlan, TaskPlanItem
from internal.service.executors.multi_agent_executor import MultiAgentExecutor


def _parse(sse_event):
    return json.loads(sse_event.split("data:", 1)[1].strip())


def _item(task_id="t1", depends_on=None):
    return TaskPlanItem(
        task_id=task_id,
        title=task_id,
        description=task_id,
        depends_on=depends_on or [],
        execution_order=0,
        risk_level="safe",
        timeout_seconds=30,
        retry_count=1,
        retry_interval=0.5,
    )


def test_subtask_started_sse_contract():
    plan = TaskPlan(
        original_query="query",
        execution_mode="multi_agent_parallel",
        reason="test",
        aggregation_strategy="summarize",
        items=[_item()],
    )
    event = MultiAgentExecutor._subtask_plan_sse(
        plan,
        str(uuid4()),
        str(uuid4()),
    )
    payload = _parse(event)

    assert set(payload) >= {
        "id",
        "task_id",
        "execution_mode",
        "aggregation_strategy",
        "reason",
        "task_count",
        "items",
    }
    item = payload["items"][0]
    assert set(item) >= {
        "task_id",
        "title",
        "depends_on",
        "execution_order",
        "agent_id",
        "tools",
        "risk_level",
        "timeout_seconds",
        "retry_count",
        "retry_interval",
    }


def test_subtask_running_sse_contract():
    item = _item()
    event = MultiAgentExecutor._subtask_running_sse(
        item,
        str(uuid4()),
        str(uuid4()),
    )
    payload = _parse(event)

    assert payload["task_id"] == "t1"
    assert payload["status"] == "running"
    assert {"task_id", "agent_id", "status", "conversation_id", "message_id"} <= set(payload)


def test_subtask_completed_sse_contract():
    item = _item()
    result = {
        "agent_id": "t1",
        "task_id": "t1",
        "answer": "done",
        "confidence": 0.9,
        "errors": [],
    }
    event = MultiAgentExecutor._subtask_completed_sse(
        item,
        result,
        str(uuid4()),
        str(uuid4()),
    )
    payload = _parse(event)

    assert payload["task_id"] == "t1"
    assert payload["status"] == "completed"
    assert payload["answer_preview"] == "done"
    assert payload["errors"] == []
    assert {"task_id", "agent_id", "status", "answer_preview", "confidence", "errors"} <= set(payload)


def test_agent_message_sse_contract():
    event = MultiAgentExecutor._message_sse(
        "final",
        {
            "summary": "summary",
            "confidence": 0.8,
            "visible_sources": ["a"],
            "user_warnings": ["w"],
        },
        str(uuid4()),
        str(uuid4()),
    )
    payload = _parse(event)

    assert payload["answer"] == "final"
    assert payload["summary"] == "summary"
    assert payload["confidence"] == 0.8
    assert payload["visible_sources"] == ["a"]
    assert payload["user_warnings"] == ["w"]
    assert {"answer", "id", "conversation_id", "message_id"} <= set(payload)
