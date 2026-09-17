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
from internal.service.admin_agent_chat_service import (
    MAX_TOOL_ITERATIONS,
    AdminAgentChatService,
)


class _FakeTool:
    def __init__(self, name):
        self.name = name
        self.calls = []

    def invoke(self, args):
        self.calls.append(args)
        return json.dumps({"ok": True, "board": "builtin_tool", "outcome": "executed"})


def _validation_error() -> Exception:
    """构造一个真实的 pydantic `ValidationError`（入参不合法）。"""
    from pydantic import BaseModel, ValidationError

    class _Args(BaseModel):
        action: str

    try:
        _Args()  # 缺必填字段
    except ValidationError as exc:
        return exc
    raise AssertionError("应当抛出 ValidationError")


class _GuidanceTool:
    """入参缺 ``action`` 时抛 `ValidationError`（模拟 `_run` 之前的校验），

    入参合法时正常返回——用于验证模型能在同一轮内据可读 error 改正重试。
    """

    def __init__(self, name):
        self.name = name
        self.calls = []

    def invoke(self, args):
        self.calls.append(args)
        if not (args or {}).get("action"):
            raise _validation_error()
        return json.dumps({"ok": True, "board": "builtin_tool", "outcome": "executed"})


class _FakeLLM:
    """按脚本产出若干轮 AI 消息，最后一轮不带 tool_calls。"""

    def __init__(self, scripted):
        self._scripted = list(scripted)
        self.bound_tools = []
        self.invocations = []

    def bind_tools(self, tools):
        self.bound_tools = tools
        return self

    def invoke(self, messages):
        self.invocations.append(messages)
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


def test_unknown_agent_reports_error_frame_without_calling_model():
    """未知 Agent：不调模型，且以 error 帧结束（不逃出生成器）。"""
    llm = _FakeLLM([])
    service = _service(None, llm, [])
    service.get_principal = lambda **kwargs: None

    frames = list(
        service.chat(
            agent_id=uuid4(),
            admin_user_id=uuid4(),
            admin_permissions=[],
            query="hi",
        )
    )

    body = "".join(frames)
    assert "event: error" in body
    assert "不存在" in body or "不可用" in body
    assert llm.invocations == [], "未知 Agent 不得调用模型"


def test_tool_loop_aborts_on_excessive_iterations():
    looping = [
        SimpleNamespace(content="", tool_calls=[{"name": "admin_builtin_tool", "args": {}, "id": f"c{i}"}])
        for i in range(20)
    ]
    llm = _FakeLLM(looping)
    service = _service(_principal(), llm, [_FakeTool("admin_builtin_tool")])

    frames = list(
        service.chat(
            agent_id=uuid4(),
            admin_user_id=uuid4(),
            admin_permissions=["builtin_tool:read"],
            query="循环",
        )
    )

    body = "".join(frames)
    assert "event: error" in body
    assert str(MAX_TOOL_ITERATIONS) in body
    assert llm.invocations and len(llm.invocations) <= MAX_TOOL_ITERATIONS + 1


def test_build_tools_wires_execution_service_that_has_run():
    """D1 唯一自动防线：真实装配出的工具必须持有**有 `run` 的执行服务**。

    历史缺陷：`_build_tools` 曾把 `BoardToolExecutor()` 当 `execution_service`
    传入，而它只有 `assert_allowed` / `requires_draft` / `execute`，**没有
    `run`**；`chat_tools` 调用 `self.execution_service.run(...)` 会抛
    `AttributeError`，任何工具调用都让整轮对话以 error 帧结束。
    """
    from internal.service.admin_agent_execution_service import (
        AdminAgentExecutionService,
    )

    service = AdminAgentChatService.__new__(AdminAgentChatService)
    service.db = SimpleNamespace(session=object())

    tools = service._build_tools(_principal())

    assert tools, "必须装配出至少一个板块工具"
    for tool in tools:
        assert isinstance(tool.execution_service, AdminAgentExecutionService)
        assert callable(getattr(tool.execution_service, "run", None))


