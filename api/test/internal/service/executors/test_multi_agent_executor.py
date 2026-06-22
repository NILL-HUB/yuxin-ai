import json
from types import SimpleNamespace
from unittest.mock import MagicMock, patch
from uuid import uuid4

from langchain_core.messages import AIMessage

from internal.core.agent.entities.queue_entity import QueueEvent
from internal.entity.execution_orchestration_entity import (
    OrchestratedAgentResult,
    TaskPlan,
    TaskPlanItem,
)
from internal.service.executors.multi_agent_executor import MultiAgentExecutor


def _parse_payload(sse_event):
    return json.loads(sse_event.split("data:", 1)[1].strip())


def _account():
    return SimpleNamespace(id=uuid4())


def _conv():
    return SimpleNamespace(id=uuid4())


def _msg():
    return SimpleNamespace(id=uuid4())


def _plan(items, strategy="concat", mode="multi_agent_parallel"):
    return TaskPlan(
        original_query="多智能体任务",
        items=items,
        execution_mode=mode,
        aggregation_strategy=strategy,
    )


def _build_executor(plan):
    task_decomposer = MagicMock()
    task_decomposer.decompose.return_value = plan
    task_decomposer.language_model_service = MagicMock()
    db = MagicMock(name="db")
    return MultiAgentExecutor(db=db, task_decomposer=task_decomposer), task_decomposer


def _run_execute(executor, *, routing_decision=None, llm=None, tools=None, history=None):
    return list(executor.execute(
        query="多智能体任务",
        account=_account(),
        conversation=_conv(),
        message=_msg(),
        routing_decision=routing_decision or {"execution_mode": "multi_agent_parallel"},
        llm=llm or MagicMock(name="llm"),
        tools=tools or [],
        history=history or [],
    ))


