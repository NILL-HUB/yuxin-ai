"""工具执行登记表专项测试（崩溃恢复时避免副作用重复执行）。"""
from __future__ import annotations

from types import SimpleNamespace
from uuid import uuid4

import pytest
from langchain_core.messages import AIMessage, ToolMessage

from internal.core.agent.entities.agent_entity import AgentConfig
from internal.core.agent.entities.queue_entity import QueueEvent
from internal.entity.conversation_entity import InvokeFrom

from test.internal.core.agent.test_function_call_and_react_agent import (
    _build_agent_config,
    _FakeQueueManager,
    _new_function_call_agent,
)


class _FakeRedis:
    """内存版 redis 客户端（支持工具登记表用到的 hset/hget/expire/delete）。"""

    def __init__(self):
        self.store: dict[str, dict[str, str]] = {}

    def hset(self, key, field, value):
        self.store.setdefault(key, {})[field] = value
        return 1

    def hget(self, key, field):
        return (self.store.get(key) or {}).get(field)

    def expire(self, _key, _seconds):
        return True

    def delete(self, key):
        self.store.pop(key, None)
        return 1


class _FakeQueueWithRedis(_FakeQueueManager):
    """带 redis_client 的队列管理器（登记表依赖 redis 客户端）。"""

    def __init__(self, redis_client):
        super().__init__()
        self.redis_client = redis_client


def _checkpoint_config(**overrides) -> AgentConfig:
    base = {
        "enable_checkpoint": True,
        "checkpoint_thread_id": "conv-reg-123",
    }
    base.update(overrides)
    return _build_agent_config(**base)


def _tool_cls(name, result=None, error=None, calls=None):
    class _Tool:
        def __init__(self, name, result=None, error=None):
            self.name = name
            self._result = result
            self._error = error

        def invoke(self, _args):
            if calls is not None:
                calls.append(name)
            if self._error:
                raise self._error
            return self._result

    return _Tool(name, result=result, error=error)


class TestToolExecutionRegistryUnit:
    """登记表纯函数单元测试。"""

    def test_mark_done_and_get_status(self):
        from internal.core.agent import tool_execution_registry as reg

        redis = _FakeRedis()
        reg.mark_done(redis, "thread-1", "call-1", "web_search", {"ok": True})
        record = reg.get_status(redis, "thread-1", "call-1")
        assert record["status"] == "done"
        assert record["result"] == {"ok": True}
        assert record["tool_name"] == "web_search"

    def test_mark_running_then_get_status(self):
        from internal.core.agent import tool_execution_registry as reg

        redis = _FakeRedis()
        reg.mark_running(redis, "thread-1", "call-1", "web_search", {"q": "x"})
        record = reg.get_status(redis, "thread-1", "call-1")
        assert record["status"] == "running"
        assert record["args"] == {"q": "x"}

    def test_get_status_missing_returns_none(self):
        from internal.core.agent import tool_execution_registry as reg

        redis = _FakeRedis()
        assert reg.get_status(redis, "thread-1", "no-such-call") is None

    def test_mark_unknown_and_cleanup(self):
        from internal.core.agent import tool_execution_registry as reg

        redis = _FakeRedis()
        reg.mark_running(redis, "thread-1", "call-1", "tool_a", {})
        reg.mark_unknown(redis, "thread-1", "call-1", "tool_a")
        assert reg.get_status(redis, "thread-1", "call-1")["status"] == "unknown"
        reg.cleanup_thread(redis, "thread-1")
        assert reg.get_status(redis, "thread-1", "call-1") is None

    def test_noop_without_redis(self):
        from internal.core.agent import tool_execution_registry as reg

        # 不抛异常即可
        reg.mark_done(None, "thread-1", "call-1", "t", "r")
        reg.mark_running(None, "thread-1", "call-1", "t", {})
        assert reg.get_status(None, "thread-1", "call-1") is None


