"""异步 Agent 执行链路测试：BaseAgent.astream/ainvoke + AgentQueueManager.alisten。"""
import asyncio
import sys
import types
from types import SimpleNamespace
from unittest.mock import MagicMock
from uuid import uuid4

# 构造 fake app.http.module 供 autouse fixture 注入（不在此处 setdefault，
# 避免污染 sys.modules 影响同进程其他测试文件；注入/恢复由 fixture 管理）。
_fake_http_module = types.ModuleType("app.http.module")
_fake_http_module.injector = SimpleNamespace(get=lambda cls: None)

import pytest
from langchain_core.messages import HumanMessage

from internal.core.agent.agents.agent_queue_manager import AgentQueueManager
from internal.core.agent.agents.base_agent import BaseAgent
from internal.core.agent.entities.agent_entity import AgentConfig
from internal.core.agent.entities.queue_entity import AgentThought, QueueEvent
from internal.core.language_model.entities.model_entity import BaseLanguageModel
from internal.entity.conversation_entity import InvokeFrom


@pytest.fixture(autouse=True)
def _inject_fake_http_module():
    """测试执行期间强制用 fake app.http.module 覆盖 sys.modules。

    代码在函数内动态 ``from app.http.module import injector``，只要 sys.modules
    中是 fake 即可生效。显式覆盖（而非仅 setdefault）可保证即使完整测试套件中
    test_asgi_app 等模块已先导入真实 app.http.module，本文件的隔离依然成立。
    """
    original = sys.modules.get("app.http.module")
    sys.modules["app.http.module"] = _fake_http_module
    yield
    if original is None:
        sys.modules.pop("app.http.module", None)
    else:
        sys.modules["app.http.module"] = original


class _FakeRedis:
    def __init__(self):
        self.store = {}
        self.setex_calls = []

    def get(self, key):
        return self.store.get(key)

    def setex(self, key, ttl, value):
        self.setex_calls.append((key, ttl, value))
        self.store[key] = value if isinstance(value, bytes) else str(value).encode("utf-8")


class _FakeInjector:
    def __init__(self, redis_client):
        self.redis_client = redis_client

    def get(self, _cls):
        return self.redis_client


class _FakeAsyncGraph:
    """模拟 LangGraph 编译图：async ainvoke 中发布 AGENT_MESSAGE + AGENT_END 事件。"""

    def __init__(self, queue_manager):
        self.queue_manager = queue_manager
        self.invoke_count = 0

    async def ainvoke(self, state, config=None):
        task_id = state["task_id"]
        await asyncio.sleep(0.01)
        self.invoke_count += 1
        self.queue_manager.publish(task_id, AgentThought(
            id=uuid4(),
            task_id=task_id,
            event=QueueEvent.AGENT_MESSAGE.value,
            thought="",
            answer="hello async",
            message=[],
            latency=0,
        ))
        self.queue_manager.publish(task_id, AgentThought(
            id=uuid4(),
            task_id=task_id,
            event=QueueEvent.AGENT_END.value,
        ))


_CURRENT_FAKE_GRAPH = None


class _FakeAsyncAgent(BaseAgent):
    """继承 BaseAgent，返回模拟异步图（fake graph 经模块级变量传入，避免 pydantic 私有属性时序问题）。"""

    def __init__(self, llm, agent_config, fake_graph):
        global _CURRENT_FAKE_GRAPH
        _CURRENT_FAKE_GRAPH = fake_graph
        super().__init__(llm=llm, agent_config=agent_config)

    def _build_agent(self):
        return _CURRENT_FAKE_GRAPH


def _make_agent(*, enable_checkpoint: bool = False) -> tuple[_FakeAsyncAgent, _FakeRedis]:
    redis_client = _FakeRedis()
    _fake_http_module.injector = _FakeInjector(redis_client)

    user_id = uuid4()
    fake_graph = _FakeAsyncGraph(None)
    agent = _FakeAsyncAgent(
        llm=MagicMock(spec=BaseLanguageModel),
        agent_config=AgentConfig(
            user_id=user_id,
            invoke_from=InvokeFrom.DEBUGGER.value,
            enable_checkpoint=enable_checkpoint,
        ),
        fake_graph=fake_graph,
    )
    fake_graph.queue_manager = agent.agent_queue_manager
    return agent, redis_client


