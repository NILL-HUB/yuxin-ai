import json
import logging
from typing import Generator, Any
from uuid import UUID
from flask import current_app
from injector import inject
from langchain_core.messages import HumanMessage
from sqlalchemy import desc
from pkg.sqlalchemy import SQLAlchemy
from .base_service import BaseService
from internal.entity.app_entity import AppStatus
from internal.model import App, Account, Conversation, Message
from internal.exception import NotFoundException, ForbiddenException
from dataclasses import dataclass
from internal.schema.web_app_schema import WebAppChatReq
from internal.core.agent.entities.queue_entity import QueueEvent
from internal.core.agent.usage_utils import summarize_agent_thoughts
from internal.core.language_model.entities.model_entity import ModelFeature
from internal.core.memory import TokenBufferMemory
from internal.entity.conversation_entity import InvokeFrom, MessageStatus
from internal.entity.dataset_entity import RetrievalSource
from .app_config_service import AppConfigService, call_config_loader
from .app_runtime_service import AppRuntimeService
from .conversation_service import ConversationService
from .language_model_service import LanguageModelService
from .orchestrator_service import OrchestratorService
from .retrieval_service import RetrievalService
from .skill_service import SkillService
from internal.core.agent.agents import AgentQueueManager


logger = logging.getLogger(__name__)