class TestToolsNodeRegistryReplay:
    """tools_node 崩溃恢复：登记 done 的工具不重复执行，直接重放结果。"""

    def _build_agent_with_registry(self, redis_client, tools):
        agent = _new_function_call_agent(
            _SimpleLLM(),
            _checkpoint_config(tools=tools),
        )
        agent._agent_queue_manager = _FakeQueueWithRedis(redis_client)
        return agent

    def test_registered_done_tool_is_replayed_not_executed(self):
        from internal.core.agent import tool_execution_registry as reg

        redis = _FakeRedis()
        executed_calls: list[str] = []
        tools = [_tool_cls("web_search", result="fresh-result", calls=executed_calls)]
        agent = self._build_agent_with_registry(redis, tools)

        # 崩溃前该 tool_call 已执行完并登记 done
        reg.mark_done(redis, "conv-reg-123", "call_9", "web_search", "registered-result")

        ai_message = AIMessage(
            content="",
            tool_calls=[{"id": "call_9", "name": "web_search", "args": {"q": "ai"}}],
        )
        result = agent._tools_node({"task_id": uuid4(), "messages": [ai_message]})

        # 工具未被再次执行（副作用不重复）
        assert executed_calls == []
        # 重放的是登记的结果而非重新执行的结果
        tool_message = result["messages"][0]
        assert isinstance(tool_message, ToolMessage)
        assert tool_message.content == "registered-result"

    def test_registered_running_tool_becomes_verify_hint(self):
        from internal.core.agent import tool_execution_registry as reg

        redis = _FakeRedis()
        executed_calls: list[str] = []
        tools = [_tool_cls("web_search", result="fresh-result", calls=executed_calls)]
        agent = self._build_agent_with_registry(redis, tools)

        # 崩溃残留在 running：工具已发起但结果未知
        reg.mark_running(redis, "conv-reg-123", "call_7", "web_search", {"q": "x"})

        ai_message = AIMessage(
            content="",
            tool_calls=[{"id": "call_7", "name": "web_search", "args": {"q": "x"}}],
        )
        result = agent._tools_node({"task_id": uuid4(), "messages": [ai_message]})

        # 工具未被再次执行
        assert executed_calls == []
        # 返回"结果未知，请核实"提示而非盲目执行
        tool_message = result["messages"][0]
        assert isinstance(tool_message, ToolMessage)
        assert "结果未知" in tool_message.content
        assert "核实" in tool_message.content
        # running 被标记为 unknown（避免恢复重跑再次触发核实路径的重复判断）
        assert reg.get_status(redis, "conv-reg-123", "call_7")["status"] == "unknown"

    def test_unregistered_tool_executes_and_registers_done(self):
        from internal.core.agent import tool_execution_registry as reg

        redis = _FakeRedis()
        executed_calls: list[str] = []
        tools = [_tool_cls("web_search", result={"ok": True}, calls=executed_calls)]
        agent = self._build_agent_with_registry(redis, tools)

        ai_message = AIMessage(
            content="",
            tool_calls=[{"id": "call_new", "name": "web_search", "args": {"q": "x"}}],
        )
        result = agent._tools_node({"task_id": uuid4(), "messages": [ai_message]})

        # 工具正常执行一次
        assert executed_calls == ["web_search"]
        # 执行后登记 done
        record = reg.get_status(redis, "conv-reg-123", "call_new")
        assert record is not None
        assert record["status"] == "done"
        assert record["result"] == {"ok": True}

    def test_registry_disabled_without_checkpoint(self):
        """未启用 checkpoint 时登记表不生效（工具正常执行、无登记写入）。"""
        from internal.core.agent import tool_execution_registry as reg

        redis = _FakeRedis()
        executed_calls: list[str] = []
        tools = [_tool_cls("web_search", result="result", calls=executed_calls)]
        # enable_checkpoint=False（默认 config）
        agent = _new_function_call_agent(_SimpleLLM(), _build_agent_config(tools=tools))
        agent._agent_queue_manager = _FakeQueueWithRedis(redis)

        ai_message = AIMessage(
            content="",
            tool_calls=[{"id": "call_1", "name": "web_search", "args": {}}],
        )
        agent._tools_node({"task_id": uuid4(), "messages": [ai_message]})

        assert executed_calls == ["web_search"]
        # 登记表无写入
        assert reg.get_status(redis, "conv-reg-123", "call_1") is None


class _SimpleLLM:
    """tools_node 测试用的最小 LLM（仅需 get_pricing / features 等属性）。"""

    def __init__(self):
        self.features = []

    def get_pricing(self):
        return 0.0, 0.0, 0.0