def test_model_build_failure_emits_error_frame_without_raising():
    """D2：构造阶段异常必须转成 `event: error` 帧，不得逃出 SSE 生成器。

    `_build_model` 在公共 AI 配置关闭本 feature 时抛 `FailException`；若它
    位于 try 之外，异常会逃出生成器（客户端断流、拿不到 error 帧）。
    """
    service = _service(_principal(), _FakeLLM([]), [])

    def _boom():
        raise FailException("公共 AI 配置未启用 admin_agent")

    service._build_model = _boom

    frames = list(
        service.chat(
            agent_id=uuid4(),
            admin_user_id=uuid4(),
            admin_permissions=["builtin_tool:read"],
            query="hi",
        )
    )

    body = "".join(frames)
    assert "event: error" in body


def test_history_for_pairs_tool_calls_with_tool_messages(monkeypatch):
    """D3：TOOL 行必须还原为「AIMessage(tool_calls) + ToolMessage」成对结构。

    历史缺陷：TOOL 行曾被还原为**孤立**的 `ToolMessage`（前面没有携同 id
    `tool_calls` 的 `AIMessage`），多轮续聊会被 OpenAI 兼容接口 4xx 拒收。
    """
    from langchain_core.messages import AIMessage, ToolMessage

    import internal.service.admin_agent_conversation_service as conversations

    rows = [
        SimpleNamespace(role="user", content="看看内置工具", tool_calls=[]),
        SimpleNamespace(
            role="tool",
            content='{"call": ...}',
            tool_calls=[
                {
                    "call": {"name": "admin_builtin_tool", "args": {"action": "list"}, "id": "c1"},
                    "result": '{"ok": true}',
                },
                {
                    "call": {"name": "admin_builtin_tool", "args": {"action": "list"}, "id": "c2"},
                    "result": '{"ok": true}',
                },
            ],
        ),
        # assistant 行带 tool_calls，但还原时必须**只还原文本**（不得产生悬空 tool_calls）
        SimpleNamespace(
            role="assistant",
            content="已查看现状。",
            tool_calls=[
                {"name": "admin_builtin_tool", "args": {"action": "list"}, "id": "c1"},
                {"name": "admin_builtin_tool", "args": {"action": "list"}, "id": "c2"},
            ],
        ),
    ]

    class _StubConversations:
        def __init__(self, db):
            self.db = db

        def list_messages(self, *, conversation_id):
            return rows

    monkeypatch.setattr(
        conversations, "AdminAgentConversationService", _StubConversations
    )

    service = AdminAgentChatService.__new__(AdminAgentChatService)
    service.db = object()

    history = service._history_for(uuid4())

    answered_ids: set[str] = set()
    for message in history:
        if isinstance(message, AIMessage):
            for call in message.tool_calls or []:
                answered_ids.add(call.get("id"))
        elif isinstance(message, ToolMessage):
            assert message.tool_call_id in answered_ids, (
                f"孤立 ToolMessage：{message.tool_call_id} 无前置 AIMessage"
            )

    assert [m.tool_call_id for m in history if isinstance(m, ToolMessage)] == ["c1", "c2"]


def test_permission_error_from_principal_skips_model():
    """非属主：`get_principal` 抛 `PermissionError` 时模型**零调用**，且转 error 帧。

    该异常来自身份解析阶段（try 内的第一步）。必须转成 error 帧而非逃出
    生成器——否则会被 `support._sse_response` 的通用兜底改写成另一套结构。
    """
    llm = _FakeLLM([])
    service = _service(None, llm, [])

    def _deny(**kwargs):
        raise PermissionError("Agent 不存在或非属主")

    service.get_principal = _deny

    frames = list(
        service.chat(
            agent_id=uuid4(),
            admin_user_id=uuid4(),
            admin_permissions=[],
            query="hi",
        )
    )

    body = "".join(frames)
    assert "event: error" in body
    assert "非属主" in body
    assert llm.invocations == [], "非属主不得调用模型"


