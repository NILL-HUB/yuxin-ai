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

from internal.core.admin_agent_budget import AdminAgentBudgetExceeded
from internal.entity.admin_agent_chat_entity import (
    AdminAgentChatEvent,
    AdminAgentMessageRole,
)
from internal.entity.admin_agent_entity import AdminAgentPrincipal
from internal.exception import CustomException, FailException
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
        """执行一轮对话，逐帧 yield SSE 字符串。

        本链路**所有可预期失败都以 `event: error` 帧结束**，不逃出生成器：
        逃出的异常会被 `support._sse_response` 的通用兜底捕获，改用另一套
        payload 结构（`event: <failure_event>` + `observation`），本链路的
        error 帧契约（`{"error": ...}`）就此丢失，客户端表现为断流或双帧冲突。
        """
        text = str(query or "").strip()
        if not text:
            yield self._frame(AdminAgentChatEvent.ERROR, {"error": "消息不能为空"})
            return

        # 预初始化：`except Exception` 分支要记录 agent_id，若身份解析阶段就抛错，
        # 直接引用 `principal.agent_id` 会 UnboundLocalError（历史缺陷）。
        principal: AdminAgentPrincipal | None = None
        # 工具事件在循环**进行中**逐条累加（供 assistant 落库）并即时 yield 帧，
        # 而不是等循环结束再一次性补帧——否则最长 6 轮期间客户端只见 keep-alive。
        tool_events: list[dict] = []
        answer = ""
        # try 边界覆盖**全链路**：身份解析 → 会话解析 → 落 user 消息 → MESSAGE 帧
        # → Agent 加载 → 工具装配 → 提示词构造 → 模型获取 → 工具循环。
        # `get_principal` 的 PermissionError（非属主/已停用）与
        # `_resolve_conversation` 的 NotFoundException/ForbiddenException
        # 同样是本链路可预期失败，落在 try 之外就会以另一套结构收尾。
        try:
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
                conversation_id=conversation.id,
                role=AdminAgentMessageRole.USER.value,
                content=text,
            )

            agent = self._load_agent(principal.agent_id, admin_user_id)
            # 预算闸门（ADMIN-P4 T2）：对话是"让 Agent 动手"的一类入口，进入
            # 模型/工具循环前先校验并累计周期用量。超限抛
            # `AdminAgentBudgetExceeded`，由下方 except 分支转 error 帧。
            self._budget_gate().check_and_record(
                str(principal.agent_id),
                getattr(agent, "budget_config", None) or {},
            )
            tools = self._build_tools(principal)
            # 记忆读回（ADMIN-P3c-2）：admin/Agent 主体召回，fail-open。
            # 召回复用 P3b 已主体化的读路径（retriever/digest），此处只构造 admin
            # 主体键并注入提示词。两道防线（方法内吞错 + 调用点兜底）：记忆是增强项，
            # 任何失败都不得让整轮对话以 error 帧结束。
            try:
                memory_text = self._recall_memory(
                    admin_user_id=principal.admin_user_id,
                    agent_id=principal.agent_id,
                    query=text,
                    conversation_id=str(conversation.id),
                )
            except Exception:
                logger.warning("管理端 Agent 记忆召回失败，静默降级", exc_info=True)
                memory_text = ""
            system_prompt = self._build_system_prompt(
                principal, getattr(agent, "prompt_key", None), memory_text=memory_text
            )
            llm = self._build_model()
            # 迭代工具循环生成器：每拿到一个 ("tool", event) 就立刻落库并推 TOOL
            # 帧（"边跑边推"），最后一帧 ("answer", text) 作为最终答复。循环最长
            # 6 轮，若等循环结束再一次性补帧，客户端在此期间只见 keep-alive。
            for kind, payload in self._run_tool_loop(
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
            ):
                if kind == "tool":
                    tool_events.append(payload)
                    yield self._frame(AdminAgentChatEvent.TOOL, payload)
                else:
                    answer = str(payload or "")
        except FailException as exc:
            # 业务结论（含工具循环超轮次不收敛）：统一以 error 帧结束，不上抛
            yield self._frame(AdminAgentChatEvent.ERROR, {"error": str(exc)})
            return
        except CustomException as exc:
            # NotFound/Forbidden/Validate 等同族：同样转 error 帧（HTTP 层保持
            # 200 + text/event-stream，客户端据帧内容判定失败）。
            yield self._frame(AdminAgentChatEvent.ERROR, {"error": str(exc)})
            return
        except PermissionError as exc:
            # 非属主/已停用 Agent（AdminAgentService 契约）
            yield self._frame(AdminAgentChatEvent.ERROR, {"error": str(exc)})
            return
        except AdminAgentBudgetExceeded as exc:
            # 预算闸门拒绝（ADMIN-P4 T2）：额度耗尽不是链路故障，原样透出
            # 闸门文案（管理员据此知道"哪个周期额度用完"），不得被兜底的
            # `except Exception` 改写成"对话失败：…"。
            yield self._frame(AdminAgentChatEvent.ERROR, {"error": str(exc)})
            return
        except Exception as exc:
            logger.exception(
                "管理端 Agent 对话失败 agent_id=%s",
                getattr(principal, "agent_id", None),
            )
            yield self._frame(AdminAgentChatEvent.ERROR, {"error": f"对话失败：{exc}"})
            return

        self.append_message(
            conversation_id=conversation.id,
            role=AdminAgentMessageRole.ASSISTANT.value,
            content=answer,
            tool_calls=[e["call"] for e in tool_events],
        )
        # 对话后写入记忆（ADMIN-P3c-2）：异步 + 吞错，不影响已产出的答复。
        try:
            self._write_memory(
                admin_user_id=principal.admin_user_id,
                agent_id=principal.agent_id,
                query=text,
                ai_response=answer,
                conversation_id=str(conversation.id),
            )
        except Exception:
            logger.warning("管理端 Agent 记忆写入失败，静默降级", exc_info=True)
        yield self._frame(AdminAgentChatEvent.ANSWER, {"answer": answer})
        yield self._frame(AdminAgentChatEvent.END, {})

    # ------------------------------------------------------------------
    # 工具循环
    # ------------------------------------------------------------------

    def _run_tool_loop(
        self, *, llm, system_prompt: str, history, tools, on_tool
    ) -> Generator[tuple[str, Any], None, None]:
        """驱动「LLM ⇄ 板块工具」循环（**生成器**）。

        逐次产出 ``("tool", event)``（每完成一次工具调用即产出），使调用方
        得以在循环进行中即时推帧；收敛后产出 ``("answer", text)`` 收尾。
        """
        from langchain_core.messages import SystemMessage, ToolMessage
        from pydantic import ValidationError

        messages: list[Any] = [SystemMessage(content=system_prompt), *history]
        tools_by_name = {tool.name: tool for tool in tools}
        bound = llm.bind_tools(tools) if tools else llm

        for _ in range(MAX_TOOL_ITERATIONS):
            ai = bound.invoke(messages)
            messages.append(ai)
            calls = list(getattr(ai, "tool_calls", None) or [])
            if not calls:
                yield ("answer", str(getattr(ai, "content", "") or ""))
                return

            for call in calls:
                name = str(call.get("name") or "")
                tool = tools_by_name.get(name)
                if tool is None:
                    result = json.dumps({"ok": False, "error": f"未知工具：{name}"}, ensure_ascii=False)
                else:
                    try:
                        result = tool.invoke(call.get("args") or {})
                    except ValidationError as exc:
                        # langchain `BaseTool.run` 在**进入 `_run` 之前**先用
                        # `args_schema` 校验入参；校验失败抛 `ValidationError`，
                        # 工具 `_run` 内的 try 拦不到。它是"入参不合法"这一**业务
                        # 结论**（如 action 缺失 / payload 非 dict），必须转成可读
                        # 结果回给模型据实改正重试，不得中断整轮对话。此处只捕获
                        # `ValidationError`，不放宽为 `except Exception`——真正的
                        # 编程缺陷仍应上抛，否则会被静默吞掉。
                        result = json.dumps(
                            {
                                "ok": False,
                                "board": name.removeprefix("admin_"),
                                "error": f"入参不合法: {exc}",
                            },
                            ensure_ascii=False,
                            default=str,
                        )
                event = {
                    "call": {"name": name, "args": call.get("args") or {}, "id": call.get("id") or ""},
                    "result": result,
                }
                on_tool(event)
                messages.append(
                    ToolMessage(
                        content=result,
                        tool_call_id=call.get("id") or "",
                        name=name,
                    )
                )
                yield ("tool", event)
        raise FailException(
            f"Agent 工具调用超过 {MAX_TOOL_ITERATIONS} 轮仍未收敛，已中止（疑似循环）"
        )

    # ------------------------------------------------------------------
    # 可替换点（测试替换，避免真实 LLM / DB / 提示词）
    # ------------------------------------------------------------------

    def _budget_gate(self):
        """预算闸门（ADMIN-P4 T2，测试可替换为抛错的替身）。"""
        from internal.core.admin_agent_budget import AdminAgentBudgetGate

        return AdminAgentBudgetGate()

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

    def _build_system_prompt(
        self, principal: AdminAgentPrincipal, prompt_key, *, memory_text: str = ""
    ) -> str:
        from internal.service.admin_agent_prompt_service import AdminAgentPromptService

        prompt = AdminAgentPromptService().build_system_prompt(
            principal, prompt_key=prompt_key
        )
        # 记忆注入（ADMIN-P3c-2）：命中时才附加，避免空段污染提示词。
        if memory_text:
            prompt = f"{prompt}\n\n## 你记得的相关信息\n{memory_text}"
        return prompt

    def _recall_memory(
        self, *, admin_user_id, agent_id, query: str, conversation_id: str
    ) -> str:
        """召回 admin/Agent 主体记忆（fail-open：任何异常返回空串）。

        主体键由 ``recall_admin_agent_memory_for_chat`` 内部构造为
        ``for_admin(admin_user_id, agent_id=...)``——admin 无 account，绝不走用户主体。
        """
        from internal.service.memory.admin_memory_recall import (
            recall_admin_agent_memory_for_chat,
        )

        return recall_admin_agent_memory_for_chat(
            admin_user_id=admin_user_id,
            agent_id=agent_id,
            query=query,
            conversation_id=conversation_id,
        )

    def _write_memory(
        self,
        *,
        admin_user_id,
        agent_id,
        query: str,
        ai_response: str,
        conversation_id: str,
    ) -> None:
        """对话后写入 admin/Agent 主体记忆（后台线程 + 吞错）。

        与用户端 ``AssistantAgentService._write_memory_from_conversation`` 同策：
        记忆写入涉及 LLM（实体抽取/显著性评分），放后台线程避免阻塞响应流；
        线程内必须用 ``app_session_scope``（否则连接停在 idle in transaction）。
        """
        if not ai_response:
            return

        from internal.config.memory_settings import settings as memory_settings

        if not memory_settings.memory_engine_enabled:
            return

        def _bg_write() -> None:
            from internal.lib.runtime_context import app_session_scope

            with app_session_scope():
                try:
                    from app.http.app import injector
                    from internal.service.memory.memory_write_service import (
                        MemoryWriteService,
                    )

                    injector.get(MemoryWriteService).write_admin_conversation(
                        admin_user_id=admin_user_id,
                        agent_id=agent_id,
                        query=query,
                        ai_response=ai_response,
                        conversation_id=conversation_id,
                    )
                except Exception:
                    logger.warning("管理端 Agent 记忆写入失败", exc_info=True)

        from threading import Thread

        Thread(target=_bg_write, daemon=True).start()

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
        """取既有会话（校验归属）或新建会话。

        续聊时除 ``get_conversation`` 的属主校验外，还必须校验会话属于**当前
        Agent**：``conversation_id`` 由客户端提交，若只校验属主，同一管理员
        用 Agent B 续聊 Agent A 的会话会把 A 的历史（含 A 的工具调用结果）
        灌进 B 的上下文，B 的答复又落进 A 的会话——归属与审计都错位。
        """
        from internal.service.admin_agent_conversation_service import (
            AdminAgentConversationService,
        )

        conversations = AdminAgentConversationService(self.db)
        if conversation_id:
            conversation = conversations.get_conversation(
                conversation_id, admin_user_id=admin_user_id
            )
            if conversation.admin_agent_id != admin_agent_id:
                raise FailException("会话不属于该 Agent")
            return conversation
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
