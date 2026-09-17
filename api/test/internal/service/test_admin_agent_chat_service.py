"""管理端对话编排测试（设计 §6.1）。

用替身隔离真实 LLM 与 DB，只验证编排契约：
1. 身份：非属主/停用 Agent 直接拒绝（不进模型）；
2. 工具循环：LLM 请求工具 → 执行 → 回灌 → 产出最终答复；
3. 落库：user / assistant(tool_calls) / tool 三类消息都要落；
4. 上限保护：LLM 反复请求工具时中止，不无限循环。
"""
import json
from types import SimpleNamespace
from uuid import uuid4

import pytest

from internal.entity.admin_agent_entity import AdminAgentPrincipal, AutomationLevel
from internal.exception import FailException
from internal.service.admin_agent_chat_service import AdminAgentChatService


class _FakeTool:
    def __init__(self, name):
        self.name = name
        self.calls = []

    def invoke(self, args):
        self.calls.append(args)
        return json.dumps({"ok": True, "board": "builtin_tool", "outcome": "executed"})


class _FakeLLM:
    """按脚本产出若干轮 AI 消息，最后一轮不带 tool_calls。"""

    def __init__(self, scripted):
        self._scripted = list(scripted)
        self.bound_tools = []

    def bind_tools(self, tools):
        self.bound_tools = tools
        return self

    def invoke(self, messages):
        return self._scripted.pop(0)


def _principal():
    return AdminAgentPrincipal(
        admin_user_id=uuid4(),
        agent_id=uuid4(),
        agent_name="运维 Agent",
        effective_permissions=frozenset({"builtin_tool:read"}),
        automation_policy={"builtin_tool": AutomationLevel.AUTONOMOUS},
    )


def _service(principal, llm, tools):
    service = AdminAgentChatService.__new__(AdminAgentChatService)
    service.get_principal = lambda **kwargs: principal
    service._build_model = lambda: llm
    service._build_tools = lambda p: tools
    service._build_system_prompt = lambda p, prompt_key: "系统提示词"
    service._persist = []
    service.append_message = lambda **kwargs: service._persist.append(kwargs) or SimpleNamespace(id=uuid4())
    service._history_for = lambda conversation_id: []
    service._resolve_conversation = lambda **kwargs: SimpleNamespace(id=uuid4())
    # 必须一并替换 `_load_agent`：真实实现会经 AdminAgentService 触库
    service._load_agent = lambda agent_id, admin_user_id: SimpleNamespace(prompt_key=None)
    return service


def test_tool_loop_executes_tool_and_returns_answer():
    llm = _FakeLLM(
        [
            SimpleNamespace(content="", tool_calls=[{"name": "admin_builtin_tool", "args": {"action": "list"}, "id": "c1"}]),
            SimpleNamespace(content="已查看现状：1 个工具处于启用状态。", tool_calls=[]),
        ]
    )
    tool = _FakeTool("admin_builtin_tool")
    service = _service(_principal(), llm, [tool])

    frames = list(
        service.chat(
            agent_id=uuid4(),
            admin_user_id=uuid4(),
            admin_permissions=["builtin_tool:read"],
            query="看看内置工具现状",
        )
    )

    assert tool.calls == [{"action": "list"}]
    body = "".join(frames)
    assert "已查看现状" in body
    # 三类消息都要落库
    roles = [item["role"] for item in service._persist]
    assert roles == ["user", "tool", "assistant"]


def test_unknown_agent_raises_without_calling_model():
    service = _service(None, _FakeLLM([]), [])
    service.get_principal = lambda **kwargs: None

    with pytest.raises(FailException):
        list(
            service.chat(
                agent_id=uuid4(),
                admin_user_id=uuid4(),
                admin_permissions=[],
                query="hi",
            )
        )


def test_tool_loop_aborts_on_excessive_iterations():
    looping = [
        SimpleNamespace(content="", tool_calls=[{"name": "admin_builtin_tool", "args": {}, "id": f"c{i}"}])
        for i in range(20)
    ]
    service = _service(_principal(), _FakeLLM(looping), [_FakeTool("admin_builtin_tool")])

    with pytest.raises(FailException):
        list(
            service.chat(
                agent_id=uuid4(),
                admin_user_id=uuid4(),
                admin_permissions=["builtin_tool:read"],
                query="循环",
            )
        )
