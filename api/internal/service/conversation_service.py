from collections import OrderedDict
from datetime import UTC, datetime
import asyncio
import json
import logging
import math
import re
from dataclasses import dataclass
from threading import RLock
from typing import Any, ClassVar
from uuid import UUID, uuid4
from internal.context import current_app
from injector import inject
from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import ChatPromptTemplate
from internal.entity.assistant_agent_entity import ASSISTANT_AGENT_DISPLAY_NAME
from sqlalchemy import desc, func, select
from sqlalchemy.orm import selectinload
from internal.entity.conversation_entity import (
    ConversationInfo,
    SuggestedQuestions, InvokeFrom, MessageStatus,
)
from internal.lib.helper import datetime_to_timestamp
from pkg.paginator import Paginator
from pkg.sqlalchemy import SQLAlchemy
from .base_service import BaseService
from .credit_service import CreditService
from internal.core.agent.entities.queue_entity import AgentThought, QueueEvent
from internal.core.agent.usage_utils import (
    summarize_agent_thoughts,
    charge_for_feature,
    get_openai_callback,
    _UsageTrackingHandler,
)
from internal.extension.async_database_extension import async_db
from internal.model import App, Conversation, Message, MessageAgentThought, Account
from internal.schema.conversation_schema import GetConversationMessagesWithPageReq
from internal.exception import NotFoundException
from internal.service.system_prompt_library_service import SystemPromptLibraryService

logger = logging.getLogger(__name__)


