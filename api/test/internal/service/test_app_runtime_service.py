import asyncio
import json
from types import SimpleNamespace
from uuid import uuid4

import pytest

from internal.core.agent.entities.queue_entity import AgentThought, QueueEvent
from internal.entity.dataset_entity import RetrievalStrategy
from internal.service.app_runtime_service import AppRuntimeService


def _build_app_config_service():
    """构建测试用的 app_config_service 替身，提供空的工具加载方法。"""
    return SimpleNamespace(
        get_langchain_tools_by_tools_config=lambda *_args, **_kwargs: [],
        get_langchain_tools_by_mcp_bindings=lambda *_args, **_kwargs: [],
        get_langchain_tools_by_workflow_ids=lambda *_args, **_kwargs: [],
    )


class TestAppRuntimeServiceBuildTools:
    """覆盖 build_runtime_tools_for_config 对新版 knowledge_base_ids 的接入。"""

    def test_knowledge_base_ids_should_create_knowledge_retrieval_tool(self):
        """knowledge_base_ids 非空时调用 create_knowledge_retrieval_tool 并附带检索配置。"""
        kb_id = uuid4()
        retrieval_capture = {}
        retrieval_service = SimpleNamespace(
            create_knowledge_retrieval_tool=lambda **kwargs: retrieval_capture.update(kwargs) or "kb-tool",
        )
        account = SimpleNamespace(id=uuid4())

        tools = AppRuntimeService.build_runtime_tools_for_config(
            app_config_service=_build_app_config_service(),
            retrieval_service=retrieval_service,
            account=account,
            app_id=uuid4(),
            draft_app_config={
                "knowledge_base_ids": [str(kb_id)],
                "retrieval_config": {"retrieval_strategy": "semantic", "k": 6, "score": 0.2},
            },
            flask_app="flask-app",
        )

        # 新版检索工具应被加入工具列表
        assert "kb-tool" in tools
        # account_id 透传
        assert retrieval_capture["account_id"] == account.id
        assert retrieval_capture["flask_app"] == "flask-app"
        # 字符串 id 被转换为 UUID
        assert retrieval_capture["knowledge_base_ids"] == [kb_id]
        # retrieval_strategy 与 k 从 retrieval_config 透传
        assert retrieval_capture["retrieval_strategy"] == "semantic"
        assert retrieval_capture["k"] == 6

    def test_empty_knowledge_base_ids_should_skip_retrieval(self):
        """knowledge_base_ids 为空时不构建任何检索工具。"""
        retrieval_service = SimpleNamespace()
        account = SimpleNamespace(id=uuid4())

        tools = AppRuntimeService.build_runtime_tools_for_config(
            app_config_service=_build_app_config_service(),
            retrieval_service=retrieval_service,
            account=account,
            app_id=uuid4(),
            draft_app_config={},
            flask_app="flask-app",
        )

        assert tools == []

    def test_knowledge_base_ids_default_strategy_should_be_hybrid(self):
        """retrieval_config 缺失 retrieval_strategy 时默认使用 hybrid 策略。"""
        kb_id = uuid4()
        capture = {}
        retrieval_service = SimpleNamespace(
            create_knowledge_retrieval_tool=lambda **kwargs: capture.update(kwargs) or "kb-tool",
        )
        account = SimpleNamespace(id=uuid4())

        AppRuntimeService.build_runtime_tools_for_config(
            app_config_service=_build_app_config_service(),
            retrieval_service=retrieval_service,
            account=account,
            app_id=uuid4(),
            draft_app_config={
                "knowledge_base_ids": [str(kb_id)],
                "retrieval_config": {"k": 5},
            },
            flask_app="flask-app",
        )

        assert capture["retrieval_strategy"] == RetrievalStrategy.HYBRID.value
        assert capture["k"] == 5

    def test_invalid_knowledge_base_id_should_be_skipped(self):
        """非法 knowledge_base_id 字符串应被跳过，不阻断工具构建。"""
        valid_id = uuid4()
        capture = {}
        retrieval_service = SimpleNamespace(
            create_knowledge_retrieval_tool=lambda **kwargs: capture.update(kwargs) or "kb-tool",
        )
        account = SimpleNamespace(id=uuid4())

        tools = AppRuntimeService.build_runtime_tools_for_config(
            app_config_service=_build_app_config_service(),
            retrieval_service=retrieval_service,
            account=account,
            app_id=uuid4(),
            draft_app_config={
                "knowledge_base_ids": ["not-a-uuid", str(valid_id)],
            },
            flask_app="flask-app",
        )

        # 非法 id 被跳过，仅保留有效 id
        assert "kb-tool" in tools
        assert capture["knowledge_base_ids"] == [valid_id]


class _FakeAsyncAgent:
    """模拟带 astream 的运行时 Agent，产出预置的 AgentThought 事件序列。"""

    def __init__(self, events):
        self._events = events
        self.input = None

    async def astream(self, state):
        self.input = state
        for event in self._events:
            yield event


def _thought(event, answer="", thought="", event_id=None, task_id=None):
    return AgentThought(
        id=event_id or uuid4(),
        task_id=task_id or uuid4(),
        event=event,
        answer=answer,
        thought=thought,
        total_token_count=10,
        total_price=0.1,
        latency=1.0,
    )


async def _collect_stream_async(service, **kwargs):
    frames = []
    async for frame in service.stream_agent_events_async(**kwargs):
        frames.append(frame)
    return frames


