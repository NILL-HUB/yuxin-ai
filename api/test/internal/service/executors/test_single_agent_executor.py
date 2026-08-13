import json
from types import SimpleNamespace
from unittest.mock import MagicMock, patch
from uuid import uuid4

from internal.entity.cancel_token_entity import CancelToken
from internal.core.agent.entities.queue_entity import QueueEvent
from internal.entity.execution_orchestration_entity import OrchestratedAgentResult
from internal.entity.orchestrator_entity import ExecutionMode
from internal.service.executors.single_agent_executor import SingleAgentExecutor


def _parse_payload(sse_event):
    return json.loads(sse_event.split("data:", 1)[1].strip())


def _conv():
    return SimpleNamespace(id=uuid4())


def _msg():
    return SimpleNamespace(id=uuid4())


def _run_execute(executor, *, execution_mode="single_agent", query="单智能体任务"):
    return list(executor.execute(
        query=query,
        conversation=_conv(),
        message=_msg(),
        execution_mode=execution_mode,
    ))


def _patch_coord(results=None, side_effect=None):
    manager = MagicMock()
    coordinator = MagicMock()
    if side_effect is not None:
        coordinator.execute.side_effect = side_effect
    else:
        coordinator.execute.return_value = results if results is not None else []
    patcher_agent = patch(
        "internal.service.executors.single_agent_executor.AgentTaskExecutor"
    )
    patcher_coord = patch(
        "internal.service.executors.single_agent_executor.ExecutionCoordinatorService"
    )
    manager.patcher_agent = patcher_agent
    manager.patcher_coord = patcher_coord
    manager.coordinator = coordinator
    return manager


