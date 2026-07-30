import json
import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Generator
from uuid import UUID, uuid4

from flask import current_app, has_app_context
from injector import inject
from langchain_core.messages import AIMessage
from langchain_core.messages import trim_messages
from sqlalchemy import desc
from sqlalchemy.orm import selectinload

from internal.core.agent.agents import AgentQueueManager, DeepThinkingAgent, FunctionCallAgent, ReACTAgent
from internal.core.language_model.entities.model_entity import ModelFeature
from internal.core.memory import TokenBufferMemory
from internal.entity.conversation_entity import InvokeFrom, MessageStatus
from internal.entity.orchestrator_entity import ExecutionMode
from internal.exception import FailException, NotFoundException
from internal.model import App, Account, Conversation, Message
from internal.schema.app_schema import DebugChatReq, GetDebugConversationMessagesWithPageReq
from internal.service.executors.single_agent_executor import SingleAgentExecutor
from pkg.paginator import Paginator
from pkg.sqlalchemy import SQLAlchemy
from .app_runtime_service import AppRuntimeService
from .app_service import AppService
from .base_service import BaseService
from .conversation_service import ConversationService
from .language_model_service import LanguageModelService
from .orchestrator_service import OrchestratorService


logger = logging.getLogger(__name__)


@inject
@dataclass
class AppDebugService(BaseService):
    """应用调试服务：debug_chat + prompt_compare + 调试会话管理。

    从 AppService 抽取的调试相关方法集合。依赖 AppService 提供 CRUD/配置校验，
    依赖 AppRuntimeService 提供运行时工具工厂与 Agent 工厂。
    """
    db: SQLAlchemy
    app_service: AppService
    app_runtime_service: AppRuntimeService
    language_model_service: LanguageModelService
    conversation_service: ConversationService
    orchestrator_service: OrchestratorService | None = None

    ENABLE_ORCHESTRATOR_FOR_DEBUG = True

    def get_debug_conversation_summary(self, app_id: UUID, account: Account) -> str:
        """根据传递的应用id+账号获取指定应用的调试会话长期记忆"""
        # 1.获取应用信息并校验权限
        app = self.app_service.get_app(app_id, account)

        # 2.获取应用的草稿配置，并校验长期记忆是否启用
        draft_app_config = self.app_service.get_draft_app_config(app_id, account, persist_changes=False)
        if draft_app_config["long_term_memory"]["enable"] is False:
            raise FailException("该应用并未开启长期记忆，无法获取")

        return app.debug_conversation.summary

    def update_debug_conversation_summary(self, app_id: UUID, summary: str, account: Account) -> Conversation:
        """根据传递的应用id+总结更新指定应用的调试长期记忆"""
        # 1.获取应用信息并校验权限
        app = self.app_service.get_app(app_id, account)

        # 2.获取应用的草稿配置，并校验长期记忆是否启用
        draft_app_config = self.app_service.get_draft_app_config(app_id, account, persist_changes=False)
        if draft_app_config["long_term_memory"]["enable"] is False:
            raise FailException("该应用并未开启长期记忆，无法获取")

        # 3.更新应用长期记忆
        debug_conversation = app.debug_conversation
        self.update(debug_conversation, summary=summary)

        return debug_conversation

    def delete_debug_conversation(self, app_id: UUID, account: Account) -> App:
        """根据传递的应用id，删除指定的应用调试会话"""
        # 1.获取应用信息并校验权限
        app = self.app_service.get_app(app_id, account)

        # 2.判断是否存在debug_conversation_id这个数据，如果不存在表示没有会话，无需执行任何操作
        if not app.debug_conversation_id:
            return app

        # 3.否则将debug_conversation_id的值重置为None
        self.update(app, debug_conversation_id=None)

        return app

    def _resolve_debug_conversation(
        self,
        app: App,
        account: Account,
        conversation_id: UUID | None = None,
        sync_active: bool = False,
    ) -> Conversation:
        """解析并返回应用调试会话，必要时同步应用当前调试会话指针"""
        if conversation_id is None:
            return app.debug_conversation

        conversation = self.get(Conversation, conversation_id)
        if (
            not conversation
            or conversation.app_id != app.id
            or conversation.created_by != account.id
            or conversation.is_deleted
            or conversation.invoke_from != InvokeFrom.DEBUGGER.value
        ):
            raise NotFoundException("该应用调试会话不存在或已被删除，请核实后重试")

        if sync_active and app.debug_conversation_id != conversation.id:
            self.update(app, debug_conversation_id=conversation.id)

        return conversation

    @staticmethod
    def _extract_builtin_tools_from_tool_subset(
        tool_subset: dict,
        *,
        existing_tools: list[dict],
        query: str = "",
        max_extra: int = 3,
    ) -> list[dict]:
        """从 orchestrator 的 tool_subset 中提取 builtin 工具，转换为运行时 tools_config 格式。

        orchestrator 的 tool_subset 已由 LLM 工具选择器（ToolSelectorService）根据查询语义选出
        最相关的工具，此处仅做格式转换与去重。跳过应用已绑定的工具，返回运行时格式（带
        provider/tool 嵌套对象）。
        """
        selected = tool_subset.get("selected_tools") or []
        if not selected:
            return []
        # 应用已绑定的 builtin 工具去重键：(provider_id, tool_name)
        existing_keys: set[tuple[str, str]] = set()
        for t in existing_tools:
            if not isinstance(t, dict):
                continue
            if t.get("type") != "builtin_tool":
                continue
            prov = t.get("provider_id") or (t.get("provider") or {}).get("id")
            name = t.get("tool_id") or (t.get("tool") or {}).get("name")
            if prov and name:
                existing_keys.add((prov, name))

        result: list[dict] = []
        seen_keys: set[tuple[str, str]] = set()
        for cand in selected:
            if not isinstance(cand, dict):
                continue
            if cand.get("source_type") != "builtin":
                continue
            if len(result) >= max_extra:
                break
            provider_id = cand.get("provider_id", "")
            tool_name = cand.get("name", "")
            if not provider_id or not tool_name:
                continue
            key = (provider_id, tool_name)
            if key in existing_keys or key in seen_keys:
                continue
            seen_keys.add(key)
            result.append({
                "type": "builtin_tool",
                "provider": {"id": provider_id, "name": provider_id},
                "tool": {"name": tool_name, "params": {}},
            })
        return result

    def debug_chat(self, app_id: UUID, req: DebugChatReq, account: Account) -> Generator:
        """根据传递的应用id+提问query向特定的应用发起会话调试"""
        # 1.获取应用信息并校验权限
        app = self.app_service.get_app(app_id, account)

        # 2.获取应用的最新草稿配置信息
        draft_app_config = self.app_service.get_draft_app_config(app_id, account, persist_changes=False)

        # 3.获取当前应用的调试会话信息（支持按conversation_id切换）
        debug_conversation_id = UUID(req.conversation_id.data) if req.conversation_id.data else None
        debug_conversation = self._resolve_debug_conversation(
            app=app,
            account=account,
            conversation_id=debug_conversation_id,
            sync_active=True,
        )

        # 4.在落库前解析运行时模型能力，避免带图请求被静默降级
        if hasattr(self.language_model_service, "resolve_runtime_language_model"):
            model_resolution = self.language_model_service.resolve_runtime_language_model(
                draft_app_config.get("model_config", {}),
                image_urls=req.image_urls.data,
                entrypoint=LanguageModelService.ENTRYPOINT_DEBUGGER,
            )
            llm = model_resolution.llm
            draft_app_config["capabilities"] = model_resolution.capabilities
        else:
            model_resolution = None
            llm = self.language_model_service.load_language_model(draft_app_config.get("model_config", {}))

        # 5.新建一条消息记录
        message = self.create(
            Message,
            app_id=app_id,
            conversation_id=debug_conversation.id,
            invoke_from=InvokeFrom.DEBUGGER.value,
            created_by=account.id,
            query=req.query.data,
            image_urls=req.image_urls.data,
            status=MessageStatus.NORMAL.value,
        )

        # 5.1 治理架构接入：通过 OrchestratorService 进行任务分类、成本路由与 Agent/工具池决策。
        #     受 ENABLE_ORCHESTRATOR_FOR_DEBUG 特性开关控制，默认关闭以保持兼容；
        #     未注入 OrchestratorService 或决策异常时回退到既有 stream_agent_events 流程。
        #     应用调试路径始终以应用自身配置的 Agent 作为最终执行器（stream_agent_events），
        #     多智能体/直接应答执行器由 assistant_agent_service 负责，此处不接管。
        routing_decision = None
        if self.orchestrator_service is not None and self.ENABLE_ORCHESTRATOR_FOR_DEBUG:
            try:
                routing_decision = self.orchestrator_service.decide(
                    req.query.data,
                    account_id=account.id,
                    conversation_id=debug_conversation.id,
                    message_id=message.id,
                    image_urls=req.image_urls.data,
                    enable_deep_thinking=bool(req.confirm_deep_thinking.data),
                ).to_dict()
            except Exception as exc:
                logger.warning("应用调试调度决策失败，回退到原调试流程: %s", exc)
                routing_decision = None

        # 仅在拿到有效（非 fallback）路由决策时推送治理事件并执行成本检查
        if routing_decision is not None and routing_decision.get("intent") != "fallback":
            logger.info(
                "应用调试路由决策 intent=%s execution_mode=%s complexity=%s model_tier=%s risk=%s",
                routing_decision.get("intent"),
                routing_decision.get("execution_mode"),
                routing_decision.get("complexity"),
                routing_decision.get("recommended_model_tier"),
                routing_decision.get("risk_level"),
            )
            yield "event: orchestrator_routing\ndata:" + json.dumps(routing_decision) + "\n\n"
            # 成本策略检查：余额不足时提前终止调试流，避免无效执行
            if not routing_decision.get("cost_policy", {}).get("allowed", True):
                reject_payload = {
                    "reason": "insufficient_balance",
                    "cost_policy": routing_decision.get("cost_policy"),
                    "message_id": str(message.id),
                    "conversation_id": str(debug_conversation.id),
                }
                yield "event: orchestrator_reject\ndata:" + json.dumps(reject_payload) + "\n\n"
                return

        # 6.实例化TokenBufferMemory用于提取短期记忆
        token_buffer_memory = TokenBufferMemory(
            db=self.db,
            conversation=debug_conversation,
            model_instance=llm,
        )
        history = token_buffer_memory.get_history_prompt_messages(
            message_limit=draft_app_config["dialog_round"],
        )

        agent_thoughts = {}
        runtime_flask_app = current_app._get_current_object() if has_app_context() else None

        # 6.1 治理架构执行接入：当路由决策有效且特性开关开启时，
        #     通过 SingleAgentExecutor 经 ExecutionCoordinatorService 统一编排执行，
        #     共享 multi_agent 等路径的编排与容错能力。
        #     否则回退到原有的 stream_agent_events 流程。
        execution_mode = None
        if routing_decision is not None and routing_decision.get("intent") != "fallback" and self.ENABLE_ORCHESTRATOR_FOR_DEBUG:
            execution_mode = routing_decision.get("execution_mode")
            if execution_mode in ("deep_thinking",):
                execution_mode = ExecutionMode.SINGLE_AGENT_WITH_TOOLS.value

        try:
            if execution_mode and self.ENABLE_ORCHESTRATOR_FOR_DEBUG:
                enable_deep_thinking = bool(req.confirm_deep_thinking.data)
                agent_class = DeepThinkingAgent if enable_deep_thinking else (
                    FunctionCallAgent if ModelFeature.TOOL_CALL.value in llm.features else ReACTAgent
                )
                # 治理联动：当路由决策 needs_tools=True 时，把 orchestrator 选出的 builtin 工具
                # 自动注入到运行时工具列表，避免用户必须手动给应用绑定工具才能调用工具。
                # 仅注入 builtin 工具（最稳定，无需额外凭证），并跳过应用已绑定的工具去重。
                runtime_app_config = draft_app_config
                if routing_decision and routing_decision.get("needs_tools"):
                    extra_tools_config = self._extract_builtin_tools_from_tool_subset(
                        routing_decision.get("tool_subset") or {},
                        existing_tools=draft_app_config.get("tools", []),
                        query=req.query.data,
                        max_extra=3,
                    )
                    if extra_tools_config:
                        runtime_app_config = {
                            **draft_app_config,
                            "tools": list(draft_app_config.get("tools", [])) + extra_tools_config,
                        }
                        logger.warning(
                            "应用调试注入治理池 builtin 工具 app_id=%s extra_tools=%s",
                            app_id, [t["tool"]["name"] for t in extra_tools_config],
                        )
                # 传递 runtime_context 包含 conversation_id 和 message_id，供治理审计写入路由日志
                tools = self.app_runtime_service.build_runtime_tools(
                    app_id, account, runtime_app_config,
                    flask_app=runtime_flask_app,
                    runtime_context={
                        "app_id": str(app_id),
                        "account_id": str(account.id),
                        "conversation_id": str(debug_conversation.id),
                        "message_id": str(message.id),
                    },
                )
                tool_names = [getattr(t, "name", str(t)) for t in tools]
                logger.warning(
                    "应用调试工具构建完成 app_id=%s execution_mode=%s tools_count=%d tool_names=%s",
                    app_id, execution_mode, len(tools), tool_names,
                )
                agent = self.app_runtime_service.create_runtime_agent(
                    llm,
                    account,
                    draft_app_config,
                    tools,
                    enable_deep_thinking,
                    flask_app=runtime_flask_app,
                    language_model_service=self.language_model_service,
                )
                agent_config = agent.agent_config
                executor = SingleAgentExecutor(
                    agent_class=agent_class,
                    agent_config=agent_config,
                    tools=tools,
                    llm=llm,
                    history=history,
                    query=req.query.data,
                    long_term_memory=debug_conversation.summary,
                    user_memory="",
                )
                yield from executor.execute(
                    query=req.query.data,
                    conversation=debug_conversation,
                    message=message,
                    execution_mode=execution_mode,
                    routing_decision=routing_decision,
                )
            else:
                yield from self.app_runtime_service.stream_agent_events(
                    app_id=app_id,
                    account=account,
                    draft_app_config=draft_app_config,
                    llm=llm,
                    query=req.query.data,
                    image_urls=req.image_urls.data,
                    history=history,
                    long_term_memory=debug_conversation.summary,
                    conversation_id=str(debug_conversation.id),
                    message_id=str(message.id),
                    agent_thoughts=agent_thoughts,
                    enable_deep_thinking=bool(req.confirm_deep_thinking.data),
                    flask_app=runtime_flask_app,
                )
        finally:
            # 17.将消息以及推理过程添加到数据库
            # 无论 Agent 流正常完成还是异常终止，都尝试落库已收集的推理过程
            try:
                self.conversation_service.save_agent_thoughts(
                    account_id=account.id,
                    app_id=app_id,
                    app_config=draft_app_config,
                    conversation_id=debug_conversation.id,
                    message_id=message.id,
                    agent_thoughts=[agent_thought for agent_thought in agent_thoughts.values()],
                )
            except Exception:
                logger.warning("Debug会话落库失败，conversation_id=%s message_id=%s",
                               debug_conversation.id, message.id, exc_info=True)

    def prompt_compare_chat(self, app_id: UUID, req: Any, account: Account) -> Generator[str, None, None]:
        """根据传递的应用id发起无状态提示词对比调试"""
        app = self.app_service.get_app(app_id, account)
        draft_app_config = self.app_service.get_draft_app_config(app_id, account, persist_changes=False)
        overrides = self.app_service._validate_draft_app_config(
            {
                "preset_prompt": req.preset_prompt.data,
                "model_config": req.model_config.data,
            },
            account,
        )
        draft_app_config.update(overrides)

        llm = self.language_model_service.load_language_model(draft_app_config.get("model_config", {}))
        history = self._build_compare_history_prompt_messages(
            llm=llm,
            history_entries=req.history.data,
            message_limit=draft_app_config["dialog_round"],
        )
        long_term_memory = ""
        if draft_app_config["long_term_memory"]["enable"]:
            long_term_memory = self._get_debug_long_term_memory_snapshot(app, account)

        yield from self.app_runtime_service.stream_agent_events(
            app_id=app_id,
            account=account,
            draft_app_config=draft_app_config,
            llm=llm,
            query=req.query.data,
            image_urls=[],
            history=history,
            long_term_memory=long_term_memory,
            conversation_id=req.lane_id.data.strip() if req.lane_id.data else str(uuid4()),
            message_id=str(uuid4()),
            flask_app=current_app._get_current_object() if has_app_context() else None,
        )

    def stop_debug_chat(self, app_id: UUID, task_id: UUID, account: Account) -> None:
        """根据传递的应用id+任务id+账号，停止某个应用的调试会话，中断流式事件"""
        # 1.获取应用信息并校验权限
        self.app_service.get_app(app_id, account)

        # 2.调用智能体队列管理器停止特定任务
        AgentQueueManager.set_stop_flag(task_id, InvokeFrom.DEBUGGER.value, account.id)

    def stop_prompt_compare_chat(self, app_id: UUID, task_id: UUID, account: Account) -> None:
        """根据传递的应用id+任务id停止某个提示词对比调试会话"""
        self.app_service.get_app(app_id, account)
        AgentQueueManager.set_stop_flag(task_id, InvokeFrom.DEBUGGER.value, account.id)

    def prompt_compare_chat_for_admin(self, app_id: UUID, req: Any) -> Generator[str, None, None]:
        """管理员发起提示词对比调试（不校验账号归属，以应用归属账号执行）"""
        account = self.app_service.get_app_owner_account_for_admin(app_id)
        return self.prompt_compare_chat(app_id, req, account)

    def stop_prompt_compare_chat_for_admin(self, app_id: UUID, task_id: UUID) -> None:
        """管理员停止提示词对比调试会话（不校验账号归属，以应用归属账号执行）"""
        account = self.app_service.get_app_owner_account_for_admin(app_id)
        self.stop_prompt_compare_chat(app_id, task_id, account)

    def get_debug_conversation_messages_with_page(
            self,
            app_id: UUID,
            req: GetDebugConversationMessagesWithPageReq,
            account: Account
    ) -> tuple[list[Message], Paginator]:
        """根据传递的应用id+请求数据，获取调试会话消息列表分页数据"""

        # 1. 获取应用信息并校验权限
        app = self.app_service.get_app(app_id, account)

        # 2. 获取应用的调试会话（支持按conversation_id切换）
        debug_conversation_id = UUID(req.conversation_id.data) if req.conversation_id.data else None
        debug_conversation = self._resolve_debug_conversation(
            app=app,
            account=account,
            conversation_id=debug_conversation_id,
            sync_active=False,
        )

        # 3. 构建分页器并构建过滤条件
        paginator = Paginator(db=self.db, req=req)
        filters = [
            Message.conversation_id == debug_conversation.id,
            Message.status.in_([MessageStatus.STOP.value, MessageStatus.NORMAL.value]),
            Message.answer != "",
            Message.is_deleted == False,
        ]

        if req.created_at.data:
            # 4. 将时间戳转换成 DateTime
            created_at_datetime = datetime.fromtimestamp(req.created_at.data, UTC)
            filters.append(Message.created_at <= created_at_datetime)

        # 5. 先分页查询 ID 列表
        paginated_ids = paginator.paginate(
            self.db.session.query(Message.id)
            .filter(*filters)
            .order_by(desc(Message.created_at), desc(Message.id))
        )

        normalized_ids = self._normalize_paginated_ids(paginated_ids)
        if not normalized_ids:
            return [], paginator

        # 6. 再根据 ID 查询完整消息及其关联内容
        messages = (
            self.db.session.query(Message)
            .options(selectinload(Message.agent_thoughts))
            .filter(Message.id.in_(normalized_ids))
            .order_by(desc(Message.created_at), desc(Message.id))
            .all()
        )

        return messages, paginator

    def _build_compare_history_prompt_messages(
        self,
        llm: Any,
        history_entries: list[dict[str, str]],
        message_limit: int,
        max_token_limit: int = 2000,
    ) -> list[Any]:
        """根据前端传递的历史问答构建对比调试上下文"""
        if message_limit <= 0 or not history_entries:
            return []

        prompt_messages = []
        for history_item in history_entries[-message_limit:]:
            query = str(history_item.get("query", "")).strip()
            answer = str(history_item.get("answer", "")).strip()
            if not query or not answer:
                continue
            prompt_messages.extend([
                llm.convert_to_human_message(query),
                AIMessage(content=answer),
            ])

        if not prompt_messages:
            return []

        try:
            return trim_messages(
                messages=prompt_messages,
                max_tokens=max_token_limit,
                token_counter=llm,
                strategy="last",
                start_on="human",
                end_on="ai",
            )
        except NotImplementedError:
            token_buffer_memory = TokenBufferMemory(
                db=self.db,
                conversation=None,
                model_instance=llm,
            )
            return trim_messages(
                messages=prompt_messages,
                max_tokens=max_token_limit,
                token_counter=token_buffer_memory._fallback_token_counter,
                strategy="last",
                start_on="human",
                end_on="ai",
            )

    def _get_debug_long_term_memory_snapshot(self, app: App, account: Account) -> str:
        """获取当前应用已有调试会话的长期记忆快照，不主动创建新会话"""
        if not app.debug_conversation_id:
            return ""

        debug_conversation = self.db.session.query(Conversation).filter(
            Conversation.id == app.debug_conversation_id,
            Conversation.app_id == app.id,
            Conversation.created_by == account.id,
            Conversation.invoke_from == InvokeFrom.DEBUGGER.value,
            Conversation.is_deleted == False,
        ).one_or_none()

        return debug_conversation.summary if debug_conversation else ""

    @staticmethod
    def _normalize_paginated_ids(paginated_items: list[Any]) -> list[Any]:
        """提取分页结果中的主键值，兼容 SQLAlchemy Row/tuple 标量结果。"""
        normalized_ids = []
        for item in paginated_items:
            if isinstance(item, UUID):
                normalized_ids.append(item)
                continue

            mapping = getattr(item, "_mapping", None)
            if mapping:
                normalized_ids.append(next(iter(mapping.values()), None))
                continue

            if isinstance(item, (tuple, list)):
                normalized_ids.append(item[0] if item else None)
                continue

            normalized_ids.append(item)

        return [item for item in normalized_ids if item is not None]
