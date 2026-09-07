"""进程级 checkpoint 专项测试。

覆盖「Agent 执行中途进程崩溃 → 同一会话（thread_id）续跑」的核心语义：
- LangGraph checkpoint 在节点边界保存：已执行完的工具轮/LLM 轮不重放
- 崩溃后 checkpoint 留有 pending 节点；续跑从 pending 继续，用户可见内容不重复
- BaseAgent.has_pending_checkpoint / resume 的接线行为
- 同步 RedisSaver 工厂的异常降级（Redis 不可用 / 缺 RediSearch 时返回 None）
"""
from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import Literal
from uuid import uuid4

import pytest
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, MessagesState, StateGraph

from internal.core.agent.entities.agent_entity import AgentConfig
from internal.core.agent.entities.queue_entity import QueueEvent
from internal.entity.conversation_entity import InvokeFrom


def _build_config(**overrides) -> AgentConfig:
    base = {
        "user_id": uuid4(),
        "invoke_from": InvokeFrom.WEB_APP,
        "enable_checkpoint": True,
        "checkpoint_thread_id": "conv-test-123",
        "preset_prompt": "preset",
        "max_iteration_count": 10,
        "tools": [],
    }
    base.update(overrides)
    return AgentConfig.model_construct(**base)


def _build_crash_graph(crash_after_ai_round: int = 1):
    """构造一个 llm⇄tools 循环图；在指定 AI 轮后抛异常模拟进程崩溃。

    - round 0: llm 返回带 tool_call 的 AI message
    - tools: 执行工具并返回 ToolMessage
    - round 1: llm 在 crash_after_ai_round=1 时崩溃（此时工具已执行完）
    - round >= 2: 返回最终文本
    """
    executed: list[str] = []
    crash_armed = {"v": True}

    def llm_node(state):
        ai_count = len([m for m in state["messages"] if getattr(m, "type", "") == "ai"])
        executed.append("llm")
        if ai_count == crash_after_ai_round and crash_armed["v"]:
            crash_armed["v"] = False
            raise RuntimeError("SIMULATED_PROCESS_CRASH")
        if ai_count == 0:
            return {
                "messages": [
                    AIMessage(
                        content="need-tool",
                        tool_calls=[
                            {"name": "fake_tool", "args": {}, "id": "call_1", "type": "tool_call"}
                        ],
                    )
                ]
            }
        return {"messages": [AIMessage(content=f"final-answer-after-{ai_count}-rounds")]}

    def tools_node(state):
        executed.append("tool")
        return {"messages": [ToolMessage(content="tool-result", tool_call_id="call_1")]}

    def cond(state) -> Literal["tools", "__end__"]:
        last = state["messages"][-1]
        if getattr(last, "tool_calls", None):
            return "tools"
        return END

    graph = StateGraph(MessagesState)
    graph.add_node("llm", llm_node)
    graph.add_node("tools", tools_node)
    graph.add_conditional_edges("llm", cond)
    graph.add_edge("tools", "llm")
    graph.set_entry_point("llm")
    return graph, executed


class TestCheckpointCrashResumeSemantics:
    """LangGraph checkpoint 崩溃续跑语义（与存储无关，用 MemorySaver 验证）。"""

    def test_crash_then_resume_does_not_replay_tool_and_keeps_context(self):
        graph, executed = _build_crash_graph(crash_after_ai_round=1)
        saver = MemorySaver()
        app = graph.compile(checkpointer=saver)
        cfg = {"configurable": {"thread_id": "conv-123"}}

        # run 1：llm → tool → llm(崩溃)
        with pytest.raises(RuntimeError, match="SIMULATED_PROCESS_CRASH"):
            asyncio.run(app.ainvoke({"messages": [HumanMessage(content="hi")]}, cfg))

        assert executed == ["llm", "tool", "llm"]

        # checkpoint 保留已执行上下文（含工具结果），且有 pending 节点
        snapshot = app.get_state(cfg)
        assert snapshot.next == ("llm",)
        contents = [getattr(m, "content", m) for m in snapshot.values["messages"]]
        assert contents == ["hi", "need-tool", "tool-result"]

        # resume：同 thread，ainvoke(None) 从 pending 继续
        executed.clear()
        result = asyncio.run(app.ainvoke(None, cfg))
        # 工具不重放：续跑只执行了 llm（产出最终答案）
        assert executed == ["llm"]
        final_contents = [getattr(m, "content", m) for m in result["messages"]]
        assert final_contents[-1] == "final-answer-after-1-rounds"
        # 上下文无重复：工具结果只出现一次
        assert final_contents.count("tool-result") == 1
        assert final_contents.count("need-tool") == 1

    def test_no_pending_after_completion(self):
        """正常跑完的 thread 没有 pending 节点，无需续跑。"""
        graph, executed = _build_crash_graph(crash_after_ai_round=999)  # 永不崩溃
        saver = MemorySaver()
        app = graph.compile(checkpointer=saver)
        cfg = {"configurable": {"thread_id": "conv-ok"}}

        result = asyncio.run(app.ainvoke({"messages": [HumanMessage(content="hi")]}, cfg))
        snapshot = app.get_state(cfg)
        assert snapshot.next == ()
        assert result["messages"][-1].content == "final-answer-after-1-rounds"