@inject
@dataclass
class WebAppService(BaseService):
    """WebApp服务"""
    db: SQLAlchemy
    app_config_service: AppConfigService
    conversation_service: ConversationService
    language_model_service: LanguageModelService
    retrieval_service: RetrievalService
    app_runtime_service: AppRuntimeService | None = None
    skill_service: SkillService | None = None
    orchestrator_service: OrchestratorService | None = None

    @staticmethod
    def _extract_builtin_tools_from_tool_subset(
        tool_subset: dict,
        *,
        existing_tools: list[dict],
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

    def get_web_app(self, token: str) -> App:
        """根据传递的token获取WebApp实例"""
        # 1.在数据库中查询token对应的应用
        app = self.db.session.query(App).filter(
            App.token == token
        ).one_or_none()

        if not app or app.status != AppStatus.PUBLISHED.value:
            raise NotFoundException("该WebApp不存在 请核实后重试")

        # 2.返回查询的应用
        return app

    def get_web_app_info(self, token: str) -> dict[str, Any]:
        """根据传递的token获取WebApp信息"""
        # 1.获取App基础信息
        app = self.get_web_app(token)

        # 2.根据App基础信息构建LLM
        app_config = call_config_loader(
            self.app_config_service.get_app_config,
            app,
            persist_changes=False,
        )
        if hasattr(self.language_model_service, "describe_runtime_capabilities"):
            capabilities = self.language_model_service.describe_runtime_capabilities(
                app_config.get("model_config", {}),
                entrypoint=LanguageModelService.ENTRYPOINT_WEB_APP,
            )
        else:
            llm = self.language_model_service.load_language_model(app_config.get("model_config", {}))
            capabilities = {
                "features": list(getattr(llm, "features", []) or []),
                "image_input": {
                    "enabled": ModelFeature.IMAGE_INPUT.value in list(getattr(llm, "features", []) or []),
                },
            }

        # 3.提取信息并返回
        return {
            "id": str(app.id),
            "icon": app.icon,
            "name": app.name,
            "description": app.description,
            "app_config": {
                "opening_statement": app_config.get("opening_statement"),
                "opening_questions": app_config.get("opening_questions"),
                "suggested_after_answer": app_config.get("suggested_after_answer"),
                "features": capabilities.get("features", []),
                "capabilities": capabilities,
                "text_to_speech": app_config.get("text_to_speech"),
                "speech_to_text": app_config.get("speech_to_text"),
            }
        }

    def web_app_chat(self, token: str, req: WebAppChatReq, account: Account) -> Generator:
        """根据传递的token凭证+请求与指定的WebApp进行对话"""
        # 1.获取WebApp应用并校验应用是否发布
        app = self.get_web_app(token)

        # 2.检测是否传递了会话id，如果传递了需要校验会话的归属信息
        if req.conversation_id.data:
            conversation = self.get(Conversation, req.conversation_id.data)
            if (
                    not conversation
                    or conversation.app_id != app.id
                    or conversation.invoke_from != InvokeFrom.WEB_APP.value
                    or conversation.created_by != account.id
                    or conversation.is_deleted is True
            ):
                raise ForbiddenException("该会话不存在，或者不属于当前应用/用户/调用方式")
        else:
            # 3.如果没传递conversation_id表示新会话，这时候需要创建一个会话
            conversation = self.create(Conversation, **{
                "app_id": app.id,
                "name": "New Conversation",
                "invoke_from": InvokeFrom.WEB_APP.value,
                "created_by": account.id,
            })

        # 4.获取校验后的运行时配置
        app_config = call_config_loader(
            self.app_config_service.get_app_config,
            app,
            persist_changes=False,
        )

        # 5.在落库前解析运行时模型能力，避免带图请求被静默降级
        if hasattr(self.language_model_service, "resolve_runtime_language_model"):
            model_resolution = self.language_model_service.resolve_runtime_language_model(
                app_config.get("model_config", {}),
                image_urls=req.image_urls.data,
                entrypoint=LanguageModelService.ENTRYPOINT_WEB_APP,
            )
            llm = model_resolution.llm
            app_config["capabilities"] = model_resolution.capabilities
        else:
            llm = self.language_model_service.load_language_model(app_config.get("model_config", {}))

        # 6.新建一条消息记录
        message = self.create(
            Message,
            app_id=app.id,
            conversation_id=conversation.id,
            invoke_from=InvokeFrom.WEB_APP,
            created_by=account.id,
            query=req.query.data,
            image_urls=req.image_urls.data,
            status=MessageStatus.NORMAL,
        )

        # 6.1 治理架构接入：通过 OrchestratorService 进行任务分类与 LLM 工具选择。
        #     WebApp 访客不在 account 表中，routing_log.account_id 使用 app owner 的 account_id
        #     （与 build_runtime_tools_for_config 的 governance_account_id 保持一致）。
        #     未注入 OrchestratorService 或决策异常时回退到既有 stream_agent_events 流程。
        routing_decision = None
        if self.orchestrator_service is not None:
            try:
                routing_decision = self.orchestrator_service.decide(
                    req.query.data,
                    account_id=app.account_id,
                    conversation_id=conversation.id,
                    message_id=message.id,
                    image_urls=req.image_urls.data,
                ).to_dict()
            except Exception as exc:
                logger.warning("WebApp 调度决策失败，继续原流程: %s", exc)
                routing_decision = None

        # 仅在拿到有效（非 fallback）路由决策时记录日志
        if routing_decision is not None and routing_decision.get("intent") != "fallback":
            logger.info(
                "WebApp 路由决策 intent=%s execution_mode=%s needs_tools=%s tool_count=%d",
                routing_decision.get("intent"),
                routing_decision.get("execution_mode"),
                routing_decision.get("needs_tools"),
                len((routing_decision.get("tool_subset") or {}).get("selected_tools", [])),
            )

        # 7.实例化TokenBufferMemory用于提取短期记忆
        token_buffer_memory = TokenBufferMemory(
            db=self.db,
            conversation=conversation,
            model_instance=llm,
        )
        history = token_buffer_memory.get_history_prompt_messages(
            message_limit=app_config["dialog_round"],
        )

        # 8.根据应用配置构建运行时工具
        # 传递 runtime_context 包含 conversation_id 和 message_id，供治理审计写入路由日志
        # governance_account_id 使用 app owner 的 account_id（FK 有效），
        # 因为 WebApp 访客不在 account 表中，不能直接作为 routing_log.account_id FK
        # 8.1 治理联动：当路由决策 needs_tools=True 时，把 orchestrator 选出的 builtin 工具
        #     自动注入到运行时工具列表，避免应用未绑定工具时无法调用基础能力（如时间查询）。
        #     仅注入 builtin 工具（最稳定，无需额外凭证），并跳过应用已绑定的工具去重。
        runtime_app_config = app_config
        if routing_decision and routing_decision.get("needs_tools"):
            extra_tools_config = self._extract_builtin_tools_from_tool_subset(
                routing_decision.get("tool_subset") or {},
                existing_tools=app_config.get("tools", []),
                max_extra=3,
            )
            if extra_tools_config:
                runtime_app_config = {
                    **app_config,
                    "tools": list(app_config.get("tools", [])) + extra_tools_config,
                }
                logger.info(
                    "WebApp 注入 LLM 选择的 builtin 工具 count=%d tools=%s",
                    len(extra_tools_config),
                    [t["tool"]["name"] for t in extra_tools_config],
                )
        tools = AppRuntimeService.build_runtime_tools_for_config(
            app_config_service=self.app_config_service,
            retrieval_service=self.retrieval_service,
            skill_service=self.skill_service,
            app_service=self.app_runtime_service,
            account=account,
            app_id=app.id,
            draft_app_config=runtime_app_config,
            flask_app=current_app._get_current_object(),
            runtime_context={
                "app_id": str(app.id),
                "account_id": str(account.id),
                "governance_account_id": str(app.account_id),
                "conversation_id": str(conversation.id),
                "message_id": str(message.id),
            },
            governance_gate=getattr(self.app_runtime_service, 'runtime_tool_governance_gate', None),
        )

        # 9.复用运行时Agent工厂，确保已发布WebApp与调试态应用共用深度思考链路
        runtime_flask_app = current_app._get_current_object()
        agent = AppRuntimeService.create_runtime_agent(
            llm=llm,
            account=account,
            draft_app_config=app_config,
            tools=tools,
            enable_deep_thinking=bool(req.confirm_deep_thinking.data),
            flask_app=runtime_flask_app,
            invoke_from=InvokeFrom.WEB_APP.value,
        )

        # 13.定义字典存储推理过程，并调用智能体获取消息
        # 获取完整长期记忆：包含 distant_summaries（远期分段摘要）和 summary（当前滚动摘要）
        long_term_memory = token_buffer_memory.get_distant_summary(conversation) or (conversation.summary or "")
        agent_thoughts = {}
        try:
            for agent_thought in agent.stream({
                "messages": [llm.convert_to_human_message(req.query.data, req.image_urls.data)],
                "history": history,
                "long_term_memory": long_term_memory,
            }):
                # 14.提取thought以及answer
                event_id = str(agent_thought.id)

                # 15.将数据填充到agent_thought，便于存储到数据库服务中
                if agent_thought.event != QueueEvent.PING.value:
                    # 16.除了agent_message数据为叠加，其他均为覆盖
                    if agent_thought.event == QueueEvent.AGENT_MESSAGE.value:
                        if event_id not in agent_thoughts:
                            # 17.初始化智能体消息事件
                            agent_thoughts[event_id] = agent_thought
                        else:
                            # 18.叠加智能体消息
                            agent_thoughts[event_id] = agent_thoughts[event_id].model_copy(update={
                                "thought": agent_thoughts[event_id].thought + agent_thought.thought,
                                # 消息相关数据
                                "message": agent_thought.message,
                                "message_token_count": agent_thought.message_token_count,
                                "message_unit_price": agent_thought.message_unit_price,
                                "message_price_unit": agent_thought.message_price_unit,
                                # 答案相关数据
                                "answer": agent_thoughts[event_id].answer + agent_thought.answer,
                                "answer_token_count": agent_thought.answer_token_count,
                                "answer_unit_price": agent_thought.answer_unit_price,
                                "answer_price_unit": agent_thought.answer_price_unit,
                                # Agent推理统计相关
                                "total_token_count": agent_thought.total_token_count,
                                "total_price": agent_thought.total_price,
                                "latency": agent_thought.latency,
                            })
                    else:
                        # 19.处理其他类型事件的消息
                        agent_thoughts[event_id] = agent_thought
                usage_summary = summarize_agent_thoughts(agent_thoughts.values())
                data = {
                    **agent_thought.model_dump(include={
                        "event", "thought", "observation", "tool", "tool_input", "answer",
                        "total_token_count", "total_price", "latency",
                    }),
                    "aggregate_total_token_count": usage_summary.total_token_count,
                    "aggregate_total_price": usage_summary.total_price,
                    "aggregate_latency": usage_summary.latency,
                    "id": event_id,
                    "conversation_id": str(conversation.id),
                    "message_id": str(message.id),
                    "task_id": str(agent_thought.task_id),
                }
                yield f"event: {agent_thought.event.value}\ndata:{json.dumps(data, ensure_ascii=False, default=str)}\n\n"
        finally:
            # 20.将消息以及推理过程添加到数据库（同步方式）
            # 无论 Agent 流正常完成还是异常终止，都尝试落库已收集的推理过程
            # 避免异常时 message 记录留下 answer="" 的脏数据
            try:
                self.conversation_service.save_agent_thoughts(
                    account_id=account.id,
                    app_id=app.id,
                    app_config=app_config,
                    conversation_id=conversation.id,
                    message_id=message.id,
                    agent_thoughts=[agent_thought for agent_thought in agent_thoughts.values()],
                )
            except Exception:
                logger.warning("WebApp会话落库失败，conversation_id=%s message_id=%s",
                               conversation.id, message.id, exc_info=True)

    def stop_web_app_chat(self, token: str, task_id: UUID, account: Account):
        """根据传递的token+task_id停止与指定WebApp对话"""
        # 1.获取WebApp应用并校验应用是否发布
        self.get_web_app(token)

        # 2.调用智能体队列管理器停止特定服务
        AgentQueueManager.set_stop_flag(task_id, InvokeFrom.WEB_APP.value, account.id)

    def get_conversations(
            self,
            token: str,
            is_pinned: bool,
            account: Account,
            current_page: int = 1,
            page_size: int = 20,
    ) -> list[Conversation]:
        """根据传递的token+is_pinned+account获取指定账号在该WebApp下的会话列表信息"""
        # 1.获取WebApp应用并校验应用是否发布
        app = self.get_web_app(token)

        safe_current_page = max(1, int(current_page or 1))
        safe_page_size = max(1, min(int(page_size or 20), 100))
        offset = (safe_current_page - 1) * safe_page_size

        # 2.筛选过滤并查询数据
        conversations = self.db.session.query(Conversation).filter(
            Conversation.app_id == app.id,
            Conversation.created_by == account.id,
            Conversation.invoke_from == InvokeFrom.WEB_APP.value,
            Conversation.is_pinned == is_pinned,
            Conversation.is_deleted == False
        ).order_by(desc("created_at")).offset(offset).limit(safe_page_size).all()

        return conversations