def test_alisten_should_yield_async_published_events():
    redis_client = _FakeRedis()
    _fake_http_module.injector = _FakeInjector(redis_client)

    manager = AgentQueueManager(user_id=uuid4(), invoke_from=InvokeFrom.DEBUGGER.value)
    task_id = uuid4()

    async def _producer_and_consumer():
        async_q = manager._get_or_create_async_queue(task_id)
        events = []

        async def _consume():
            async for item in manager.alisten(task_id):
                events.append(item)

        consumer_task = asyncio.create_task(_consume())
        await asyncio.sleep(0.05)
        manager.publish(task_id, AgentThought(
            id=uuid4(), task_id=task_id, event=QueueEvent.AGENT_MESSAGE.value, answer="hi", message=[], latency=0,
        ))
        await asyncio.sleep(0.05)
        manager.publish(task_id, AgentThought(
            id=uuid4(), task_id=task_id, event=QueueEvent.AGENT_END.value,
        ))
        await asyncio.wait_for(consumer_task, timeout=2)
        return events

    events = asyncio.run(_producer_and_consumer())
    events = [e for e in events if e.event != QueueEvent.PING.value]
    assert len(events) == 2
    assert events[0].event == QueueEvent.AGENT_MESSAGE.value
    assert events[0].answer == "hi"
    assert events[1].event == QueueEvent.AGENT_END.value


def test_base_agent_astream_should_run_async_graph_and_yield_events():
    agent, _ = _make_agent()

    async def _run():
        collected = []
        async for item in agent.astream({
            "messages": [HumanMessage(content="hello")],
            "history": [],
        }):
            collected.append(item)
        return collected

    collected = asyncio.run(_run())
    collected = [e for e in collected if e.event != QueueEvent.PING.value]
    assert len(collected) == 2
    assert collected[0].event == QueueEvent.AGENT_MESSAGE.value
    assert collected[0].answer == "hello async"
    assert collected[1].event == QueueEvent.AGENT_END.value
    assert _CURRENT_FAKE_GRAPH.invoke_count == 1


def test_base_agent_ainvoke_should_merge_events():
    agent, _ = _make_agent()

    async def _run():
        return await agent.ainvoke({
            "messages": [HumanMessage(content="hello")],
            "history": [],
        })

    result = asyncio.run(_run())
    assert result.answer == "hello async"
    assert result.status != QueueEvent.ERROR.value
    assert len(result.agent_thoughts) == 2  # AGENT_MESSAGE + AGENT_END（与同步 invoke 语义一致）


def test_base_agent_astream_should_raise_when_agent_missing():
    redis_client = _FakeRedis()
    _fake_http_module.injector = _FakeInjector(redis_client)
    agent = _FakeAsyncAgent(
        llm=MagicMock(spec=BaseLanguageModel),
        agent_config=AgentConfig(user_id=uuid4(), invoke_from=InvokeFrom.DEBUGGER.value),
        fake_graph=None,
    )
    # _build_agent 返回 None 时 _agent 为空，astream 应抛出 FailException
    from internal.exception import FailException
    with pytest.raises(FailException):
        asyncio.run(agent.astream({"messages": [HumanMessage(content="hi")], "history": []}).__anext__())


def test_resolve_checkpoint_config_should_fill_thread_id_when_enabled():
    agent, _ = _make_agent(enable_checkpoint=True)

    # 未传 config 时自动生成 thread_id
    resolved = agent._resolve_checkpoint_config(None)
    assert resolved is not None
    assert resolved["configurable"]["thread_id"]

    # 调用方传入 thread_id 时原样保留
    explicit = {"configurable": {"thread_id": "thread-abc"}}
    resolved2 = agent._resolve_checkpoint_config(explicit)
    assert resolved2["configurable"]["thread_id"] == "thread-abc"


def test_resolve_checkpoint_config_should_pass_through_when_disabled():
    agent, _ = _make_agent(enable_checkpoint=False)
    assert agent._resolve_checkpoint_config(None) is None
    config = {"configurable": {"thread_id": "x"}}
    assert agent._resolve_checkpoint_config(config) is config