class TestAppRuntimeServiceStreamAgentEventsAsync:
    """覆盖 stream_agent_events_async：agent.astream 消费、AGENT_MESSAGE 累积、SSE 帧格式。"""

    def _make_service(self, monkeypatch, agent):
        service = object.__new__(AppRuntimeService)
        service.language_model_service = None
        monkeypatch.setattr(service, "build_runtime_tools", lambda *args, **kwargs: [])
        monkeypatch.setattr(
            service,
            "create_runtime_agent",
            lambda *args, **kwargs: agent,
        )
        return service

    def test_should_yield_sse_frames_for_each_agent_thought(self, monkeypatch):
        event_id = uuid4()
        task_id = uuid4()
        agent = _FakeAsyncAgent([
            _thought(QueueEvent.AGENT_MESSAGE, answer="Hello ", event_id=event_id, task_id=task_id),
            _thought(QueueEvent.AGENT_END, event_id=event_id, task_id=task_id),
        ])
        service = self._make_service(monkeypatch, agent)
        llm = SimpleNamespace(convert_to_human_message=lambda query, image_urls: {"role": "user", "content": query})

        frames = asyncio.run(_collect_stream_async(
            service,
            app_id=uuid4(),
            account=SimpleNamespace(id=uuid4()),
            draft_app_config={},
            llm=llm,
            query="hello",
            image_urls=[],
            history=[],
            long_term_memory="",
        ))

        assert len(frames) == 2
        assert frames[0].startswith("event: agent_message\ndata:")
        assert frames[1].startswith("event: agent_end\ndata:")
        first_payload = json.loads(frames[0].split("data:", 1)[1].strip())
        assert first_payload["answer"] == "Hello "
        assert first_payload["task_id"] == str(task_id)
        assert first_payload["aggregate_total_token_count"] == 10

    def test_should_accumulate_message_chunks_with_same_event_id(self, monkeypatch):
        event_id = uuid4()
        task_id = uuid4()
        agent = _FakeAsyncAgent([
            _thought(QueueEvent.AGENT_MESSAGE, answer="Hello ", event_id=event_id, task_id=task_id),
            _thought(QueueEvent.AGENT_MESSAGE, answer="world", event_id=event_id, task_id=task_id),
        ])
        service = self._make_service(monkeypatch, agent)
        llm = SimpleNamespace(convert_to_human_message=lambda query, image_urls: {"role": "user", "content": query})
        agent_thoughts = {}

        frames = asyncio.run(_collect_stream_async(
            service,
            app_id=uuid4(),
            account=SimpleNamespace(id=uuid4()),
            draft_app_config={},
            llm=llm,
            query="hello",
            image_urls=[],
            history=[],
            long_term_memory="",
            agent_thoughts=agent_thoughts,
        ))

        assert len(frames) == 2
        first_payload = json.loads(frames[0].split("data:", 1)[1].strip())
        assert first_payload["answer"] == "Hello "
        second_payload = json.loads(frames[1].split("data:", 1)[1].strip())
        assert second_payload["answer"] == "world"
        assert len(agent_thoughts) == 1
        assert agent_thoughts[str(event_id)].answer == "Hello world"

    def test_should_skip_ping_from_accumulation_but_still_emit_frame(self, monkeypatch):
        event_id = uuid4()
        task_id = uuid4()
        agent = _FakeAsyncAgent([
            _thought(QueueEvent.PING, event_id=event_id, task_id=task_id),
            _thought(QueueEvent.AGENT_END, event_id=event_id, task_id=task_id),
        ])
        service = self._make_service(monkeypatch, agent)
        llm = SimpleNamespace(convert_to_human_message=lambda query, image_urls: {"role": "user", "content": query})

        frames = asyncio.run(_collect_stream_async(
            service,
            app_id=uuid4(),
            account=SimpleNamespace(id=uuid4()),
            draft_app_config={},
            llm=llm,
            query="hello",
            image_urls=[],
            history=[],
            long_term_memory="",
        ))

        assert len(frames) == 2
        ping_payload = json.loads(frames[0].split("data:", 1)[1].strip())
        assert ping_payload["event"] == "ping"
        end_payload = json.loads(frames[1].split("data:", 1)[1].strip())
        assert end_payload["aggregate_total_price"] == 0.1

    def test_should_merge_with_initial_agent_thoughts(self, monkeypatch):
        event_id = uuid4()
        task_id = uuid4()
        existing = _thought(QueueEvent.AGENT_MESSAGE, answer="prior ", event_id=event_id, task_id=task_id)
        agent = _FakeAsyncAgent([
            _thought(QueueEvent.AGENT_MESSAGE, answer="tail", event_id=event_id, task_id=task_id),
        ])
        service = self._make_service(monkeypatch, agent)
        llm = SimpleNamespace(convert_to_human_message=lambda query, image_urls: {"role": "user", "content": query})
        agent_thoughts = {str(event_id): existing}

        frames = asyncio.run(_collect_stream_async(
            service,
            app_id=uuid4(),
            account=SimpleNamespace(id=uuid4()),
            draft_app_config={},
            llm=llm,
            query="hello",
            image_urls=[],
            history=[],
            long_term_memory="",
            agent_thoughts=agent_thoughts,
        ))

        assert len(frames) == 1
        last_payload = json.loads(frames[0].split("data:", 1)[1].strip())
        assert last_payload["answer"] == "tail"
        assert agent_thoughts[str(event_id)].answer == "prior tail"
