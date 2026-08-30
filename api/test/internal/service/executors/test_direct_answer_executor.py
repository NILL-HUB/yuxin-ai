import json
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from internal.core.agent.entities.queue_entity import QueueEvent
from internal.service.executors.direct_answer_executor import DirectAnswerExecutor
from internal.service.system_prompt_library_service import SystemPromptLibraryService

SYSTEM_PROMPT = "system-prompt"


class _FakeDelta:
    def __init__(self, content="", reasoning_content="", tool_calls=None):
        self.content = content
        self.reasoning_content = reasoning_content
        self.tool_calls = tool_calls


class _FakeChoice:
    def __init__(self, content="", reasoning_content="", tool_calls=None):
        self.delta = _FakeDelta(content=content, reasoning_content=reasoning_content, tool_calls=tool_calls)
        self.usage = None


class _FakeChunk:
    def __init__(self, content="", reasoning_content="", tool_calls=None):
        self.choices = [_FakeChoice(content=content, reasoning_content=reasoning_content, tool_calls=tool_calls)]


class _UsageChunk:
    """OpenAI 兼容流末尾的 usage chunk：choices 为空数组，usage 在顶层。"""

    def __init__(self, usage):
        self.usage = usage
        self.choices = []


class TestDirectAnswerExecutor:
    def _build_executor(self, llm):
        return DirectAnswerExecutor(llm=llm)

    def _parse_payload(self, sse_event):
        return json.loads(sse_event.split("data:", 1)[1].strip())

    def test_stream_success_yields_agent_message_events(self):
        llm = MagicMock()
        llm.client.create.return_value = [
            _FakeChunk(content="你好"),
            _FakeChunk(content="，我是智能助手。"),
        ]
        executor = self._build_executor(llm)

        with patch.object(SystemPromptLibraryService, "get_prompt_or_default", return_value=SYSTEM_PROMPT):
            events = list(executor.stream(query="你好", conversation_id="conv-1", message_id="msg-1"))

        assert len(events) == 2
        assert all(e.startswith(f"event: {QueueEvent.AGENT_MESSAGE.value}") for e in events)

        message_payload = self._parse_payload(events[0])
        assert message_payload["answer"] == "你好"
        assert message_payload["conversation_id"] == "conv-1"
        assert message_payload["message_id"] == "msg-1"
        assert message_payload["id"] == "msg-1"

        assert executor.last_answer == "你好，我是智能助手。"

        llm.client.create.assert_called_once()
        invoked_messages = llm.client.create.call_args.kwargs["messages"]
        assert invoked_messages[0] == {"role": "system", "content": SYSTEM_PROMPT}
        assert invoked_messages[-1] == {"role": "user", "content": "你好"}

    def test_stream_success_includes_history_messages(self):
        llm = MagicMock()
        llm.client.create.return_value = [_FakeChunk(content="好的")]
        executor = self._build_executor(llm)
        history = [
            {"role": "user", "content": "上一轮问题"},
            {"role": "assistant", "content": "上一轮回答"},
        ]

        with patch.object(SystemPromptLibraryService, "get_prompt_or_default", return_value=SYSTEM_PROMPT):
            list(executor.stream(query="继续", history=history, conversation_id="c", message_id="m"))

        invoked_messages = llm.client.create.call_args.kwargs["messages"]
        assert len(invoked_messages) == 4
        assert invoked_messages[0] == {"role": "system", "content": SYSTEM_PROMPT}
        assert invoked_messages[1] is history[0]
        assert invoked_messages[2] is history[1]
        assert invoked_messages[3] == {"role": "user", "content": "继续"}

    def test_stream_error_yields_error_event(self):
        llm = MagicMock()
        llm.client.create.side_effect = RuntimeError("模型调用失败")
        executor = self._build_executor(llm)

        with patch.object(SystemPromptLibraryService, "get_prompt_or_default", return_value=SYSTEM_PROMPT):
            events = list(executor.stream(query="你好", conversation_id="conv-1", message_id="msg-1"))

        assert len(events) == 1
        assert events[0].startswith(f"event: {QueueEvent.ERROR.value}")

        error_payload = self._parse_payload(events[0])
        assert "模型调用失败" in error_payload["observation"]
        assert error_payload["conversation_id"] == "conv-1"
        assert error_payload["message_id"] == "msg-1"

        llm.client.create.assert_called_once()

    def test_stream_request_should_enable_include_usage(self):
        llm = MagicMock()
        llm.client.create.return_value = [_FakeChunk(content="好的")]
        executor = self._build_executor(llm)

        with patch.object(SystemPromptLibraryService, "get_prompt_or_default", return_value=SYSTEM_PROMPT):
            list(executor.stream(query="你好", conversation_id="conv-1", message_id="msg-1"))

        kwargs = llm.client.create.call_args.kwargs
        assert kwargs["stream"] is True
        assert kwargs["stream_options"] == {"include_usage": True}

    def test_stream_should_capture_usage_from_empty_choices_chunk(self):
        usage = SimpleNamespace(prompt_tokens=10, completion_tokens=5, total_tokens=15)
        llm = MagicMock()
        llm.client.create.return_value = [
            _FakeChunk(content="答案"),
            _UsageChunk(usage=usage),
        ]
        executor = self._build_executor(llm)

        with patch.object(SystemPromptLibraryService, "get_prompt_or_default", return_value=SYSTEM_PROMPT):
            events = list(executor.stream(query="你好", conversation_id="conv-1", message_id="msg-1"))

        assert any(e.startswith(f"event: {QueueEvent.AGENT_MESSAGE.value}") for e in events)
        assert executor.last_answer == "答案"
        assert executor.last_token_usage == {
            "prompt_tokens": 10,
            "completion_tokens": 5,
            "total_tokens": 15,
            "cached_tokens": 0,
        }

    def test_extract_token_usage_from_sdk_usage_object_attributes(self):
        response = SimpleNamespace(
            prompt_tokens=10,
            completion_tokens=5,
            total_tokens=15,
            response_metadata={},
        )
        result = DirectAnswerExecutor._extract_token_usage(response)
        assert result == {
            "prompt_tokens": 10,
            "completion_tokens": 5,
            "total_tokens": 15,
            "cached_tokens": 0,
        }

    def test_extract_token_usage_returns_none_without_any_usage(self):
        response = SimpleNamespace(response_metadata={})
        assert DirectAnswerExecutor._extract_token_usage(response) is None

    def test_stream_should_take_usage_from_final_choice_when_no_top_usage(self):
        llm = MagicMock()
        llm.client.create.return_value = [
            _FakeChunk(content="好的"),
        ]
        executor = self._build_executor(llm)
        # 无 usage chunk 时 last_token_usage 应为 None，且不抛异常
        with patch.object(SystemPromptLibraryService, "get_prompt_or_default", return_value=SYSTEM_PROMPT):
            list(executor.stream(query="你好", conversation_id="conv-1", message_id="msg-1"))
        assert executor.last_answer == "好的"
        assert executor.last_token_usage is None

    def test_extract_token_usage_includes_cached_tokens_from_metadata_dict(self):
        usage = {
            "prompt_tokens": 100,
            "completion_tokens": 50,
            "total_tokens": 150,
            "prompt_tokens_details": {"cached_tokens": 40},
        }
        result = DirectAnswerExecutor._extract_token_usage(
            SimpleNamespace(response_metadata={"token_usage": usage})
        )
        assert result["cached_tokens"] == 40
        assert result["prompt_tokens"] == 100
        assert result["completion_tokens"] == 50
        assert result["total_tokens"] == 150

    def test_extract_token_usage_includes_cached_tokens_from_usage_object(self):
        response = SimpleNamespace(
            prompt_tokens=100,
            completion_tokens=50,
            total_tokens=150,
            prompt_tokens_details=SimpleNamespace(cached_tokens=40),
            response_metadata={},
        )
        result = DirectAnswerExecutor._extract_token_usage(response)
        assert result["cached_tokens"] == 40
        assert result["prompt_tokens"] == 100
        assert result["completion_tokens"] == 50
        assert result["total_tokens"] == 150

    def test_extract_token_usage_from_dict_includes_cached_tokens(self):
        usage = {
            "prompt_tokens": 100,
            "completion_tokens": 50,
            "total_tokens": 150,
            "prompt_tokens_details": {"cached_tokens": 40},
        }
        result = DirectAnswerExecutor._extract_token_usage_from_dict(usage)
        assert result["cached_tokens"] == 40
