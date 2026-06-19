import json
from unittest.mock import MagicMock

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

from internal.core.agent.entities.queue_entity import QueueEvent
from internal.service.executors.direct_answer_executor import DirectAnswerExecutor


class TestDirectAnswerExecutor:
    def _build_executor(self, llm):
        language_model_service = MagicMock()
        language_model_service.get_cheap_chat_model.return_value = llm
        return DirectAnswerExecutor(language_model_service=language_model_service)

    def _parse_payload(self, sse_event):
        return json.loads(sse_event.split("data:", 1)[1].strip())

    def test_stream_success_yields_agent_message_and_agent_end(self):
        llm = MagicMock()
        llm.invoke.return_value = AIMessage(content="你好，我是智能助手。")
        executor = self._build_executor(llm)

        events = list(executor.stream(query="你好", conversation_id="conv-1", message_id="msg-1"))

        assert len(events) == 2
        assert events[0].startswith(f"event: {QueueEvent.AGENT_MESSAGE.value}")
        assert events[1].startswith(f"event: {QueueEvent.AGENT_END.value}")

        message_payload = self._parse_payload(events[0])
        assert message_payload["answer"] == "你好，我是智能助手。"
        assert message_payload["conversation_id"] == "conv-1"
        assert message_payload["message_id"] == "msg-1"
        assert message_payload["id"] == "msg-1"

        end_payload = self._parse_payload(events[1])
        assert end_payload["conversation_id"] == "conv-1"
        assert end_payload["id"] == "msg-1"

        llm.invoke.assert_called_once()
        invoked_messages = llm.invoke.call_args[0][0]
        assert isinstance(invoked_messages[0], SystemMessage)
        assert isinstance(invoked_messages[-1], HumanMessage)
        assert invoked_messages[-1].content == "你好"

    def test_stream_success_includes_history_messages(self):
        llm = MagicMock()
        llm.invoke.return_value = AIMessage(content="好的")
        executor = self._build_executor(llm)
        history = [HumanMessage(content="上一轮问题"), AIMessage(content="上一轮回答")]

        list(executor.stream(query="继续", history=history, conversation_id="c", message_id="m"))

        invoked_messages = llm.invoke.call_args[0][0]
        assert len(invoked_messages) == 4
        assert invoked_messages[0] is not history[0]
        assert invoked_messages[1] is history[0]
        assert invoked_messages[2] is history[1]
        assert invoked_messages[3].content == "继续"

    def test_stream_error_yields_error_event(self):
        llm = MagicMock()
        llm.invoke.side_effect = RuntimeError("模型调用失败")
        executor = self._build_executor(llm)

        events = list(executor.stream(query="你好", conversation_id="conv-1", message_id="msg-1"))

        assert len(events) == 1
        assert events[0].startswith(f"event: {QueueEvent.ERROR.value}")

        error_payload = self._parse_payload(events[0])
        assert "模型调用失败" in error_payload["observation"]
        assert error_payload["conversation_id"] == "conv-1"
        assert error_payload["message_id"] == "msg-1"

        llm.invoke.assert_called_once()
