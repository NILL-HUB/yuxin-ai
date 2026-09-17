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

        agent = self._load_agent(principal.agent_id, admin_user_id)
        llm = self._build_model()

        # 提示词/工具构造放进 try：`_build_system_prompt` 在提示词缺失时抛
        # RuntimeError（Task 4 的守卫）。若放在 try 之外，异常会**逃出 SSE 生成器**
        # （客户端拿到断流而非 `event: error`），故必须纳入统一兜底。
        try:
            tools = self._build_tools(principal)
            system_prompt = self._build_system_prompt(
                principal, getattr(agent, "prompt_key", None)
            )
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
            raise
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

        return build_board_tools(BoardToolExecutor(), principal)

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
                history.append(AIMessage(content=row.content or ""))
            elif row.role == AdminAgentMessageRole.TOOL.value and row.tool_calls:
                first = row.tool_calls[0]
                call = first.get("call") or {}
                history.append(
                    ToolMessage(
                        content=first.get("result") or "",
                        tool_call_id=call.get("id") or "",
                        name=call.get("name") or "",
                    )
                )
        return history

    @staticmethod
    def _frame(event: AdminAgentChatEvent, payload: dict) -> str:
        return f"event: {event.value}\ndata:{json.dumps(payload, ensure_ascii=False)}\n\n"