class _FakeQueueManager:
    def __init__(self):
        self.published = []
        self.failures = []

    def publish(self, task_id, thought):
        self.published.append(thought)

    def publish_failure(self, task_id, error, context=""):
        self.failures.append(error)


class _DummyAgent:
    """构造一个可挂 MemorySaver 的假编译图，供 BaseAgent 方法测试。"""

    def __init__(self, saver, crash_on_run=False):
        self._saver = saver
        self._crash = crash_on_run
        self._thread_id = None

    @property
    def checkpointer(self):
        return self._saver

    def _resolve_checkpoint_config(self, config):
        return config


class TestBaseAgentCheckpointHooks:
    """BaseAgent.has_pending_checkpoint 的判定接线。"""

    def test_has_pending_checkpoint_false_when_checkpoint_disabled(self, monkeypatch):
        from internal.core.agent.agents.function_call_agent import FunctionCallAgent

        agent = FunctionCallAgent.model_construct(
            llm=SimpleNamespace(),
            agent_config=_build_config(enable_checkpoint=False),
        )
        # 编译图无 checkpointer
        agent._agent = _DummyAgent(MemorySaver())
        assert agent.has_pending_checkpoint() is False

    def test_has_pending_checkpoint_false_without_stable_thread(self, monkeypatch):
        from internal.core.agent.agents.function_call_agent import FunctionCallAgent

        agent = FunctionCallAgent.model_construct(
            llm=SimpleNamespace(),
            agent_config=_build_config(checkpoint_thread_id=""),
        )
        agent._agent = _DummyAgent(MemorySaver())
        assert agent.has_pending_checkpoint() is False

    def test_has_pending_checkpoint_true_after_crash(self):
        """崩溃后 thread 有 pending 节点 → has_pending_checkpoint 为 True。"""
        from internal.core.agent.agents.function_call_agent import FunctionCallAgent

        graph, _ = _build_crash_graph(crash_after_ai_round=1)
        saver = MemorySaver()
        app = graph.compile(checkpointer=saver)
        cfg = {"configurable": {"thread_id": "conv-123"}}

        with pytest.raises(RuntimeError):
            asyncio.run(app.ainvoke({"messages": [HumanMessage(content="hi")]}, cfg))

        agent = FunctionCallAgent.model_construct(
            llm=SimpleNamespace(),
            agent_config=_build_config(checkpoint_thread_id="conv-123"),
        )
        agent._agent = _DummyAgent(saver)
        assert agent.has_pending_checkpoint() is True


class TestCheckpointerFactoryDegradation:
    """checkpointer 工厂异常降级：Redis 不可用 / 缺 RediSearch 时不阻塞执行。"""

    def test_get_async_checkpointer_returns_none_on_failure(self, monkeypatch):
        from internal.core.agent import checkpointer

        # 重置单例缓存
        monkeypatch.setattr(checkpointer, "_async_redis_saver_attempted", False)
        monkeypatch.setattr(checkpointer, "_async_redis_saver", None)

        # 模拟 Redis 不可用：让 saver 构造抛异常（连接失败 / 缺 RediSearch）
        class _BoomSaver:
            def __init__(self, *a, **k):
                raise RuntimeError("Redis unavailable / no RediSearch")

        monkeypatch.setattr(checkpointer, "LoopAwareAsyncRedisSaver", _BoomSaver)

        # get_sync_checkpointer 委托 get_async_checkpointer，同样降级为 None
        assert checkpointer.get_async_checkpointer() is None
        assert checkpointer.get_sync_checkpointer() is None
