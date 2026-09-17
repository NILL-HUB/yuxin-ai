"""管理端 Agent 对话编排（设计 §6.1：新建独立链路）。

链路：解析 principal（三重交集实时重算）→ 取/建会话 → 落 user 消息 →
构造系统提示词 → 装配板块工具 → 工具循环 → 落库 → SSE 帧。

为什么手写循环而不用用户端 `FunctionCallAgent`：后者依赖用户域
`AgentConfig` + `app/account` 上下文与 LangGraph 状态机（含知识库、记忆、
确认流等用户域节点）。复用会把用户域语义带进管理端链路，而设计 §6.1 的
前提正是"两条链路不交叉"。此处只需要「LLM ⇄ 板块工具」两节点，故显式实现
并有轮次上限保护。

SSE 帧格式与用户端一致（`event: <name>\ndata:<json>\n\n`），便于复用
`support._sse_response`。
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Any, Generator

from injector import inject

from internal.entity.admin_agent_chat_entity import (
    AdminAgentChatEvent,
    AdminAgentMessageRole,
)
from internal.entity.admin_agent_entity import AdminAgentPrincipal
from internal.exception import FailException
from pkg.sqlalchemy import SQLAlchemy

logger = logging.getLogger(__name__)

# 工具循环上限：防 LLM 陷入"反复调同一工具"烧钱（预算闸门属 P4）
MAX_TOOL_ITERATIONS = 6

FEATURE_KEY = "admin_agent"


# 必须带 @inject（否则 `a._get_service(AdminAgentChatService)` 运行时 CallError）
@inject
@dataclass
class AdminAgentChatService:
    db: SQLAlchemy

    # ------------------------------------------------------------------
    # 主链路
    # ------------------------------------------------------------------

    def chat(
        self,
        *,
        agent_id,
        admin_user_id,
        admin_permissions,
        query: str,
        conversation_id=None,
    ) -> Generator[str, None, None]:
        """执行一轮对话，逐帧 yield SSE 字符串。"""
        text = str(query or "").strip()
        if not text:
            yield self._frame(AdminAgentChatEvent.ERROR, {"error": "消息不能为空"})
            return

        principal = self.get_principal(
            agent_id=agent_id,
            admin_user_id=admin_user_id,
            admin_permissions=admin_permissions,
        )
        if principal is None:
            raise FailException("Agent 不存在或不可用")

        conversation = self._resolve_conversation(
            admin_agent_id=principal.agent_id,
            admin_user_id=admin_user_id,
            conversation_id=conversation_id,
            title=text[:50],
        )
        yield self._frame(
            AdminAgentChatEvent.MESSAGE, {"conversation_id": str(conversation.id)}
        )

        self.append_message(
            conversation_id=conversation.id, role=AdminAgentMessageRole.USER.value, content=text
        )

        # D2：Agent 加载、工具装配、提示词构造、模型获取**全部**纳入 try。
        # 这些步骤任一抛错（如提示词缺失、公共 AI 配置关闭了本 feature）都必须
        # 转成 `event: error` 帧回给客户端，而不是**逃出 SSE 生成器**——逃出的
        # 异常会被 `support._sse_response` 的通用兜底改用另一套 payload 结构，
        # 本链路的 error 帧契约（`{"error": ...}`）就此丢失，客户端表现为断流。
        in_tool_loop = False
        try:
            agent = self._load_agent(principal.agent_id, admin_user_id)
            tools = self._build_tools(principal)
            system_prompt = self._build_system_prompt(
                principal, getattr(agent, "prompt_key", None)
            )
            llm = self._build_model()
            in_tool_loop = True
            answer, tool_events = self._run_tool_loop(
                llm=llm,
                system_prompt=system_prompt,
                history=self._history_for(conversation.id),
                tools=tools,
                on_tool=lambda event: self.append_message(
                    conversation_id=conversation.id,
                    role=AdminAgentMessageRole.TOOL.value,
                    content=json.dumps(event, ensure_ascii=False),
                    tool_calls=[event],
                ),
            )
        except FailException as exc:
            yield self._frame(AdminAgentChatEvent.ERROR, {"error": str(exc)})
            # 构造阶段失败已由 error 帧完整告知客户端（不逃出生成器）；工具循环
            # 内部失败（如超过轮次上限）仍需上抛，让调用方感知这轮未产出答复。
            if in_tool_loop:
                raise
            return
        except Exception as exc:
            logger.exception("管理端 Agent 对话失败 agent_id=%s", principal.agent_id)
            yield self._frame(AdminAgentChatEvent.ERROR, {"error": f"对话失败：{exc}"})
            return

        for event in tool_events:
            yield self._frame(AdminAgentChatEvent.TOOL, event)

        self.append_message(
            conversation_id=conversation.id,
            role=AdminAgentMessageRole.ASSISTANT.value,
            content=answer,
            tool_calls=[e["call"] for e in tool_events],
        )
        yield self._frame(AdminAgentChatEvent.ANSWER, {"answer": answer})
        yield self._frame(AdminAgentChatEvent.END, {})

    # ------------------------------------------------------------------
    # 工具循环
    # ------------------------------------------------------------------

    def _run_tool_loop(self, *, llm, system_prompt: str, history, tools, on_tool) -> tuple[str, list[dict]]:
        from langchain_core.messages import SystemMessage, ToolMessage

        messages: list[Any] = [SystemMessage(content=system_prompt), *history]
        tools_by_name = {tool.name: tool for tool in tools}
        bound = llm.bind_tools(tools) if tools else llm
        tool_events: list[dict] = []

        for _ in range(MAX_TOOL_ITERATIONS):
            ai = bound.invoke(messages)
            messages.append(ai)
            calls = list(getattr(ai, "tool_calls", None) or [])
            if not calls:
                return str(getattr(ai, "content", "") or ""), tool_events

            for call in calls:
                name = str(call.get("name") or "")
                tool = tools_by_name.get(name)
                if tool is None:
                    result = json.dumps({"ok": False, "error": f"未知工具：{name}"}, ensure_ascii=False)
                else:
                    result = tool.invoke(call.get("args") or {})
                event = {
                    "call": {"name": name, "args": call.get("args") or {}, "id": call.get("id") or ""},
                    "result": result,
                }
                tool_events.append(event)
                on_tool(event)
                messages.append(
                    ToolMessage(
                        content=result,
                        tool_call_id=call.get("id") or "",
                        name=name,
                    )
                )
        raise FailException(
            f"Agent 工具调用超过 {MAX_TOOL_ITERATIONS} 轮仍未收敛，已中止（疑似循环）"
        )

    # ------------------------------------------------------------------
    # 可替换点（测试替换，避免真实 LLM / DB / 提示词）
    # ------------------------------------------------------------------

    def _build_model(self):
        from internal.service.language_model_service import LanguageModelService

        return LanguageModelService.get_feature_model(FEATURE_KEY)

    def _build_tools(self, principal: AdminAgentPrincipal):
        from internal.service.admin_agent_board_tools import BoardToolExecutor
        from internal.service.admin_agent_chat_tools import build_board_tools
        from internal.service.admin_agent_execution_service import (
            AdminAgentExecutionService,
        )

        # 协作者必须是 **AdminAgentExecutionService**（有 `run(principal,
        # board=, action=, payload=)`），不是 `BoardToolExecutor`（只有
        # `assert_allowed` / `requires_draft` / `execute`，**没有 `run`**）。
        # 传错会在第一次工具调用时抛 AttributeError，使整轮对话以 error 帧结束。
        execution = AdminAgentExecutionService(
            board_executor=BoardToolExecutor(),
            draft_service=self._build_draft_service(),
            audit_log_service=self._build_audit_service(),
        )
        return build_board_tools(execution, principal)

    def _build_draft_service(self):
        from internal.service.admin_change_draft_service import (
            AdminChangeDraftService,
        )

        return AdminChangeDraftService(db=self.db)

    def _build_audit_service(self):
        from internal.service.audit_log_service import AuditLogService

        # 实读签名：`__init__(self, session=None)`——**不接收 `db=`**。显式传
        # 注入的 `self.db.session`（与 `session=None` 回落到全局 `db.session`
        # 是同一 scoped session，但显式传参可测、不依赖全局单例的惰性初始化）。
        return AuditLogService(session=self.db.session)

    def _build_system_prompt(self, principal: AdminAgentPrincipal, prompt_key) -> str:
        from internal.service.admin_agent_prompt_service import AdminAgentPromptService

        return AdminAgentPromptService().build_system_prompt(
            principal, prompt_key=prompt_key
        )

    def get_principal(self, *, agent_id, admin_user_id, admin_permissions):
        from internal.service.admin_agent_service import AdminAgentService

        return AdminAgentService(db=self.db).get_principal(
            agent_id=agent_id,
            admin_user_id=admin_user_id,
            admin_permissions=admin_permissions,
        )

    def append_message(self, *, conversation_id, role, content="", tool_calls=None):
        from internal.service.admin_agent_conversation_service import (
            AdminAgentConversationService,
        )

        return AdminAgentConversationService(self.db).append_message(
            conversation_id=conversation_id,
            role=role,
            content=content,
            tool_calls=tool_calls,
        )

    def _resolve_conversation(self, *, admin_agent_id, admin_user_id, conversation_id, title):
        """取既有会话（校验归属）或新建会话。"""
        from internal.service.admin_agent_conversation_service import (
            AdminAgentConversationService,
        )

        conversations = AdminAgentConversationService(self.db)
        if conversation_id:
            return conversations.get_conversation(
                conversation_id, admin_user_id=admin_user_id
            )
        return conversations.create_conversation(
            admin_agent_id=admin_agent_id, admin_user_id=admin_user_id, title=title
        )

    def _load_agent(self, agent_id, admin_user_id):
        from internal.service.admin_agent_service import AdminAgentService

        return AdminAgentService(db=self.db).get_agent(
            agent_id=agent_id, admin_user_id=admin_user_id
        )

    def _history_for(self, conversation_id):
        """把已落库的消息还原为 LangChain 消息序列（供多轮上下文）。"""
        from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

        from internal.service.admin_agent_conversation_service import (
            AdminAgentConversationService,
        )

        rows = AdminAgentConversationService(self.db).list_messages(
            conversation_id=conversation_id
        )
        history: list[Any] = []
        for row in rows:
            if row.role == AdminAgentMessageRole.USER.value:
                history.append(HumanMessage(content=row.content or ""))
            elif row.role == AdminAgentMessageRole.ASSISTANT.value:
                # 只还原文本答复，**不带** tool_calls：本轮的工具调用已由下面的
                # TOOL 行还原为「前置 AIMessage(tool_calls) + ToolMessage」。
                # 若在此再挂 tool_calls，会形成「没有对应 ToolMessage 的悬空
                # tool_calls」——协议非法，下一轮续聊会被 OpenAI 兼容接口 4xx 拒收。
                history.append(AIMessage(content=row.content or ""))
            elif row.role == AdminAgentMessageRole.TOOL.value and row.tool_calls:
                # 每个 TOOL 行承载 {call, result}。按 LLM 协议**成对**还原：
                # 先补一条携 tool_calls 的 AIMessage，再补对应的 ToolMessage。
                # 孤立 ToolMessage（前面无携同 id tool_calls 的 AIMessage）会被
                # OpenAI 兼容接口 4xx 拒收，多轮续聊直接失败。
                for item in row.tool_calls:
                    call = item.get("call") or {}
                    history.append(
                        AIMessage(
                            content="",
                            tool_calls=[
                                {
                                    "name": call.get("name") or "",
                                    "args": call.get("args") or {},
                                    "id": call.get("id") or "",
                                }
                            ],
                        )
                    )
                    history.append(
                        ToolMessage(
                            content=item.get("result") or "",
                            tool_call_id=call.get("id") or "",
                            name=call.get("name") or "",
                        )
                    )
        return history

    @staticmethod
    def _frame(event: AdminAgentChatEvent, payload: dict) -> str:
        return f"event: {event.value}\ndata:{json.dumps(payload, ensure_ascii=False)}\n\n"