class TestMultiAgentExecutor:
    def test_execute_multi_item_concat_aggregation(self):
        items = [
            TaskPlanItem(task_id="subtask_1", title="t1", description="d1"),
            TaskPlanItem(task_id="subtask_2", title="t2", description="d2"),
        ]
        plan = _plan(items, strategy="concat")
        executor, _ = _build_executor(plan)
        results = [
            OrchestratedAgentResult(agent_id="a", task_id="subtask_1", answer="答案A"),
            OrchestratedAgentResult(agent_id="b", task_id="subtask_2", answer="答案B"),
        ]

        with patch("internal.service.executors.multi_agent_executor.AgentTaskExecutor"), \
             patch("internal.service.executors.multi_agent_executor.ExecutionCoordinatorService") as mock_coord_cls, \
             patch.object(MultiAgentExecutor, "_build_agent_config", return_value=MagicMock()):
            coordinator = MagicMock()
            coordinator.execute.return_value = results
            mock_coord_cls.return_value = coordinator

            events = _run_execute(executor)

        plan_arg = coordinator.execute.call_args.args[0]
        assert len(plan_arg.items) == 2
        assert plan_arg.items[0].task_id == "subtask_1"
        assert plan_arg.items[1].task_id == "subtask_2"
        assert plan_arg.execution_mode == "multi_agent_parallel"

        thoughts = [e for e in events if e.startswith(f"event: {QueueEvent.AGENT_THOUGHT.value}")]
        assert len(thoughts) == 2
        messages = [e for e in events if e.startswith(f"event: {QueueEvent.AGENT_MESSAGE.value}")]
        assert len(messages) == 1

        payload = _parse_payload(messages[0])
        assert "答案A" in payload["answer"]
        assert "答案B" in payload["answer"]
        assert "---" in payload["answer"]

    def test_execute_passes_available_agents_and_tools_to_decomposer(self):
        items = [TaskPlanItem(task_id="subtask_1", title="t", description="d")]
        plan = _plan(items)
        executor, task_decomposer = _build_executor(plan)
        tool_a = MagicMock(name="tool_a")
        tool_a.name = "search"
        tool_a.description = "联网搜索"

        with patch("internal.service.executors.multi_agent_executor.AgentTaskExecutor"), \
             patch("internal.service.executors.multi_agent_executor.ExecutionCoordinatorService") as mock_coord_cls, \
             patch.object(MultiAgentExecutor, "_build_agent_config", return_value=MagicMock()):
            coordinator = MagicMock()
            coordinator.execute.return_value = []
            mock_coord_cls.return_value = coordinator

            _run_execute(
                executor,
                routing_decision={
                    "execution_mode": "multi_agent_parallel",
                    "agent_subset": {
                        "selected_agents": [
                            {"agent_id": "agent-1", "name": "调研Agent", "description": "做调研"},
                        ],
                    },
                },
                tools=[tool_a],
            )

        args, _ = task_decomposer.decompose.call_args
        query, agents, tools_info = args
        assert query == "多智能体任务"
        assert agents[0]["agent_id"] == "agent-1"
        assert agents[0]["name"] == "调研Agent"
        assert tools_info[0]["name"] == "search"
        assert tools_info[0]["description"] == "联网搜索"

    def test_execute_sequential_mode_passthrough(self):
        items = [
            TaskPlanItem(task_id="subtask_1", title="t1", description="d1"),
            TaskPlanItem(
                task_id="subtask_2",
                title="t2",
                description="d2",
                depends_on=["subtask_1"],
            ),
        ]
        plan = _plan(items, mode="multi_agent_sequential")
        executor, _ = _build_executor(plan)

        with patch("internal.service.executors.multi_agent_executor.AgentTaskExecutor"), \
             patch("internal.service.executors.multi_agent_executor.ExecutionCoordinatorService") as mock_coord_cls, \
             patch.object(MultiAgentExecutor, "_build_agent_config", return_value=MagicMock()):
            coordinator = MagicMock()
            coordinator.execute.return_value = []
            mock_coord_cls.return_value = coordinator

            _run_execute(
                executor,
                routing_decision={"execution_mode": "multi_agent_sequential"},
            )

        plan_arg = coordinator.execute.call_args.args[0]
        assert plan_arg.execution_mode == "multi_agent_sequential"
        assert plan_arg.items[1].depends_on == ["subtask_1"]

    def test_execute_summarize_aggregation_invokes_llm(self):
        items = [
            TaskPlanItem(task_id="subtask_1", title="t1", description="d1"),
            TaskPlanItem(task_id="subtask_2", title="t2", description="d2"),
        ]
        plan = _plan(items, strategy="summarize")
        executor, _ = _build_executor(plan)
        results = [
            OrchestratedAgentResult(agent_id="a", task_id="subtask_1", answer="片段A"),
            OrchestratedAgentResult(agent_id="b", task_id="subtask_2", answer="片段B"),
        ]
        llm = MagicMock(name="llm")
        llm.invoke.return_value = AIMessage(content="摘要结果")

        with patch("internal.service.executors.multi_agent_executor.AgentTaskExecutor"), \
             patch("internal.service.executors.multi_agent_executor.ExecutionCoordinatorService") as mock_coord_cls, \
             patch.object(MultiAgentExecutor, "_build_agent_config", return_value=MagicMock()):
            coordinator = MagicMock()
            coordinator.execute.return_value = results
            mock_coord_cls.return_value = coordinator

            events = _run_execute(executor, llm=llm)

        llm.invoke.assert_called_once()
        messages = [e for e in events if e.startswith(f"event: {QueueEvent.AGENT_MESSAGE.value}")]
        payload = _parse_payload(messages[0])
        assert payload["answer"] == "摘要结果"

    def test_execute_best_of_aggregation_invokes_llm(self):
        items = [
            TaskPlanItem(task_id="subtask_1", title="t1", description="d1"),
            TaskPlanItem(task_id="subtask_2", title="t2", description="d2"),
        ]
        plan = _plan(items, strategy="best_of")
        executor, _ = _build_executor(plan)
        results = [
            OrchestratedAgentResult(agent_id="a", task_id="subtask_1", answer="候选A"),
            OrchestratedAgentResult(agent_id="b", task_id="subtask_2", answer="候选B"),
        ]
        llm = MagicMock(name="llm")
        llm.invoke.return_value = AIMessage(content="最佳答案")

        with patch("internal.service.executors.multi_agent_executor.AgentTaskExecutor"), \
             patch("internal.service.executors.multi_agent_executor.ExecutionCoordinatorService") as mock_coord_cls, \
             patch.object(MultiAgentExecutor, "_build_agent_config", return_value=MagicMock()):
            coordinator = MagicMock()
            coordinator.execute.return_value = results
            mock_coord_cls.return_value = coordinator

            events = _run_execute(executor, llm=llm)

        llm.invoke.assert_called_once()
        messages = [e for e in events if e.startswith(f"event: {QueueEvent.AGENT_MESSAGE.value}")]
        payload = _parse_payload(messages[0])
        assert payload["answer"] == "最佳答案"

    def test_execute_subtask_failure_does_not_break_aggregation(self):
        items = [
            TaskPlanItem(task_id="subtask_1", title="t1", description="d1"),
            TaskPlanItem(task_id="subtask_2", title="t2", description="d2"),
        ]
        plan = _plan(items, strategy="concat")
        executor, _ = _build_executor(plan)
        results = [
            OrchestratedAgentResult(
                agent_id="",
                task_id="subtask_1",
                answer="",
                errors=["agent_execution_failed"],
                confidence=0,
            ),
            OrchestratedAgentResult(agent_id="b", task_id="subtask_2", answer="有效答案"),
        ]

        with patch("internal.service.executors.multi_agent_executor.AgentTaskExecutor"), \
             patch("internal.service.executors.multi_agent_executor.ExecutionCoordinatorService") as mock_coord_cls, \
             patch.object(MultiAgentExecutor, "_build_agent_config", return_value=MagicMock()):
            coordinator = MagicMock()
            coordinator.execute.return_value = results
            mock_coord_cls.return_value = coordinator

            events = _run_execute(executor)

        messages = [e for e in events if e.startswith(f"event: {QueueEvent.AGENT_MESSAGE.value}")]
        payload = _parse_payload(messages[0])
        assert payload["answer"] == "有效答案"

    def test_execute_empty_results_yields_default_message(self):
        items = [TaskPlanItem(task_id="subtask_1", title="t", description="d")]
        plan = _plan(items)
        executor, _ = _build_executor(plan)

        with patch("internal.service.executors.multi_agent_executor.AgentTaskExecutor"), \
             patch("internal.service.executors.multi_agent_executor.ExecutionCoordinatorService") as mock_coord_cls, \
             patch.object(MultiAgentExecutor, "_build_agent_config", return_value=MagicMock()):
            coordinator = MagicMock()
            coordinator.execute.return_value = []
            mock_coord_cls.return_value = coordinator

            events = _run_execute(executor)

        assert len(events) == 1
        assert events[0].startswith(f"event: {QueueEvent.AGENT_MESSAGE.value}")
        payload = _parse_payload(events[0])
        assert payload["answer"] == "多智能体执行完成，但未获得有效回答。"

    def test_execute_coordinator_failure_yields_fallback(self):
        items = [TaskPlanItem(task_id="subtask_1", title="t", description="d")]
        plan = _plan(items)
        executor, _ = _build_executor(plan)

        with patch("internal.service.executors.multi_agent_executor.AgentTaskExecutor"), \
             patch("internal.service.executors.multi_agent_executor.ExecutionCoordinatorService") as mock_coord_cls, \
             patch.object(MultiAgentExecutor, "_build_agent_config", return_value=MagicMock()):
            coordinator = MagicMock()
            coordinator.execute.side_effect = RuntimeError("协调器崩溃")
            mock_coord_cls.return_value = coordinator

            events = _run_execute(executor)

        assert len(events) == 1
        assert events[0].startswith(f"event: {QueueEvent.AGENT_MESSAGE.value}")
        payload = _parse_payload(events[0])
        assert payload["answer"] == "多智能体执行遇到问题，请稍后重试。"

    def test_execute_single_item_skips_aggregation(self):
        items = [TaskPlanItem(task_id="subtask_1", title="t", description="d")]
        plan = _plan(items, strategy="summarize")
        executor, _ = _build_executor(plan)
        results = [OrchestratedAgentResult(agent_id="a", task_id="subtask_1", answer="唯一答案")]
        llm = MagicMock(name="llm")

        with patch("internal.service.executors.multi_agent_executor.AgentTaskExecutor"), \
             patch("internal.service.executors.multi_agent_executor.ExecutionCoordinatorService") as mock_coord_cls, \
             patch.object(MultiAgentExecutor, "_build_agent_config", return_value=MagicMock()):
            coordinator = MagicMock()
            coordinator.execute.return_value = results
            mock_coord_cls.return_value = coordinator

            events = _run_execute(executor, llm=llm)

        llm.invoke.assert_not_called()
        messages = [e for e in events if e.startswith(f"event: {QueueEvent.AGENT_MESSAGE.value}")]
        payload = _parse_payload(messages[0])
        assert payload["answer"] == "唯一答案"