@inject
@dataclass
class ConversationService(BaseService):
    """会话服务"""
    db: SQLAlchemy
    credit_service: CreditService | None = None
    # 会话主题生成结果缓存：仅在最近query变化时才重新调用模型，避免重复消耗token
    _conversation_name_cache_lock: ClassVar[RLock] = RLock()
    _conversation_name_cache: ClassVar[OrderedDict[str, tuple[str, str]]] = OrderedDict()
    SUMMARY_SINGLE_THRESHOLD: ClassVar[int] = 30
    SUMMARY_SEGMENT_SIZE: ClassVar[int] = 20
    _conversation_name_cache_limit: ClassVar[int] = 1024

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

    @classmethod
    def _normalize_conversation_name_query(cls, query: str) -> str:
        """规范化会话命名query，保证缓存键稳定"""
        normalized_query = (query or "").replace("\n", " ")
        if len(normalized_query) > 2000:
            normalized_query = (
                normalized_query[:300]
                + "...[TRUNCATED]..."
                + normalized_query[-300:]
            )
        return normalized_query

    @classmethod
    def _get_cached_conversation_name(
            cls,
            conversation_id: UUID,
            normalized_query: str,
    ) -> str | None:
        """从进程内临时缓存中获取会话主题名称"""
        conversation_cache_key = str(conversation_id)
        with cls._conversation_name_cache_lock:
            cached_data = cls._conversation_name_cache.get(conversation_cache_key)
            if not cached_data:
                return None
            cached_query, cached_name = cached_data
            if cached_query != normalized_query:
                return None
            cls._conversation_name_cache.move_to_end(conversation_cache_key)
            return cached_name

    @classmethod
    def _set_cached_conversation_name(
            cls,
            conversation_id: UUID,
            normalized_query: str,
            conversation_name: str,
    ) -> None:
        """写入会话主题名称缓存，并控制缓存大小"""
        conversation_cache_key = str(conversation_id)
        with cls._conversation_name_cache_lock:
            cls._conversation_name_cache[conversation_cache_key] = (
                normalized_query,
                conversation_name,
            )
            cls._conversation_name_cache.move_to_end(conversation_cache_key)
            while len(cls._conversation_name_cache) > cls._conversation_name_cache_limit:
                cls._conversation_name_cache.popitem(last=False)

    @classmethod
    def _clear_cached_conversation_name(cls, conversation_id: UUID) -> None:
        """清理指定会话的缓存，避免删除会话后仍占用内存"""
        with cls._conversation_name_cache_lock:
            cls._conversation_name_cache.pop(str(conversation_id), None)

    @classmethod
    def _get_credit_service(cls):
        """从依赖注入器获取 CreditService 实例，获取失败返回 None。"""
        try:
            from app.http.module import injector
            return injector.get(CreditService)
        except Exception:
            return None

    @classmethod
    def summary(cls, human_message: str, ai_message: str, old_summary: str = "", account_id: UUID | None = None) -> str:
        """根据传递的人类消息、AI消息还有原始的摘要信息总结生成一段新的摘要"""
        # 1.创建prompt
        prompt = ChatPromptTemplate.from_template(SystemPromptLibraryService().get_prompt_or_default("conversation_summarizer_template"))

        # 2.通过动态模型注册表加载模型（带 API key 注入），避免硬编码静态配置导致 401
        llm = cls._load_summary_llm()

        # 3.构建链应用
        summary_chain = prompt | llm | StrOutputParser()

        # 4.调用链并获取新摘要信息，同时捕获 token 用量用于计费
        invoke_input = {
            "summary": old_summary,
            "new_lines": f"Human: {human_message}\nAI: {ai_message}",
        }
        if get_openai_callback is not None:
            with get_openai_callback() as cb:
                new_summary = summary_chain.invoke(invoke_input)
            token_count = cb.total_tokens
        else:
            handler = _UsageTrackingHandler()
            new_summary = summary_chain.invoke(invoke_input, config={"callbacks": [handler]})
            token_count = handler.total_tokens

        # 5.计费（失败不影响主流程）
        if account_id is not None:
            charge_for_feature(cls._get_credit_service(), account_id, "conversation_summary", token_count)

        return new_summary

    @classmethod
    def _load_summary_llm(cls):
        """加载摘要任务用的 LLM，统一走数据库配置 + compatible_api 分发。"""
        from app.http.module import injector
        from internal.service.language_model_service import LanguageModelService
        return LanguageModelService.get_feature_model("conversation_summary")

    @classmethod
    def generate_conversation_name(cls, query: str, account_id: UUID | None = None) -> str:
        """根据传递的query生成对应的会话名字，并且语言与用户的输入保持一致"""
        # 1.创建prompt
        prompt = ChatPromptTemplate.from_messages([
            ("system", SystemPromptLibraryService().get_prompt_or_default("conversation_name_template")),
            ("human", "{query}")
        ])

        # 2.通过动态模型注册表加载模型（带 API key 注入），避免硬编码静态配置导致 401
        llm = cls._load_summary_llm()
        structured_llm = llm.with_structured_output(ConversationInfo)

        # 3.构建链应用
        chain = prompt | structured_llm

        # 4.提取并整理query，截取长度过长的部分
        query = cls._normalize_conversation_name_query(query)

        # 5.调用链并获取会话信息，同时捕获 token 用量用于计费
        invoke_input = {"query": query}
        try:
            if get_openai_callback is not None:
                with get_openai_callback() as cb:
                    conversation_info = chain.invoke(invoke_input)
                token_count = cb.total_tokens
            else:
                handler = _UsageTrackingHandler()
                conversation_info = chain.invoke(invoke_input, config={"callbacks": [handler]})
                token_count = handler.total_tokens
        except Exception:
            logging.warning("生成会话名称失败，使用默认会话名", exc_info=True)
            return "新的会话"

        # 6.计费（失败不影响主流程）
        if account_id is not None:
            charge_for_feature(cls._get_credit_service(), account_id, "conversation_summary", token_count)

        # 7.提取会话名称
        name = "新的会话"
        try:
            if conversation_info and hasattr(conversation_info, "subject"):
                name = conversation_info.subject
        except Exception as e:
            logging.exception(f"提取会话名称出错, conversation_info: {conversation_info}, 错误信息: {str(e)}")
        if len(name) > 120:
            name = name[:120] + "..."

        return name

    @classmethod
    def _parse_suggested_questions(cls, response) -> list[str]:
        """从普通文本或对象响应中解析建议问题列表。"""
        questions: list[str] = []
        if response is None:
            return questions

        if isinstance(response, dict):
            raw = response.get("questions") or response.get("content") or ""
        elif isinstance(response, str):
            raw = response
        else:
            raw = getattr(response, "content", "") or str(response)

        if isinstance(raw, list):
            questions = [str(item).strip() for item in raw if str(item).strip()]
        elif isinstance(raw, str):
            text = raw.strip()
            text = re.sub(r"^```(?:json)?\s*", "", text)
            text = re.sub(r"\s*```$", "", text)
            match = re.search(r"\[.*\]", text, re.S)
            if match:
                try:
                    parsed = json.loads(match.group(0))
                    if isinstance(parsed, list):
                        questions = [str(item).strip() for item in parsed if str(item).strip()]
                except Exception:
                    questions = []
            if not questions:
                questions = [
                    line.strip().lstrip("-*").strip()
                    for line in text.splitlines()
                    if line.strip()
                ]

        return [question for question in questions if question][:3]

    @classmethod
    def generate_suggested_questions(cls, histories: str) -> list[str]:
        """根据传递的历史信息生成最多不超过3个的建议问题"""
        # 1.创建prompt
        prompt = ChatPromptTemplate.from_messages([
            ("system", SystemPromptLibraryService().get_prompt_or_default("conversation_suggested_questions_template")),
            ("human", "{histories}")
        ])

        # 2.通过动态模型注册表加载模型，避免硬编码静态配置导致 401
        llm = cls._load_summary_llm()
        structured_llm = llm.with_structured_output(SuggestedQuestions)

        # 3.构建链应用
        chain = prompt | structured_llm

        # 4.调用链并获取建议问题列表
        try:
            suggested_questions = chain.invoke({"histories": histories})
        except Exception as exc:
            logging.warning("建议问题结构化输出失败，降级为文本解析: %s", exc)
            try:
                plain_response = (prompt | llm).invoke({"histories": histories})
                return cls._parse_suggested_questions(plain_response)
            except Exception as fallback_exc:
                logging.exception("建议问题文本兜底失败: %s", fallback_exc)
                return []

        # 5.提取建议问题列表
        questions = []
        try:
            if suggested_questions and hasattr(suggested_questions, "questions"):
                questions = suggested_questions.questions
        except Exception as e:
            logging.exception(f"生成建议问题出错, suggested_questions: {suggested_questions}, 错误信息: {str(e)}")
        if len(questions) > 3:
            questions = questions[:3]

        return questions

    def save_agent_thoughts(
        self,
        account_id: UUID,
        app_id: UUID,
        app_config: dict[str, Any],
        conversation_id: UUID,
        message_id: UUID,
        agent_thoughts: list[AgentThought],
        routing_decision: dict[str, Any] | None = None,
    ):
        """存储智能体推理步骤消息"""
        # 1.定义变量存储推理位置及总耗时
        position = 0
        usage_summary = summarize_agent_thoughts(agent_thoughts)

        # 2.在子线程中重新查询conversation以及message，确保对象会被子线程的会话管理到
        conversation = self.get(Conversation, conversation_id)
        message = self.get(Message, message_id)

        # 3.循环遍历所有的智能体推理过程执行存储操作
        for agent_thought in agent_thoughts:
            # 4.存储长期记忆召回、推理、消息、动作、知识库检索等步骤
            if agent_thought.event in [
                QueueEvent.LONG_TERM_MEMORY_RECALL.value,
                QueueEvent.AGENT_THOUGHT.value,
                QueueEvent.AGENT_MESSAGE.value,
                QueueEvent.AGENT_ACTION.value,
                QueueEvent.DATASET_RETRIEVAL.value,
                QueueEvent.DEEP_THINKING.value,
                QueueEvent.DEEP_STEP.value,
                QueueEvent.DEEP_COMPLETE.value,
                QueueEvent.DEEP_ARTIFACT_CREATED.value,
            ]:
                # 5.更新位置及总耗时
                position += 1

                # 6.创建智能体消息推理步骤
                self.create(
                    MessageAgentThought,
                    app_id=app_id,
                    conversation_id=conversation.id,
                    message_id=message.id,
                    invoke_from=message.invoke_from,
                    created_by=account_id,
                    position=position,
                    event=agent_thought.event,
                    thought=agent_thought.thought,
                    observation=agent_thought.observation,
                    tool=agent_thought.tool,
                    tool_input=agent_thought.tool_input,
                    # 消息相关数据
                    message=agent_thought.message,
                    message_token_count=agent_thought.message_token_count,
                    message_unit_price=agent_thought.message_unit_price,
                    message_price_unit=agent_thought.message_price_unit,
                    # 答案相关字段
                    answer=agent_thought.answer,
                    answer_token_count=agent_thought.answer_token_count,
                    answer_unit_price=agent_thought.answer_unit_price,
                    answer_price_unit=agent_thought.answer_price_unit,
                    # Agent推理统计相关
                    total_token_count=agent_thought.total_token_count,
                    total_price=agent_thought.total_price,
                    latency=agent_thought.latency,
                )

            # 7.检测事件是否为Agent_message
            if agent_thought.event == QueueEvent.AGENT_MESSAGE.value:
                # 8.更新消息信息
                logging.info(f"Updating message {message_id} with answer: {agent_thought.answer}")
                self.update(
                    message,
                    # 消息相关字段
                    message=agent_thought.message,
                    message_token_count=agent_thought.message_token_count,
                    message_unit_price=agent_thought.message_unit_price,
                    message_price_unit=agent_thought.message_price_unit,
                    # 答案相关字段
                    answer=agent_thought.answer,
                    answer_token_count=agent_thought.answer_token_count,
                    answer_unit_price=agent_thought.answer_unit_price,
                    answer_price_unit=agent_thought.answer_price_unit,
                    # Agent推理统计相关
                    total_token_count=usage_summary.total_token_count,
                    total_price=usage_summary.total_price,
                    latency=usage_summary.latency,
                )

                # 9.检测是否开启长期记忆
                if (app_config.get("long_term_memory") or {}).get("enable", False):
                    self._generate_summary_and_update(
                        conversation_id=conversation_id,
                        query=message.query,
                        answer=message.answer,
                        account_id=account_id,
                    )

                # 10.处理生成新会话名称（兜底处理首轮异常导致名称未更新）
                if conversation.is_new or conversation.name == "New Conversation":
                    self._generate_conversation_name_and_update(
                        conversation_id=conversation.id,
                        query=message.query,
                        account_id=account_id,
                    )

            # 11.判断是否为停止或者错误，如果是则需要更新消息状态
            if agent_thought.event in [QueueEvent.TIMEOUT.value, QueueEvent.STOP.value, QueueEvent.ERROR.value]:
                self.update(
                    message,
                    status=agent_thought.event,
                    error=agent_thought.observation,
                )
                break

        if usage_summary.total_token_count > 0 and self.credit_service is not None:
            self.credit_service.consume_for_message(
                account_id,
                message.id,
                token_count=usage_summary.total_token_count,
            )

    def _generate_summary_and_update(
            self,
            conversation_id: UUID,
            query: str,
            answer: str,
            account_id: UUID | None = None,
    ):
        conversation = self.get(Conversation, conversation_id)

        new_summary = self.summary(
            query,
            answer,
            conversation.summary,
            account_id=account_id,
        )

        message_count = self._count_conversation_messages(conversation_id)

        if message_count <= self.SUMMARY_SINGLE_THRESHOLD:
            self.update(conversation, summary=new_summary)
            return

        last_index = conversation.last_summarized_message_index or 0
        if message_count - last_index >= self.SUMMARY_SEGMENT_SIZE:
            distant_summaries = list(conversation.distant_summaries or [])
            if conversation.summary:
                distant_summaries.append(conversation.summary)
            self.update(
                conversation,
                summary=new_summary,
                distant_summaries=distant_summaries,
                last_summarized_message_index=message_count,
            )
        else:
            self.update(conversation, summary=new_summary)

    def _count_conversation_messages(self, conversation_id: UUID) -> int:
        return self.db.session.query(func.count(Message.id)).filter(
            Message.conversation_id == conversation_id,
            Message.is_deleted == False,
        ).scalar() or 0

    def _generate_conversation_name_and_update(
            self,
            conversation_id: UUID,
            query: str,
            account_id: UUID | None = None,
    ) -> None:
        """生成会话名字并更新"""
        # 1.根据会话id获取会话
        conversation = self.get(Conversation, conversation_id)
        normalized_query = self._normalize_conversation_name_query(query)

        # 2.命中同query缓存时直接复用主题，避免重复调用模型
        cached_conversation_name = self._get_cached_conversation_name(
            conversation_id=conversation_id,
            normalized_query=normalized_query,
        )
        if cached_conversation_name:
            if conversation.name != cached_conversation_name:
                self.update(
                    conversation,
                    name=cached_conversation_name,
                )
            return

        # 3.同query无缓存时，调用模型重新生成主题并写入临时缓存
        new_conversation_name = self.generate_conversation_name(normalized_query, account_id=account_id)
        self._set_cached_conversation_name(
            conversation_id=conversation_id,
            normalized_query=normalized_query,
            conversation_name=new_conversation_name,
        )

        # 4.调用更新服务更新会话名称
        if conversation.name != new_conversation_name:
            self.update(
                conversation,
                name=new_conversation_name,
            )



    def get_conversation(self, conversation_id: UUID, account: Account) -> Conversation:
        """根据传递的会话id+account获取指定的会话消息"""
        # 1.根据conversation_id查询指定的会话消息
        conversation = self.get(Conversation, conversation_id)
        if (
            not conversation
            or conversation.created_by != account.id
            or conversation.is_deleted
        ):
            raise NotFoundException("该会话不存在或被删除 请核实后重试")

        # 2.校验通过返回会话d
        return conversation

    def get_recent_conversations(self, account: Account, limit: int = 20) -> list[dict]:
        """获取当前账号最近会话列表（包含辅助Agent与应用调试会话）"""
        safe_limit = max(1, min(limit, 1000))
        message_scan_limit = max(80, safe_limit * 30)

        # 1.查询当前账号的私有最近消息，并按会话去重
        private_recent_messages = (
            self.db.session.query(Message)
            .filter(
                Message.created_by == account.id,
                Message.invoke_from.in_(
                    [
                        InvokeFrom.ASSISTANT_AGENT.value,
                        InvokeFrom.DEBUGGER.value,
                        InvokeFrom.SCHEDULE.value,
                    ]
                ),
                Message.status.in_([MessageStatus.STOP.value, MessageStatus.NORMAL.value]),
                Message.answer != "",
                ~Message.is_deleted,
            )
            .order_by(desc(Message.created_at))
            .limit(message_scan_limit)
            .all()
        )

        # 2.查询公开广场产生的最近消息，并按会话去重
        public_recent_messages = (
            self.db.session.query(Message)
            .filter(
                Message.invoke_from == InvokeFrom.SERVICE_API.value,
                Message.status.in_([MessageStatus.STOP.value, MessageStatus.NORMAL.value]),
                Message.answer != "",
                ~Message.is_deleted,
            )
            .order_by(desc(Message.created_at))
            .limit(message_scan_limit)
            .all()
        )

        message_by_conversation = OrderedDict()
        for message in private_recent_messages + public_recent_messages:
            if message.conversation_id in message_by_conversation:
                continue
            message_by_conversation[message.conversation_id] = message
            if len(message_by_conversation) >= safe_limit:
                break

        if not message_by_conversation:
            return []

        conversation_ids = list(message_by_conversation.keys())

        # 3.批量查询会话数据，只允许当前账号私有会话或公开服务会话进入列表
        conversations = (
            self.db.session.query(Conversation)
            .filter(
                Conversation.id.in_(conversation_ids),
                (
                    (Conversation.created_by == account.id)
                    | (Conversation.invoke_from == InvokeFrom.SERVICE_API.value)
                ),
                ~Conversation.is_deleted,
            )
            .all()
        )
        conversation_map = {conversation.id: conversation for conversation in conversations}

        # 4.为调试会话、公开应用会话批量查询应用信息，以及为assistant_agent查询应用名称
        app_ids = {
            message.app_id
            for message in message_by_conversation.values()
            if message.invoke_from in (
                InvokeFrom.DEBUGGER.value,
                InvokeFrom.SERVICE_API.value,
            )
        }

        # 添加assistant_agent的应用id
        assistant_agent_id = current_app.config.get("ASSISTANT_AGENT_ID")
        for message in message_by_conversation.values():
            if message.invoke_from == InvokeFrom.ASSISTANT_AGENT.value and assistant_agent_id:
                app_ids.add(assistant_agent_id)

        apps = (
            self.db.session.query(App)
            .filter(App.id.in_(app_ids))
            .all()
            if app_ids
            else []
        )
        app_map = {app.id: app for app in apps}

        # 5.组装响应列表（共享纯逻辑，供同步/异步版本复用）
        return self._build_recent_conversation_results(
            message_by_conversation,
            conversation_map,
            app_map,
            account,
            assistant_agent_id,
        )

    def _build_recent_conversation_results(
        self,
        message_by_conversation: OrderedDict,
        conversation_map: dict,
        app_map: dict,
        account: Account,
        assistant_agent_id: str | None,
    ) -> list[dict]:
        """组装最近会话响应列表（纯逻辑，不依赖 app context）。"""
        results = []
        for message in message_by_conversation.values():
            conversation = conversation_map.get(message.conversation_id)
            if not conversation:
                continue

            source_type = (
                "schedule"
                if message.invoke_from == InvokeFrom.SCHEDULE.value
                else "assistant_agent"
                if message.invoke_from == InvokeFrom.ASSISTANT_AGENT.value
                else "public_app"
                if message.invoke_from == InvokeFrom.SERVICE_API.value
                else "app_debugger"
            )
            app_id = ""
            app_name = ""
            agent_name = ""
            is_active = False

            if source_type == "assistant_agent":
                agent_name = ASSISTANT_AGENT_DISPLAY_NAME
                is_active = account.assistant_agent_conversation_id == conversation.id
            elif source_type == "schedule":
                app_id = str(message.app_id) if message.app_id else ""
            else:
                app = app_map.get(message.app_id)
                if not app:
                    continue
                app_id = str(app.id)
                app_name = app.name
                if source_type == "app_debugger":
                    is_active = app.debug_conversation_id == conversation.id

            results.append(
                {
                    "id": str(conversation.id),
                    "name": conversation.name,
                    "source_type": source_type,
                    "invoke_from": conversation.invoke_from or message.invoke_from,
                    "app_id": app_id,
                    "app_name": app_name,
                    "agent_name": agent_name,
                    "message_id": str(message.id),
                    "is_active": is_active,
                    "latest_message_at": datetime_to_timestamp(message.created_at),
                    "created_at": datetime_to_timestamp(conversation.created_at),
                    "human_message": message.query,
                    "ai_message": message.answer,
                }
            )

        return results

    async def get_recent_conversations_async(
        self,
        account: Account,
        limit: int = 20,
        assistant_agent_id: str | None = None,
    ) -> list[dict]:
        """异步版本：async session 直查最近会话列表，不占用工作线程。

        async 数据库未启用时降级到同步实现（asyncio.to_thread 线程池执行），
        保证在任何部署形态下都可用。
        """
        session = async_db.session_factory()
        if session is None:
            return await asyncio.to_thread(self.get_recent_conversations, account, limit)

        safe_limit = max(1, min(limit, 1000))
        message_scan_limit = max(80, safe_limit * 30)

        async with session as session:
            private_recent_messages = list(
                (
                    await session.scalars(
                        select(Message)
                        .where(
                            Message.created_by == account.id,
                            Message.invoke_from.in_(
                                [
                                    InvokeFrom.ASSISTANT_AGENT.value,
                                    InvokeFrom.DEBUGGER.value,
                                    InvokeFrom.SCHEDULE.value,
                                ]
                            ),
                            Message.status.in_(
                                [MessageStatus.STOP.value, MessageStatus.NORMAL.value]
                            ),
                            Message.answer != "",
                            ~Message.is_deleted,
                        )
                        .order_by(desc(Message.created_at))
                        .limit(message_scan_limit)
                    )
                ).all()
            )
            public_recent_messages = list(
                (
                    await session.scalars(
                        select(Message)
                        .where(
                            Message.invoke_from == InvokeFrom.SERVICE_API.value,
                            Message.status.in_(
                                [MessageStatus.STOP.value, MessageStatus.NORMAL.value]
                            ),
                            Message.answer != "",
                            ~Message.is_deleted,
                        )
                        .order_by(desc(Message.created_at))
                        .limit(message_scan_limit)
                    )
                ).all()
            )

            message_by_conversation = OrderedDict()
            for message in private_recent_messages + public_recent_messages:
                if message.conversation_id in message_by_conversation:
                    continue
                message_by_conversation[message.conversation_id] = message
                if len(message_by_conversation) >= safe_limit:
                    break

            if not message_by_conversation:
                return []

            conversation_ids = list(message_by_conversation.keys())

            conversations = list(
                (
                    await session.scalars(
                        select(Conversation)
                        .where(
                            Conversation.id.in_(conversation_ids),
                            (
                                (Conversation.created_by == account.id)
                                | (
                                    Conversation.invoke_from
                                    == InvokeFrom.SERVICE_API.value
                                )
                            ),
                            ~Conversation.is_deleted,
                        )
                    )
                ).all()
            )
            conversation_map = {conversation.id: conversation for conversation in conversations}

            app_ids = {
                message.app_id
                for message in message_by_conversation.values()
                if message.invoke_from
                in (
                    InvokeFrom.DEBUGGER.value,
                    InvokeFrom.SERVICE_API.value,
                )
            }
            if assistant_agent_id:
                for message in message_by_conversation.values():
                    if message.invoke_from == InvokeFrom.ASSISTANT_AGENT.value:
                        app_ids.add(assistant_agent_id)

            app_map = {}
            if app_ids:
                apps = list(
                    (
                        await session.scalars(select(App).where(App.id.in_(app_ids)))
                    ).all()
                )
                app_map = {app.id: app for app in apps}

        return self._build_recent_conversation_results(
            message_by_conversation,
            conversation_map,
            app_map,
            account,
            assistant_agent_id,
        )

    def get_message(self, message_id: UUID, account: Account) -> Message:
        """根据传递的消息id+账号，获取指定的消息"""
        # 1.根据message_id查询消息记录
        message = self.get(Message, message_id)
        if (
                not message
                or message.created_by != account.id
                or message.is_deleted
        ):
            raise NotFoundException("该消息不存在或被删除，请核实后重试")

        # 2.校验通过返回消息
        return message

    def get_conversation_messages_with_page(
            self,
            conversation_id: UUID,
            req: GetConversationMessagesWithPageReq,
            account: Account,
    ) -> tuple[list[Message], Paginator]:
        """根据传递的会话id+请求数据 获取当前账号下该会话的消息分页列表数据"""
        # 1.获取会话并校验权限
        conversation = self.get_conversation(conversation_id, account)

        # 2.构建分页器并设置过滤条件
        paginator = Paginator(db=self.db, req=req)
        filters = [
            Message.conversation_id == conversation_id,
            Message.status.in_([MessageStatus.STOP.value, MessageStatus.NORMAL.value]),
            Message.answer != "",
            Message.is_deleted == False,
        ]

        if req.created_at.data:
            created_at_datetime = datetime.fromtimestamp(req.created_at.data, UTC)
            filters.append(Message.created_at <= created_at_datetime)

        # 3.先分页查询ID列表
        paginated_ids = paginator.paginate(
            self.db.session.query(Message.id)
            .filter(*filters)
            .order_by(desc(Message.created_at), desc(Message.id))
        )

        normalized_ids = self._normalize_paginated_ids(paginated_ids)
        if not normalized_ids:
            return [], paginator

        # 4.再根据ID查询完整的消息及其关联内容
        messages = (
            self.db.session.query(Message)
            .options(selectinload(Message.agent_thoughts))
            .filter(Message.id.in_(normalized_ids))
            .order_by(desc(Message.created_at), desc(Message.id))
            .all()
        )

        return messages, paginator

    async def get_conversation_messages_with_page_async(
        self,
        conversation_id: UUID,
        req: GetConversationMessagesWithPageReq,
        account: Account,
    ) -> tuple[list[Message], Paginator]:
        """异步版本：async session 直查会话消息分页，不占用工作线程。

        async 数据库未启用时降级到同步实现（asyncio.to_thread 线程池执行），
        保证在任何部署形态下都可用。
        """
        session = async_db.session_factory()
        if session is None:
            return await asyncio.to_thread(
                self.get_conversation_messages_with_page,
                conversation_id,
                req,
                account,
            )

        current_page = max(1, req.current_page.data or 1)
        page_size = max(1, min(req.page_size.data or 20, 50))

        async with session as session:
            # 1.获取会话并校验权限
            conversation = await session.scalar(
                select(Conversation).where(
                    Conversation.id == conversation_id,
                    Conversation.created_by == account.id,
                    ~Conversation.is_deleted,
                )
            )
            if conversation is None:
                raise NotFoundException("该会话不存在或被删除 请核实后重试")

            # 2.构建过滤条件
            filters = [
                Message.conversation_id == conversation_id,
                Message.status.in_(
                    [MessageStatus.STOP.value, MessageStatus.NORMAL.value]
                ),
                Message.answer != "",
                Message.is_deleted == False,
            ]
            if req.created_at.data:
                created_at_datetime = datetime.fromtimestamp(req.created_at.data, UTC)
                filters.append(Message.created_at <= created_at_datetime)

            # 3.查询总数
            total = (
                await session.scalar(
                    select(func.count()).select_from(Message).where(*filters)
                )
            ) or 0

            # 4.分页查询完整消息（含 agent_thoughts 预加载）
            messages = list(
                (
                    await session.scalars(
                        select(Message)
                        .options(selectinload(Message.agent_thoughts))
                        .where(*filters)
                        .order_by(desc(Message.created_at), desc(Message.id))
                        .offset((current_page - 1) * page_size)
                        .limit(page_size)
                    )
                ).all()
            )

        paginator = Paginator(db=self.db)
        paginator.current_page = current_page
        paginator.page_size = page_size
        paginator.total_record = total
        paginator.total_page = math.ceil(total / page_size) if total else 0
        return messages, paginator

    def delete_conversation(
        self,
        conversation_id: UUID,
        account: Account,
        *,
        retention_days: int | None = None,
        agent_id=None,
    ) -> Conversation:
        """根据传递的会话id+账号删除指定的会话记录（软删除 + 入回收站）"""
        # 1.获取会话记录并校验权限
        conversation = self.get_conversation(conversation_id, account)

        # 2.如果删除的是当前活跃会话，则同步清理账号/应用指针
        if (
            conversation.invoke_from == InvokeFrom.ASSISTANT_AGENT.value
            and account.assistant_agent_conversation_id == conversation.id
        ):
            self.update(account, assistant_agent_conversation_id=None)
        elif conversation.invoke_from == InvokeFrom.DEBUGGER.value and conversation.app_id:
            app = self.get(App, conversation.app_id)
            if app and app.account_id == account.id and app.debug_conversation_id == conversation.id:
                self.update(app, debug_conversation_id=None)

        # 3.更新会话的删除状态
        self.update(conversation, is_deleted=True)
        self._clear_cached_conversation_name(conversation_id)

        # 4.进入平台回收站（软删除模式：数据保留，恢复时翻转 is_deleted；
        #    留存期到期由回收站 purge 物理清理会话与消息）
        try:
            from internal.service.recycle_bin_service import RecycleBinService

            RecycleBinService().delete_resource(
                resource_type="conversation",
                resource_id=conversation.id,
                resource_key=str(conversation.id),
                resource_name=conversation.name or "未命名会话",
                deleted_by=str(account.id),
                deleted_by_type="user",
                retention_days=retention_days,
                agent_id=agent_id,
            )
        except Exception:
            logger.warning("会话入回收站失败 id=%s", conversation_id, exc_info=True)

        return conversation

    def delete_message(self, conversation_id: UUID, message_id: UUID, account: Account) -> Message:
        """根据传递的会话id+消息id删除指定的消息记录"""
        # 1.获取会话记录并校验权限
        conversation = self.get_conversation(conversation_id, account)

        # 2.获取消息并校验权限
        message = self.get_message(message_id, account)

        # 3.判断消息和会话是否关联
        if conversation.id != message.conversation_id:
            raise NotFoundException("该会话下不存在该消息，请核实后重试")

        # 4.校验通过修改消息is_deleted属性标记删除
        self.update(message, is_deleted=True)

        return message

    def update_conversation(self, conversation_id: UUID, account: Account, **kwargs) -> Conversation:
        """根据传递的会话id+账号+kwargs更新会话信息"""
        # 1.获取会话记录并校验权限
        conversation = self.get_conversation(conversation_id, account)

        # 2.更新会话信息
        self.update(conversation, **kwargs)

        return conversation

    @staticmethod
    def _search_contains(text: str | None, query_lower: str) -> bool:
        """判断文本是否包含搜索词"""
        return bool(text) and query_lower in text.lower()

    @classmethod
    def _extract_search_snippet(cls, text: str | None, query_lower: str, max_chars: int = 240) -> str:
        """提取命中搜索词的消息片段，优先保留完整行以兼容 markdown 预览"""
        if not text:
            return ""

        content = str(text).strip()
        if not content:
            return ""

        if not cls._search_contains(content, query_lower):
            return content if len(content) <= max_chars else content[:max_chars].rstrip() + "..."

        lines = content.splitlines()
        if len(lines) > 1:
            for index, line in enumerate(lines):
                if not cls._search_contains(line, query_lower):
                    continue

                start_line = max(0, index - 1)
                end_line = min(len(lines), index + 2)
                snippet = "\n".join(lines[start_line:end_line]).strip()
                if snippet and len(snippet) <= max_chars:
                    prefix = "...\n" if start_line > 0 else ""
                    suffix = "\n..." if end_line < len(lines) else ""
                    return f"{prefix}{snippet}{suffix}".strip()
                break

        keyword_index = content.lower().find(query_lower)
        context_size = max(80, (max_chars - len(query_lower)) // 2)
        start = max(0, keyword_index - context_size)
        end = min(len(content), keyword_index + len(query_lower) + context_size)
        snippet = content[start:end].strip()

        prefix = "..." if start > 0 else ""
        suffix = "..." if end < len(content) else ""
        return f"{prefix}{snippet}{suffix}"

    @staticmethod
    def _dedupe_match_fields(fields_list: list[str]) -> list[str]:
        """保持顺序去重搜索命中字段"""
        deduped_fields = []
        seen_fields = set()
        for field in fields_list:
            if field in seen_fields:
                continue
            seen_fields.add(field)
            deduped_fields.append(field)
        return deduped_fields

    def search_conversations(self, account: Account, query: str, limit: int = 50) -> list[dict]:
        """搜索会话及其消息内容"""
        safe_limit = max(1, min(limit, 100))

        # 1.如果查询为空，返回最近会话
        if not query or not query.strip():
            return self.get_recent_conversations(account, safe_limit)

        query_lower = query.strip().lower()

        # 2.查询当前账号的消息
        messages = (
            self.db.session.query(Message)
            .filter(
                Message.created_by == account.id,
                Message.invoke_from.in_(
                    [
                        InvokeFrom.ASSISTANT_AGENT.value,
                        InvokeFrom.DEBUGGER.value,
                        InvokeFrom.SCHEDULE.value,
                    ]
                ),
                Message.status.in_([MessageStatus.STOP.value, MessageStatus.NORMAL.value]),
                Message.answer != "",
                ~Message.is_deleted,
            )
            .order_by(desc(Message.created_at))
            .all()
        )
        # 3.收集每个会话的最新消息以及真正命中的消息片段
        latest_message_by_conversation: dict[UUID, Message] = {}
        matched_message_by_conversation: dict[UUID, dict[str, Any]] = {}
        for message in messages:
            conversation_id = getattr(message, "conversation_id", None)
            if conversation_id is None:
                continue
            if conversation_id not in latest_message_by_conversation:
                latest_message_by_conversation[message.conversation_id] = message

            matched_fields = []
            if self._search_contains(message.query, query_lower):
                matched_fields.append("human_message")
            if self._search_contains(message.answer, query_lower):
                matched_fields.append("ai_message")

            if not matched_fields or message.conversation_id in matched_message_by_conversation:
                continue

            matched_message_by_conversation[message.conversation_id] = {
                "message": message,
                "matched_fields": matched_fields,
                "human_message": self._extract_search_snippet(message.query, query_lower)
                if "human_message" in matched_fields else "",
                "ai_message": self._extract_search_snippet(message.answer, query_lower)
                if "ai_message" in matched_fields else "",
            }

        # 4.查询账号会话，统一判断标题/应用/助手/消息命中
        conversations = (
            self.db.session.query(Conversation)
            .filter(
                Conversation.created_by == account.id,
                ~Conversation.is_deleted,
            )
            .all()
        )

        if not conversations:
            return []

        # 5.为调试会话批量查询应用信息，以及为assistant_agent查询应用名称
        app_ids = {
            message.app_id
            for message in latest_message_by_conversation.values()
            if message.invoke_from == InvokeFrom.DEBUGGER.value and message.app_id is not None
        }

        # 添加assistant_agent的应用id
        assistant_agent_id = current_app.config.get("ASSISTANT_AGENT_ID")
        if assistant_agent_id:
            app_ids.add(assistant_agent_id)

        apps = (
            self.db.session.query(App)
            .filter(App.id.in_(app_ids))
            .all()
            if app_ids
            else []
        )
        app_map = {app.id: app for app in apps}

        # 6.组装响应列表，human_message/ai_message 仅返回真正命中的 QA 片段
        results = []
        for conversation in conversations:
            latest_message = latest_message_by_conversation.get(conversation.id)
            matched_message_entry = matched_message_by_conversation.get(conversation.id)
            preview_message = matched_message_entry["message"] if matched_message_entry else latest_message
            source_type = (
                "assistant_agent"
                if latest_message is None or latest_message.invoke_from == InvokeFrom.ASSISTANT_AGENT.value
                else "schedule"
                if latest_message.invoke_from == InvokeFrom.SCHEDULE.value
                else "app_debugger"
            )
            app_id = ""
            app_name = ""
            agent_name = ""
            is_active = False

            if source_type == "app_debugger" and latest_message is not None:
                app = app_map.get(latest_message.app_id)
                if not app:
                    continue
                app_id = str(app.id)
                app_name = app.name
                is_active = app.debug_conversation_id == conversation.id
            elif source_type == "assistant_agent":
                agent_name = ASSISTANT_AGENT_DISPLAY_NAME
                is_active = account.assistant_agent_conversation_id == conversation.id

            matched_fields = []
            if self._search_contains(conversation.name, query_lower):
                matched_fields.append("name")
            if self._search_contains(app_name, query_lower):
                matched_fields.append("app_name")
            if self._search_contains(agent_name, query_lower):
                matched_fields.append("agent_name")
            if matched_message_entry:
                matched_fields.extend(matched_message_entry["matched_fields"])

            matched_fields = self._dedupe_match_fields(matched_fields)
            if not matched_fields:
                continue

            preview_timestamp_source = preview_message.created_at if preview_message else conversation.created_at

            results.append(
                {
                    "id": str(conversation.id),
                    "name": conversation.name,
                    "source_type": source_type,
                    "invoke_from": conversation.invoke_from
                    or (preview_message.invoke_from if preview_message else ""),
                    "app_id": app_id,
                    "app_name": app_name,
                    "agent_name": agent_name,
                    "message_id": str(preview_message.id) if preview_message and preview_message.id else "",
                    "is_active": is_active,
                    "human_message": matched_message_entry["human_message"] if matched_message_entry else "",
                    "ai_message": matched_message_entry["ai_message"] if matched_message_entry else "",
                    "matched_fields": matched_fields,
                    "latest_message_at": datetime_to_timestamp(preview_timestamp_source),
                    "created_at": datetime_to_timestamp(conversation.created_at),
                }
            )

        results.sort(key=lambda item: item["latest_message_at"], reverse=True)
        return results[:safe_limit]
