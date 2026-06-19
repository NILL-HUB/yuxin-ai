import json
from unittest.mock import MagicMock, patch
from uuid import uuid4

from internal.core.agent.entities.queue_entity import AgentThought, QueueEvent
from internal.service.executors.single_agent_executor import SingleAgentExecutor


def _parse_payload(sse_event):
    return json.loads(sse_event.split("data:", 1)[1].strip())


def _make_thought(event, answer="", thought="", task_id=None):
    return AgentThought(
        id=uuid4(),
        task_id=task_id or uuid4(),
        event=event,
        thought=thought,
        answer=answer,
        latency=1.0,
        total_token_count=10,
    )


class TestSingleAgentExecutor:
    def _build_executor(self):
        llm = MagicMock()
        llm.convert_to_human_message.return_value = MagicMock(name="human_message")
        return SingleAgentExecutor(agent_config=MagicMock(name="agent_config"), tools=[], llm=llm), llm

    @patch("internal.service.executors.single_agent_executor.FunctionCallAgent")
    def test_stream_success_yields_sse_events(self, mock_agent_cls):
        agent = MagicMock()
        thoughts = [
            _make_thought(QueueEvent.AGENT_THOUGHT, thought="思考中", task_id=uuid4()),
            _make_thought(QueueEvent.AGENT_MESSAGE, answer="最终答案", task_id=uuid4()),
        ]
        agent.stream.return_value = iter(thoughts)
        mock_agent_cls.return_value = agent

        executor, llm = self._build_executor()
        events = list(executor.stream(
            query="你好", history=[], conversation_id="conv-1", message_id="msg-1",
        ))

        mock_agent_cls.assert_called_once_with(llm=llm, agent_config=executor.agent_config)
        llm.convert_to_human_message.assert_called_once_with("你好", [])

        assert len(events) == 2
        assert events[0].startswith(f"event: {QueueEvent.AGENT_THOUGHT.value}")
        assert events[1].startswith(f"event: {QueueEvent.AGENT_MESSAGE.value}")

        thought_payload = _parse_payload(events[0])
        assert thought_payload["thought"] == "思考中"
        assert thought_payload["conversation_id"] == "conv-1"
        assert thought_payload["message_id"] == "msg-1"
        assert thought_payload["id"] == "msg-1"

        message_payload = _parse_payload(events[1])
        assert message_payload["answer"] == "最终答案"

        stream_input = agent.stream.call_args.args[0]
        assert stream_input["history"] == []
        assert stream_input["long_term_memory"] == ""
        assert stream_input["user_memory"] == ""

    @patch("internal.service.executors.single_agent_executor.FunctionCallAgent")
    def test_stream_agent_instantiation_failure_yields_error_event(self, mock_agent_cls):
        mock_agent_cls.side_effect = RuntimeError("agent 构建失败")

        executor, _ = self._build_executor()
        events = list(executor.stream(
            query="你好", history=[], conversation_id="conv-1", message_id="msg-1",
        ))

        assert len(events) == 1
        assert events[0].startswith(f"event: {QueueEvent.ERROR.value}")
        payload = _parse_payload(events[0])
        assert "agent 构建失败" in payload["observation"]
        assert payload["conversation_id"] == "conv-1"
        assert payload["message_id"] == "msg-1"

    @patch("internal.service.executors.single_agent_executor.FunctionCallAgent")
    def test_stream_skips_thought_that_fails_serialization(self, mock_agent_cls):
        agent = MagicMock()
        bad_thought = MagicMock()
        bad_thought.event = QueueEvent.AGENT_THOUGHT
        bad_thought.model_dump.side_effect = RuntimeError("序列化失败")
        good_thought = _make_thought(QueueEvent.AGENT_MESSAGE, answer="好答案", task_id=uuid4())
        agent.stream.return_value = iter([bad_thought, good_thought])
        mock_agent_cls.return_value = agent

        executor, _ = self._build_executor()
        events = list(executor.stream(
            query="你好", history=[], conversation_id="conv-1", message_id="msg-1",
        ))

        assert len(events) == 1
        assert events[0].startswith(f"event: {QueueEvent.AGENT_MESSAGE.value}")
        assert _parse_payload(events[0])["answer"] == "好答案"
