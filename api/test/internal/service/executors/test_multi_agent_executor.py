import json
from unittest.mock import MagicMock, patch

from internal.core.agent.entities.queue_entity import QueueEvent
from internal.entity.execution_orchestration_entity import OrchestratedAgentResult
from internal.service.executors.multi_agent_executor import MultiAgentExecutor


def _parse_payload(sse_event):
    return json.loads(sse_event.split("data:", 1)[1].strip())


class TestMultiAgentExecutor:
    def _build_executor(self):
        return MultiAgentExecutor(
            agent_config=MagicMock(name="agent_config"),
            tools=[],
            llm=MagicMock(name="llm"),
        )

    @patch("internal.service.executors.multi_agent_executor.ExecutionCoordinatorService")
    @patch("internal.service.executors.multi_agent_executor.AgentTaskExecutor")
    def test_stream_success_yields_thought_and_message_events(
        self, mock_task_executor_cls, mock_coordinator_cls,
    ):
        results = [
            OrchestratedAgentResult(agent_id="a1", task_id="t1", answer="答案1"),
            OrchestratedAgentResult(agent_id="a2", task_id="t2", answer=""),
        ]
        coordinator = MagicMock()
        coordinator.execute.return_value = results
        mock_coordinator_cls.return_value = coordinator

        executor = self._build_executor()
        events = list(executor.stream(
            query="多智能体任务", history=[], conversation_id="conv-1", message_id="msg-1",
        ))

        mock_task_executor_cls.assert_called_once()
        mock_coordinator_cls.assert_called_once_with(executor=mock_task_executor_cls.return_value)
        coordinator.execute.assert_called_once()
        plan = coordinator.execute.call_args.args[0]
        assert plan.execution_mode == "parallel"
        assert plan.original_query == "多智能体任务"
        assert len(plan.items) == 1
        assert plan.items[0].task_id == "msg-1"

        assert len(events) == 3
        assert events[0].startswith(f"event: {QueueEvent.AGENT_THOUGHT.value}")
        assert events[1].startswith(f"event: {QueueEvent.AGENT_THOUGHT.value}")
        assert events[2].startswith(f"event: {QueueEvent.AGENT_MESSAGE.value}")

        first_payload = _parse_payload(events[0])
        assert first_payload["answer"] == "答案1"
        assert first_payload["thought"] == "t1"
        assert first_payload["conversation_id"] == "conv-1"
        assert first_payload["message_id"] == "msg-1"

        message_payload = _parse_payload(events[2])
        assert message_payload["answer"] == "答案1"

    @patch("internal.service.executors.multi_agent_executor.ExecutionCoordinatorService")
    @patch("internal.service.executors.multi_agent_executor.AgentTaskExecutor")
    def test_stream_passes_sequential_execution_mode(self, mock_task_executor_cls, mock_coordinator_cls):
        coordinator = MagicMock()
        coordinator.execute.return_value = []
        mock_coordinator_cls.return_value = coordinator

        executor = self._build_executor()
        list(executor.stream(
            query="串行任务", history=[], conversation_id="conv-1", message_id="msg-1",
            execution_mode="multi_agent_sequential",
        ))

        plan = coordinator.execute.call_args.args[0]
        assert plan.execution_mode == "multi_agent_sequential"

    @patch("internal.service.executors.multi_agent_executor.ExecutionCoordinatorService")
    @patch("internal.service.executors.multi_agent_executor.AgentTaskExecutor")
    def test_stream_empty_results_yields_default_message(self, mock_task_executor_cls, mock_coordinator_cls):
        coordinator = MagicMock()
        coordinator.execute.return_value = []
        mock_coordinator_cls.return_value = coordinator

        executor = self._build_executor()
        events = list(executor.stream(
            query="空任务", history=[], conversation_id="conv-1", message_id="msg-1",
        ))

        assert len(events) == 1
        assert events[0].startswith(f"event: {QueueEvent.AGENT_MESSAGE.value}")
        payload = _parse_payload(events[0])
        assert payload["answer"] == "多智能体执行完成，但未获得有效回答。"

    @patch("internal.service.executors.multi_agent_executor.ExecutionCoordinatorService")
    @patch("internal.service.executors.multi_agent_executor.AgentTaskExecutor")
    def test_stream_coordinator_failure_yields_fallback_message(self, mock_task_executor_cls, mock_coordinator_cls):
        coordinator = MagicMock()
        coordinator.execute.side_effect = RuntimeError("协调器崩溃")
        mock_coordinator_cls.return_value = coordinator

        executor = self._build_executor()
        events = list(executor.stream(
            query="失败任务", history=[], conversation_id="conv-1", message_id="msg-1",
        ))

        assert len(events) == 1
        assert events[0].startswith(f"event: {QueueEvent.AGENT_MESSAGE.value}")
        payload = _parse_payload(events[0])
        assert payload["answer"] == "多智能体执行遇到问题，请稍后重试。"
