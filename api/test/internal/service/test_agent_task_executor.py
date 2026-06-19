from unittest.mock import MagicMock

from internal.entity.execution_orchestration_entity import TaskPlanItem
from internal.service.agent_task_executor import AgentTaskExecutor


def test_execute_success_returns_expected_dict():
    human_message = MagicMock(name="human_message")
    llm = MagicMock()
    llm.convert_to_human_message.return_value = human_message

    thought1 = MagicMock()
    thought1.answer = "中间答案"
    thought2 = MagicMock()
    thought2.answer = "最终答案"
    thought3 = MagicMock()
    thought3.answer = ""

    agent = MagicMock()
    agent.stream.return_value = iter([thought1, thought2, thought3])

    agent_class = MagicMock(return_value=agent)

    executor = AgentTaskExecutor(
        agent_class=agent_class,
        agent_config={"k": "v"},
        tools=["tool1"],
        llm=llm,
        history=[],
        query="备用查询",
    )

    item = TaskPlanItem(task_id="task-1", title="标题", description="任务描述")
    result = executor.execute(item)

    agent_class.assert_called_once_with({"k": "v"}, ["tool1"])
    llm.convert_to_human_message.assert_called_once_with("任务描述", [])

    stream_input = agent.stream.call_args.args[0]
    assert stream_input["messages"] == [human_message]
    assert stream_input["history"] == []
    assert stream_input["long_term_memory"] == ""
    assert stream_input["user_memory"] == ""

    assert result == {
        "agent_id": "task-1",
        "task_id": "task-1",
        "answer": "最终答案",
        "confidence": 1.0,
        "sources": [],
        "tool_calls": [],
        "warnings": [],
        "errors": [],
        "cost": {},
        "metadata": {"title": "标题"},
    }


def test_execute_exception_returns_error_dict_without_raising():
    agent_class = MagicMock(side_effect=RuntimeError("boom"))
    llm = MagicMock()

    executor = AgentTaskExecutor(
        agent_class=agent_class,
        agent_config=None,
        tools=[],
        llm=llm,
    )

    item = TaskPlanItem(task_id="task-2", title="标题2", description="描述2")
    result = executor.execute(item)

    assert result == {
        "agent_id": "",
        "task_id": "task-2",
        "answer": "",
        "errors": ["agent_execution_failed"],
        "warnings": [],
        "confidence": 0,
    }