class TestSingleAgentExecutor:
    def test_keepalive_sse_reports_long_task_progress(self):
        conversation_id = str(uuid4())
        message_id = str(uuid4())

        sse = SingleAgentExecutor._keepalive_sse(conversation_id, message_id)

        assert sse.startswith(f"event: {QueueEvent.AGENT_THOUGHT.value}")
        payload = _parse_payload(sse)
        assert "执行中" in payload["thought"]
        assert payload["conversation_id"] == conversation_id
        assert payload["message_id"] == message_id

    def test_single_agent_executor_should_not_emit_routing_decision_to_user_stream(self):
        executor = SingleAgentExecutor(agent_class=MagicMock(), llm=MagicMock())
        manager = _patch_coord(results=[])

        with manager.patcher_agent, manager.patcher_coord as mock_coord_cls:
            mock_coord_cls.return_value = manager.coordinator
            events = list(executor.execute(
                query="测试查询",
                conversation=_conv(),
                message=_msg(),
                execution_mode=ExecutionMode.SINGLE_AGENT_WITH_TOOLS.value,
                routing_decision={
                    "intent": "tool_task",
                    "execution_mode": "single_agent_with_tools",
                    "recommended_model_tier": "2",
                },
            ))

        assert not any(
            event.startswith("event: orchestrator_routing")
            for event in events
        )

    def test_single_agent_executor_success(self):
        executor = SingleAgentExecutor(agent_class=MagicMock(), llm=MagicMock())
        results = [
            OrchestratedAgentResult(
                agent_id="a", task_id="single_agent_task", answer="最终答案"
            ),
        ]
        manager = _patch_coord(results=results)

        with manager.patcher_agent, manager.patcher_coord as mock_coord_cls:
            mock_coord_cls.return_value = manager.coordinator
            events = _run_execute(executor)

        plan_arg = manager.coordinator.execute.call_args.args[0]
        assert plan_arg.execution_mode == "single_agent"
        assert len(plan_arg.items) == 1
        assert plan_arg.items[0].task_id == "single_agent_task"

        thoughts = [
            e for e in events
            if e.startswith(f"event: {QueueEvent.AGENT_THOUGHT.value}")
        ]
        assert len(thoughts) == 1
        thought_payload = _parse_payload(thoughts[0])
        assert thought_payload["answer"] == "最终答案"

        messages = [
            e for e in events
            if e.startswith(f"event: {QueueEvent.AGENT_MESSAGE.value}")
        ]
        assert len(messages) == 1
        message_payload = _parse_payload(messages[0])
        assert message_payload["answer"] == "最终答案"

    def test_single_agent_executor_empty_answer(self):
        executor = SingleAgentExecutor(agent_class=MagicMock(), llm=MagicMock())
        results = [
            OrchestratedAgentResult(
                agent_id="a", task_id="single_agent_task", answer=""
            ),
        ]
        manager = _patch_coord(results=results)

        with manager.patcher_agent, manager.patcher_coord as mock_coord_cls:
            mock_coord_cls.return_value = manager.coordinator
            events = _run_execute(executor)

        messages = [
            e for e in events
            if e.startswith(f"event: {QueueEvent.AGENT_MESSAGE.value}")
        ]
        assert len(messages) == 1
        payload = _parse_payload(messages[0])
        assert payload["answer"] == "单智能体执行完成，但未获得有效回答。"

    def test_single_agent_executor_exception(self):
        executor = SingleAgentExecutor(agent_class=MagicMock(), llm=MagicMock())
        manager = _patch_coord(side_effect=RuntimeError("协调器崩溃"))

        with manager.patcher_agent, manager.patcher_coord as mock_coord_cls:
            mock_coord_cls.return_value = manager.coordinator
            events = _run_execute(executor)

        assert len(events) == 2
        assert events[0].startswith(f"event: {QueueEvent.AGENT_MESSAGE.value}")
        payload = _parse_payload(events[0])
        assert payload["answer"] == "单智能体执行遇到问题，请稍后重试。"
        assert events[1].startswith(f"event: {QueueEvent.AGENT_END.value}")

    def test_single_agent_executor_build_plan(self):
        executor = SingleAgentExecutor(agent_class=MagicMock())

        plan = executor._build_plan("测试查询", ExecutionMode.SINGLE_AGENT.value)

        assert plan.original_query == "测试查询"
        assert plan.execution_mode == ExecutionMode.SINGLE_AGENT.value
        assert plan.reason == "single_agent_via_coordinator"
        assert len(plan.items) == 1
        item = plan.items[0]
        assert item.task_id == "single_agent_task"
        assert item.title == "单智能体任务"
        assert item.description == "测试查询"
        assert item.execution_order == 0

    def test_single_agent_executor_deep_thinking_mode(self):
        executor = SingleAgentExecutor(agent_class=MagicMock(), llm=MagicMock())
        results = [
            OrchestratedAgentResult(
                agent_id="a", task_id="single_agent_task", answer="深度思考答案"
            ),
        ]
        manager = _patch_coord(results=results)

        with manager.patcher_agent, manager.patcher_coord as mock_coord_cls:
            mock_coord_cls.return_value = manager.coordinator
            events = _run_execute(
                executor, execution_mode=ExecutionMode.DEEP_THINKING.value
            )

        plan_arg = manager.coordinator.execute.call_args.args[0]
        assert plan_arg.execution_mode == ExecutionMode.DEEP_THINKING.value

        thoughts = [
            e for e in events
            if e.startswith(f"event: {QueueEvent.AGENT_THOUGHT.value}")
        ]
        assert len(thoughts) == 1
        messages = [
            e for e in events
            if e.startswith(f"event: {QueueEvent.AGENT_MESSAGE.value}")
        ]
        assert len(messages) == 1
        payload = _parse_payload(messages[0])
        assert payload["answer"] == "深度思考答案"

    def test_single_agent_executor_single_agent_with_tools_mode(self):
        tool = MagicMock(name="search")
        tool.name = "search"
        executor = SingleAgentExecutor(
            agent_class=MagicMock(), llm=MagicMock(), tools=[tool]
        )
        results = [
            OrchestratedAgentResult(
                agent_id="a", task_id="single_agent_task", answer="工具答案"
            ),
        ]
        manager = _patch_coord(results=results)

        with manager.patcher_agent, manager.patcher_coord as mock_coord_cls:
            mock_coord_cls.return_value = manager.coordinator
            events = _run_execute(
                executor, execution_mode=ExecutionMode.SINGLE_AGENT_WITH_TOOLS.value
            )

        plan_arg = manager.coordinator.execute.call_args.args[0]
        assert plan_arg.execution_mode == ExecutionMode.SINGLE_AGENT_WITH_TOOLS.value

        messages = [
            e for e in events
            if e.startswith(f"event: {QueueEvent.AGENT_MESSAGE.value}")
        ]
        assert len(messages) == 1
        payload = _parse_payload(messages[0])
        assert payload["answer"] == "工具答案"

    def test_single_agent_executor_passes_subtask_registry_and_request_id(self):
        registry = MagicMock()
        cancel_token = CancelToken()
        executor = SingleAgentExecutor(
            agent_class=MagicMock(),
            llm=MagicMock(),
            subtask_registry=registry,
            cancel_token=cancel_token,
        )
        manager = _patch_coord(results=[])
        message = _msg()

        with manager.patcher_agent, manager.patcher_coord as mock_coord_cls:
            mock_coord_cls.return_value = manager.coordinator
            list(executor.execute(
                query="测试查询",
                conversation=_conv(),
                message=message,
                execution_mode=ExecutionMode.SINGLE_AGENT.value,
            ))

        kwargs = mock_coord_cls.call_args.kwargs
        assert kwargs["subtask_registry"] is registry
        assert kwargs["cancel_token"] is cancel_token
        assert kwargs["request_id"] == str(message.id)
        registry.register_cancel_token.assert_called_once_with(str(message.id), cancel_token)