def test_invalid_tool_args_do_not_break_chat_and_model_can_recover():
    """I-1：工具入参校验失败（`ValidationError`，逃出 `_run`）不得中断对话。

    历史上该异常会穿透工具边界 → chat 的 `except Exception` → 整轮以
    "对话失败" error 帧结束，模型失去自我纠正机会。修复后同一轮里模型应能
    看到可读 error 结果并改正重试，最终仍产出 answer。
    """
    llm = _FakeLLM(
        [
            # 第一次：入参非法（缺 action）→ 工具抛 ValidationError
            SimpleNamespace(content="", tool_calls=[{"name": "admin_builtin_tool", "args": {}, "id": "c1"}]),
            # 第二次：模型据 error 结果改正后重试成功
            SimpleNamespace(content="", tool_calls=[{"name": "admin_builtin_tool", "args": {"action": "list"}, "id": "c2"}]),
            SimpleNamespace(content="已按合法入参重试完成。", tool_calls=[]),
        ]
    )
    invalid_tool = _GuidanceTool("admin_builtin_tool")
    service = _service(_principal(), llm, [invalid_tool])

    frames = list(
        service.chat(
            agent_id=uuid4(),
            admin_user_id=uuid4(),
            admin_permissions=["builtin_tool:read"],
            query="先给个坏入参",
        )
    )

    body = "".join(frames)
    # 对话不中断：不出现链路级"对话失败"error 帧，且最终答案照常产出
    assert "对话失败" not in body
    assert "event: answer" in body
    assert "已按合法入参重试完成。" in body
    # 工具结果里带可读 error（模型据此改正）
    tool_messages = [item for item in service._persist if item["role"] == "tool"]
    assert tool_messages, "工具调用必须落库"
    assert "入参不合法" in tool_messages[0]["content"]
    assert llm.invocations, "模型必须被继续调用以纠正重试"


def test_tool_loop_still_works_with_valid_and_missing_tools():
    """回归：合法工具与未知工具路径仍按原语义产出 tool 事件。"""
    llm = _FakeLLM(
        [
            SimpleNamespace(
                content="",
                tool_calls=[
                    {"name": "admin_builtin_tool", "args": {"action": "list"}, "id": "c1"},
                    {"name": "admin_nope", "args": {}, "id": "c2"},
                ],
            ),
            SimpleNamespace(content="完成。", tool_calls=[]),
        ]
    )
    tool = _FakeTool("admin_builtin_tool")
    service = _service(_principal(), llm, [tool])

    frames = list(
        service.chat(
            agent_id=uuid4(),
            admin_user_id=uuid4(),
            admin_permissions=["builtin_tool:read"],
            query="混合调用",
        )
    )

    body = "".join(frames)
    assert body.count("event: tool") == 2
    assert "未知工具" in body
    assert "完成。" in body


def test_resume_rejects_conversation_of_another_agent():
    """M-3：续聊必须校验会话属于当前 Agent，否则以 error 帧结束。"""

    class _StubConversations:
        def __init__(self, db):
            self.db = db

        def get_conversation(self, conversation_id, *, admin_user_id):
            return SimpleNamespace(id=conversation_id, admin_agent_id=uuid4())

    import internal.service.admin_agent_conversation_service as conversations

    original = conversations.AdminAgentConversationService
    conversations.AdminAgentConversationService = _StubConversations
    try:
        llm = _FakeLLM([])
        service = AdminAgentChatService.__new__(AdminAgentChatService)
        service.db = object()
        service.get_principal = lambda **kwargs: _principal()
        service._build_model = lambda: llm
        service._build_tools = lambda p: []
        service._build_system_prompt = lambda p, prompt_key: "系统提示词"
        service._load_agent = lambda agent_id, admin_user_id: SimpleNamespace(prompt_key=None)

        frames = list(
            service.chat(
                agent_id=uuid4(),
                admin_user_id=uuid4(),
                admin_permissions=["builtin_tool:read"],
                query="续聊别的 Agent 的会话",
                conversation_id=uuid4(),
            )
        )
    finally:
        conversations.AdminAgentConversationService = original

    body = "".join(frames)
    assert "event: error" in body
    assert "不属于该 Agent" in body
    assert llm.invocations == [], "会话归属不匹配不得调用模型"
