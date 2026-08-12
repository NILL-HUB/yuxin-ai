import hashlib
import json
import logging
import re

logger = logging.getLogger(__name__)

from dataclasses import dataclass
from datetime import UTC, datetime
from threading import Lock, Thread
from typing import Any, Generator
from uuid import UUID

from internal.context import current_app, has_app_context
from injector import inject
from redis import Redis
from langchain_core.messages import (
    HumanMessage,
    SystemMessage,
    trim_messages,
)
from langchain_core.tools import BaseTool, tool
from pydantic import BaseModel, Field
from sqlalchemy import and_, desc
from sqlalchemy.orm import selectinload

from internal.core.agent.agents import (
    A2ADeepThinkingAgent,
    FunctionCallAgent,
    AgentQueueManager,
)
from internal.core.agent.entities.agent_entity import AgentConfig
from internal.core.agent.entities.queue_entity import QueueEvent
from internal.core.agent.usage_utils import (
    charge_for_feature,
    extract_token_usage_from_stream,
)
from internal.entity.assistant_agent_entity import ASSISTANT_AGENT_DISPLAY_NAME
from internal.entity.cancel_token_entity import CancelToken
from internal.core.language_model.entities.model_entity import ModelFeature
from internal.core.memory import TokenBufferMemory
from internal.entity.conversation_entity import InvokeFrom, MessageStatus
from internal.lib.helper import datetime_to_timestamp
from internal.model import Account, Conversation, Message
from internal.schema.assistant_agent_schema import (
    AssistantAgentChat,
    GetAssistantAgentConversationsReq,
    GetAssistantAgentMessagesWithPageReq,
)
from internal.task.app_task import auto_create_app
from internal.exception import NotFoundException
from pkg.paginator import Paginator
from pkg.sqlalchemy import SQLAlchemy

from .base_service import BaseService
from .app_config_service import AppConfigService
from .conversation_service import ConversationService
from .credit_service import CreditService
from .faiss_service import FaissService
from .language_model_service import LanguageModelService
from .orchestrator_service import OrchestratorService
from .routing_log_service import RoutingLogService
from .conductor_service import ConductorService
from .orchestration_feature_flag_service import OrchestrationFeatureFlagService
from .result_synthesizer_service import ResultSynthesizerService
from .retrieval_service import RetrievalService
from .runtime_tool_mount_service import RuntimeToolMountService
from internal.entity.runtime_tool_entity import RuntimeToolDescriptor
from .public_agent_a2a_service import PublicAgentA2AService
from .public_agent_registry_service import PublicAgentRegistryService


def _get_markdown_preset_prompt() -> str:
    """读取首页助手 Markdown 回复规范（系统提示词库可管理，YAML 兜底）。

    默认文本集中在 internal/core/prompts/system_prompts.yaml
    （key=assistant_agent_markdown_preset），管理员可在系统提示词库中编辑覆盖。
    """
    from internal.service.system_prompt_library_service import SystemPromptLibraryService
    return SystemPromptLibraryService().get_prompt_or_default("assistant_agent_markdown_preset")


def _get_system_knowledge_context(db) -> str:
    """读取启用中的系统级知识库内容，注入助手提示词。

    系统知识库（knowledge_scope='system'）中的身份认知等规则文档不应依赖
    模型是否主动调用检索工具，否则“你是什么模型”类问题会退化为模型自述/幻觉。
    """
    try:
        from internal.model import KnowledgeBase, KnowledgeDocument, KnowledgeSegment

        base_ids = [
            base.id
            for base in db.session.query(KnowledgeBase).filter(
                KnowledgeBase.enabled.is_(True),
                KnowledgeBase.knowledge_scope == "system",
            ).all()
            if str(base.name or "").strip() != "系统提示词库"
        ]
        if not base_ids:
            return ""
        rows = (
            db.session.query(KnowledgeSegment)
            .join(KnowledgeDocument, KnowledgeSegment.knowledge_document_id == KnowledgeDocument.id)
            .filter(
                KnowledgeDocument.knowledge_base_id.in_(base_ids),
                KnowledgeDocument.status == "completed",
                KnowledgeSegment.enabled.is_(True),
                KnowledgeSegment.status == "completed",
            )
            .order_by(KnowledgeDocument.created_at.asc(), KnowledgeSegment.position.asc())
            .all()
        )
        parts = [str(row.content or "").strip() for row in rows if str(row.content or "").strip()]
        return "\n\n".join(parts)
    except Exception:
        logger.warning("读取系统知识库上下文失败，跳过", exc_info=True)
        return ""



@inject
@dataclass
class AssistantAgentService(BaseService):
    """辅助智能体服务"""

    db: SQLAlchemy
    faiss_service: FaissService
    conversation_service: ConversationService
    redis_client: Redis
    credit_service: CreditService | None = None
    app_config_service: AppConfigService | None = None
    language_model_service: LanguageModelService | None = None
    public_agent_a2a_service: PublicAgentA2AService | None = None
    public_agent_registry_service: PublicAgentRegistryService | None = None
    orchestrator_service: OrchestratorService | None = None
    conductor_service: ConductorService | None = None
    orchestration_feature_flag_service: OrchestrationFeatureFlagService | None = None
    result_synthesizer_service: ResultSynthesizerService | None = None
    retrieval_service: RetrievalService | None = None
    runtime_tool_mount_service: RuntimeToolMountService | None = None
    routing_log_service: RoutingLogService | None = None
    _introduction_prewarm_lock = Lock()
    _introduction_prewarm_pending = set()
    _active_cancel_tokens = {}

    def _schedule_introduction_prewarm(self, account_id: UUID) -> None:
        """在后台预热首页介绍缓存，降低首页首开 LLM 命中概率。"""
        if not has_app_context():
            return

        if bool(current_app.config.get("TESTING", False)):
            return

        prewarm_flag = current_app.config.get("ASSISTANT_INTRO_PREWARM_ENABLED", True)
        if prewarm_flag is False:
            return

        flask_app = current_app._get_current_object()
        pending_key = str(account_id)
        with self._introduction_prewarm_lock:
            if pending_key in self._introduction_prewarm_pending:
                return
            self._introduction_prewarm_pending.add(pending_key)

        def _worker() -> None:
            try:
                with flask_app.app_context():
                    account = self.get(Account, account_id)
                    if account is None:
                        return
                    for _ in self.generate_introduction(account):
                        pass
            except Exception:
                logger.exception("首页助手介绍预热失败: account_id=%s", account_id)
            finally:
                with self._introduction_prewarm_lock:
                    self._introduction_prewarm_pending.discard(pending_key)

        Thread(target=_worker, daemon=True).start()

    @classmethod
    def _resolve_conversation_id(cls, conversation_id: str) -> UUID | None:
        """将会话id字符串解析成UUID，不存在时返回None"""
        normalized = str(conversation_id or "").strip()
        if not normalized:
            return None
        return UUID(normalized)

    def _resolve_assistant_agent_conversation(
        self,
        account: Account,
        conversation_id: UUID | None = None,
        sync_active: bool = False,
        allowed_invoke_from: str | None = None,
    ) -> Conversation:
        """解析并返回辅助Agent会话，必要时同步账号当前会话指针"""
        if conversation_id is None:
            return self._get_or_create_assistant_agent_conversation(account)

        conversation = self.get(Conversation, conversation_id)
        if (
            not conversation
            or conversation.created_by != account.id
            or conversation.is_deleted
            or conversation.invoke_from != (allowed_invoke_from or InvokeFrom.ASSISTANT_AGENT.value)
        ):
            raise NotFoundException(
                f"该{ASSISTANT_AGENT_DISPLAY_NAME}会话不存在或已被删除，请核实后重试"
            )

        if sync_active and account.assistant_agent_conversation_id != conversation.id:
            self.update(account, assistant_agent_conversation_id=conversation.id)

        return conversation

    def _get_or_create_assistant_agent_conversation(self, account: Account) -> Conversation:
        """返回账号的辅助Agent会话；缺失时通过账号行锁串行创建。

        并发首次访问同一账号时会各自创建会话并写回同一行 account，
        直接依赖 UPDATE 互斥可能产生锁等待甚至超时。这里先对账号行加
        FOR UPDATE 锁，再检查指针，能保证同一账号只创建一个会话、指针不被覆盖。
        """
        if not isinstance(account, Account):
            # 兼容历史测试/调用方传入的会话占位对象
            return account.assistant_agent_conversation

        def _is_valid(candidate: Conversation | None) -> bool:
            return bool(
                candidate
                and not candidate.is_deleted
                and candidate.created_by == account.id
                and candidate.invoke_from == InvokeFrom.ASSISTANT_AGENT.value
            )

        if account.assistant_agent_conversation_id:
            existing = self.get(Conversation, account.assistant_agent_conversation_id)
            if _is_valid(existing):
                return existing

        with self.db.auto_commit():
            locked_account = (
                self.db.session.query(Account)
                .filter(Account.id == account.id)
                .with_for_update()
                .one_or_none()
            )
            target = locked_account or account
            if target.assistant_agent_conversation_id:
                existing = self.get(Conversation, target.assistant_agent_conversation_id)
                if _is_valid(existing):
                    return existing

            assistant_agent_id = current_app.config.get("ASSISTANT_AGENT_ID")
            conversation = Conversation(
                app_id=assistant_agent_id,
                name="New Conversation",
                invoke_from=InvokeFrom.ASSISTANT_AGENT.value,
                created_by=target.id,
            )
            self.db.session.add(conversation)
            self.db.session.flush()
            target.assistant_agent_conversation_id = conversation.id

        return conversation

    def get_capabilities(self) -> dict[str, Any]:
        """返回辅助 Agent 当前可用能力。"""
        if self.language_model_service is None:
            return {
                "requested_model": {},
                "effective_model": {},
                "features": [ModelFeature.TOOL_CALL.value, ModelFeature.AGENT_THOUGHT.value],
                "requested_features": [ModelFeature.TOOL_CALL.value, ModelFeature.AGENT_THOUGHT.value],
                "image_input": {
                    "enabled": False,
                    "via_fallback": False,
                    "policy": LanguageModelService.IMAGE_REQUEST_POLICY_STRICT,
                    "requested_model_supports": False,
                    "effective_model_supports": False,
                    "fallback_model": None,
                    "fallback_model_supports": False,
                    "reason_code": "IMAGE_INPUT_UNSUPPORTED",
                    "message": "当前辅助 Agent 不支持图片输入",
                },
                "image_output": {
                    "enabled": True,
                    "reason_code": "IMAGE_OUTPUT_SUPPORTED",
                },
                "artifact_output": {
                    "enabled": True,
                    "reason_code": "ARTIFACT_OUTPUT_SUPPORTED",
                },
            }
        return self.language_model_service.describe_runtime_capabilities(
            self.language_model_service.get_assistant_agent_model_config(),
            entrypoint=LanguageModelService.ENTRYPOINT_ASSISTANT_AGENT,
        )

    def _stream_deep_thinking_proposal(self, routing_decision: dict):
        """阶段1：判定需要深度思考后，返回提案事件等待用户确认。"""
        import json
        payload = {
            "event": "deep_thinking_proposal",
            "reason": routing_decision.get("reason", ""),
            "estimated_steps": 4,
        }
        yield f"event: deep_thinking_proposal\ndata:{json.dumps(payload, ensure_ascii=False)}\n\n"

    def _stream_insufficient_balance(self):
        """余额不足时返回提示事件。"""
        import json
        payload = {
            "event": "error",
            "message": "账户余额不足，无法执行此任务",
        }
        yield f"event: error\ndata:{json.dumps(payload, ensure_ascii=False)}\n\n"

    def _stream_direct_answer(self, req, account, conversation, message, routing_decision=None, _chat_started_at: float = 0, llm=None, tools=None):
        """direct_answer 路径：真流式 LLM 调用，逐 token yield SSE 事件。

        如果指挥官已给出 direct_answer 内容（routing_decision.task_plan_summary.direct_answer），
        直接使用（答案已完整，用优化参数分块发送）；否则走 DirectAnswerExecutor.stream()
        真 LLM 流式调用，LLM 生成时即可逐 token yield，前端实时渲染。

        Args:
            llm: 外层 chat() 已解析好的 LLM 实例（tier=3，与主路径一致）。
                传入时 DirectAnswerExecutor 直接使用，避免独立解析到不可用模型。
                未传入时 DirectAnswerExecutor 走 get_feature_model() 自行解析（向后兼容）。
            tools: 知识库检索等工具（BaseTool 列表），direct_answer 阶段也能检索系统知识库。
        """
        from internal.entity.billing_metering_entity import BillingEventType
        from internal.service.billing_metering_service import BillingUsageAggregator
        from internal.service.executors.direct_answer_executor import DirectAnswerExecutor
        from internal.service.system_prompt_library_service import SystemPromptLibraryService
        import time

        # 首次使用时把硬编码提示词 seed 到系统提示词库（幂等，管理员编辑不会被覆盖）
        try:
            SystemPromptLibraryService().ensure_seed_prompts()
        except Exception:
            logger.warning("系统提示词库 seed 失败，回退内置默认提示词", exc_info=True)

        billing_aggregator = BillingUsageAggregator(task_id=str(message.id))
        billing_started = billing_aggregator.started()
        yield f"event: {BillingEventType.STARTED.value}\ndata:{json.dumps(billing_started.to_sse())}\n\n"

        # 指挥官 direct_answer 预生成内容不再直接分块发送：
        # 为获得推理过程（reasoning_content）流式显示，统一走 DirectAnswerExecutor.stream()
        # 真实 LLM 流式调用（conductor 预生成答案会被丢弃，避免"丢个答案"现象）

        final_answer = ""
        fallback_msg = ""
        try:
            executor = DirectAnswerExecutor(
                language_model_service=self.language_model_service,
                credit_service=self.credit_service,
                account_id=account.id,
                llm=llm,
                tools=tools or [],
                system_prompt_override=self._build_assistant_system_prompt(),
            )
            # 真流式改造：直接 yield from executor.stream()，LLM 生成时即可逐 token yield
            # 绕过 coordinator.execute() 的同步收集，避免"等完整答案再假分块"的延迟
            # stream() 只负责 token 流（AGENT_MESSAGE），计费/AGENT_END 由本外层统一管理
            # 同时 stream() 会逐 chunk 提取推理过程（reasoning_content），
            # 从 LLM 开始思考时即流式发送 agent_thought 事件，思考框实时显示推理内容
            yield from executor.stream(
                query=req.query.data,
                history=None,
                conversation_id=str(conversation.id),
                message_id=str(message.id),
            )

            # 流结束后从 executor 实例属性读取完整 answer 和 token_usage
            final_answer = executor.last_answer or ""
            token_usage = executor.last_token_usage

            if token_usage:
                billing_delta = billing_aggregator.model_tokens(
                    "direct_answer",
                    input_tokens=token_usage.get("prompt_tokens", 0),
                    output_tokens=token_usage.get("completion_tokens", 0),
                    reason="direct_answer_llm_invoke",
                )
                yield f"event: {BillingEventType.DELTA.value}\ndata:{json.dumps(billing_delta.to_sse())}\n\n"

            if not final_answer:
                # LLM 调用失败或返回空回答时，发送兜底 AGENT_MESSAGE
                # 避免用户看到空响应
                fallback_msg = "未获得有效回答，请稍后重试或换种方式提问。"
                logger.warning("direct_answer 路径未获得有效回答")
                yield f"event: {QueueEvent.AGENT_MESSAGE.value}\ndata:{json.dumps({'answer': fallback_msg, 'id': str(message.id), 'conversation_id': str(conversation.id), 'message_id': str(message.id)}, ensure_ascii=False)}\n\n"

            billing_summary = billing_aggregator.summary()
            yield f"event: {BillingEventType.SUMMARY.value}\ndata:{json.dumps(billing_summary.to_sse())}\n\n"
            # 外层 aggregator 在 final() 时根据累计的 total_tokens 触发实际扣费（问题6修复）
            billing_aggregator.credit_service = self.credit_service
            billing_aggregator.account_id = account.id
            billing_final = billing_aggregator.final()
            yield f"event: {BillingEventType.FINAL.value}\ndata:{json.dumps(billing_final.to_sse())}\n\n"

            # 发送 AGENT_END 事件，让前端能识别流结束，携带真实总耗时
            _total_latency = round(time.perf_counter() - _chat_started_at, 3) if _chat_started_at else 0
            yield f"event: {QueueEvent.AGENT_END.value}\ndata:{json.dumps({'id': str(message.id), 'conversation_id': str(conversation.id), 'message_id': str(message.id), 'latency': _total_latency}, ensure_ascii=False)}\n\n"

            # 对话后写入记忆（同步降级，不影响主流程）
            answer_to_persist = final_answer or fallback_msg
            yield from self._write_memory_from_conversation(
                account, req.query.data, answer_to_persist, conversation.id
            )
        except Exception:
            logger.warning("direct_answer 真流式执行失败", exc_info=True)
            billing_cancelled = billing_aggregator.cancelled(pending_phases=["直接回答"])
            yield f"event: {BillingEventType.CANCELLED.value}\ndata:{json.dumps(billing_cancelled.to_sse())}\n\n"
            yield f"event: {QueueEvent.AGENT_MESSAGE.value}\ndata:{json.dumps({'answer': '直接回答遇到问题，请稍后重试。', 'id': str(message.id), 'conversation_id': str(conversation.id), 'message_id': str(message.id)}, ensure_ascii=False)}\n\n"
        finally:
            # 无论正常完成、异常、还是 GeneratorExit（用户关闭页面），都持久化已收集的 answer 和 latency
            answer_to_persist = final_answer or fallback_msg
            if answer_to_persist:
                try:
                    msg = self.get(Message, message.id)
                    if msg is not None:
                        _persist_latency = round(time.perf_counter() - _chat_started_at, 3) if _chat_started_at else 0
                        self.update(msg, answer=answer_to_persist, latency=_persist_latency)
                except Exception:
                    logger.warning("持久化 direct_answer 到 Message.answer 失败（finally）", exc_info=True)
            # 将 executor 收集的 AgentThought（推理链等）挂到 message 上，
            # 供外层 _persist_assistant_thoughts 持久化，避免 reload 时思考内容丢失
            if executor is not None and executor.collected_thoughts:
                try:
                    message._collected_thoughts = executor.collected_thoughts
                except Exception:
                    logger.warning("挂载 direct_answer collected_thoughts 到 message 失败（finally）", exc_info=True)

    def _stream_single_agent(
        self, req, account, conversation, message, routing_decision, llm, tools, history, should_deep_think,
        distant_summary="", user_memory_text="", invoke_from: str | None = None,
    ):
        """single_agent / deep_thinking 路径：经 ExecutionCoordinatorService 编排单 Agent。"""
        from internal.entity.billing_metering_entity import BillingEventType
        from internal.service.billing_metering_service import BillingUsageAggregator
        from internal.service.executors.single_agent_executor import SingleAgentExecutor
        from internal.entity.orchestrator_entity import ExecutionMode

        billing_aggregator = BillingUsageAggregator(task_id=str(message.id))
        billing_started = billing_aggregator.started()
        yield f"event: {BillingEventType.STARTED.value}\ndata:{json.dumps(billing_started.to_sse())}\n\n"

        collected_answer = ""
        executor = None  # 确保初始化，finally 能安全访问
        try:
            agent_class = A2ADeepThinkingAgent if should_deep_think else FunctionCallAgent
            agent_config = AgentConfig(
                user_id=account.id,
                invoke_from=invoke_from or InvokeFrom.ASSISTANT_AGENT.value,
                preset_prompt=self._build_assistant_system_prompt(),
                enable_long_term_memory=True,
                enable_deep_thinking=should_deep_think,
                runtime_flask_app=current_app._get_current_object(),
                language_model_service=self.language_model_service,
                tools=tools,
            )
            execution_mode = (
                ExecutionMode.DEEP_THINKING.value
                if should_deep_think
                else (routing_decision.get("execution_mode") if routing_decision else ExecutionMode.SINGLE_AGENT.value)
            )
            executor = SingleAgentExecutor(
                agent_class=agent_class,
                agent_config=agent_config,
                tools=tools,
                llm=llm,
                history=history or [],
                query=req.query.data,
                long_term_memory=distant_summary,
                user_memory=user_memory_text,
            )
            billing_delta_prefix = f"event: {BillingEventType.DELTA.value}"
            for chunk in executor.execute(
                query=req.query.data,
                conversation=conversation,
                message=message,
                execution_mode=execution_mode,
                routing_decision=routing_decision,
            ):
                if chunk.startswith(f"event: {QueueEvent.AGENT_MESSAGE.value}"):
                    try:
                        data_part = chunk.split("data:", 1)[1].strip()
                        payload = json.loads(data_part)
                        # 累加流式 chunk（覆盖会导致只保留最后一个 chunk）
                        chunk_answer = payload.get("answer", "")
                        if chunk_answer:
                            collected_answer = collected_answer + chunk_answer if collected_answer else chunk_answer
                    except Exception:
                        pass
                # 截获 executor 发出的 billing delta 事件，累计到外层 aggregator
                # executor 内部不再创建独立 aggregator（问题7修复），由外层统一累计
                if chunk.startswith(billing_delta_prefix):
                    try:
                        data_part = chunk.split("data:", 1)[1].strip()
                        payload = json.loads(data_part)
                        meta = payload.get("metadata") or {}
                        in_tok = int(meta.get("input_tokens", 0) or 0)
                        out_tok = int(meta.get("output_tokens", 0) or 0)
                        if in_tok or out_tok:
                            billing_aggregator.model_tokens(
                                "single_agent",
                                input_tokens=in_tok,
                                output_tokens=out_tok,
                                reason="agent_llm_invoke",
                            )
                    except Exception:
                        pass
                yield chunk

            # 外层 aggregator 在 final() 时根据累计的 total_tokens 触发实际扣费（问题6修复）
            billing_aggregator.credit_service = self.credit_service
            billing_aggregator.account_id = account.id
            billing_summary = billing_aggregator.summary()
            yield f"event: {BillingEventType.SUMMARY.value}\ndata:{json.dumps(billing_summary.to_sse())}\n\n"
            billing_final = billing_aggregator.final()
            yield f"event: {BillingEventType.FINAL.value}\ndata:{json.dumps(billing_final.to_sse())}\n\n"

            yield from self._write_memory_from_conversation(account, req.query.data, collected_answer, conversation.id)
        except Exception as e:
            logger.warning("单智能体经协调器执行失败: %s", e, exc_info=True)
            billing_cancelled = billing_aggregator.cancelled(pending_phases=["单智能体执行"])
            yield f"event: {BillingEventType.CANCELLED.value}\ndata:{json.dumps(billing_cancelled.to_sse())}\n\n"
            yield f"event: {QueueEvent.AGENT_MESSAGE.value}\ndata:{json.dumps({'answer': '单智能体执行遇到问题，请稍后重试。', 'id': str(message.id), 'conversation_id': str(conversation.id), 'message_id': str(message.id)}, ensure_ascii=False)}\n\n"
        finally:
            # 无论正常完成、异常、还是 GeneratorExit（用户关闭页面），都持久化已收集的 answer
            if collected_answer:
                try:
                    msg = self.get(Message, message.id)
                    if msg is not None:
                        self.update(msg, answer=collected_answer)
                except Exception:
                    logger.warning("持久化 single_agent answer 到 Message.answer 失败（finally）", exc_info=True)
            # 将收集到的 AgentThought 挂到 message 对象上，供外层 _persist_assistant_thoughts 使用
            # 修复 reload 丢失根因：之前传入空 {} 导致中间事件全部丢失
            if executor is not None and executor.collected_thoughts:
                try:
                    message._collected_thoughts = executor.collected_thoughts
                except Exception:
                    logger.warning("挂载 collected_thoughts 到 message 失败（finally）", exc_info=True)

    def _build_assistant_system_prompt(self) -> str:
        """组装首页助手提示词：Markdown 规范 + 启用中的系统知识库内容。"""
        preset = _get_markdown_preset_prompt()
        system_knowledge = _get_system_knowledge_context(self.db)
        if not system_knowledge:
            return preset
        return f"{preset}\n\n## 系统知识库（必须遵守）\n{system_knowledge}".strip()

    def _write_memory_from_conversation(self, account, query, ai_response, conversation_id):
        """对话后自动写入记忆，无需用户确认。降级时跳过。

        保持 generator 形式以兼容调用方的 ``yield from``。
        记忆写入涉及 LLM 调用（实体抽取/显著性评分），改为后台线程异步执行，
        避免阻塞主响应流（历史问题：同步执行时 entity_extractor 30s 超时阻塞主响应）。
        """
        try:
            from internal.config.memory_settings import settings as memory_settings

            if not memory_settings.memory_engine_enabled:
                logger.warning("记忆引擎已禁用，跳过写入")
            elif ai_response:
                from internal.service.memory.memory_write_service import MemoryWriteService

                # 捕获 Flask app 引用，供后台线程 push app context
                flask_app = current_app._get_current_object()
                account_id = account.id

                def _bg_write():
                    """后台线程：进入 app context 后执行记忆写入。"""
                    with flask_app.app_context():
                        try:
                            from app.http.app import injector
                            # 重新查询 account 对象，避免使用请求结束后变为 detached 的实例
                            account_obj = self.db.session.get(Account, account_id)
                            if account_obj is None:
                                logger.warning("记忆写入后台线程跳过: account 不存在 id=%s", account_id)
                                return
                            memory_write_service = injector.get(MemoryWriteService)
                            memory_write_service.write_from_conversation(
                                account=account_obj,
                                query=query,
                                ai_response=ai_response,
                                conversation_id=conversation_id,
                            )
                            # ── 基因1+5: 对话后即时技能涌现 + Nudge 评估（§8.5 §2.6）──
                            # 在 app context 中调用 maybe_trigger_emergence，内部异步执行
                            # 复用 memory_settings 配置，避免重复构造
                            try:
                                from internal.service.memory.post_execution_hook import PostExecutionHook
                                hook = PostExecutionHook(
                                    config=memory_settings.skill,
                                    write_config=memory_settings.write,
                                )
                                hook.maybe_trigger_emergence(
                                    user_id=str(account_id),
                                    query=query,
                                    ai_response=ai_response,
                                    conversation_id=str(conversation_id),
                                )
                            except Exception:
                                logger.warning("即时技能涌现钩子调度失败，不影响主流程", exc_info=True)
                        except Exception:
                            logger.warning("后台记忆写入失败，不影响主流程", exc_info=True)

                Thread(target=_bg_write, daemon=True).start()
        except Exception:
            logger.warning("记忆写入调度失败，不影响主流程", exc_info=True)

        # 保持 generator 兼容性，不再 yield 任何 SSE 事件
        yield from ()

    def _build_assistant_runtime_tools(self, account_id: UUID) -> list[BaseTool]:
        """构建首页助手运行时工具，包括公共 Agent、创建应用、全局 MCP 绑定和用户知识库检索。"""
        search_public_agents_tool = (
            self.public_agent_registry_service.convert_public_agent_search_to_tool()
            if self.public_agent_registry_service
            else self.faiss_service.convert_faiss_to_tool()
        )
        tools: list[BaseTool] = []
        if self.public_agent_a2a_service:
            tools.append(
                self.public_agent_a2a_service.convert_public_agent_route_to_tool(account_id)
            )
        tools.extend(
            [
                search_public_agents_tool,
                self.convert_create_app_to_tool(account_id),
            ]
        )

        if self.app_config_service is not None:
            assistant_mcp_bindings = (
                current_app.config.get("ASSISTANT_MCP_BINDINGS", [])
                if has_app_context()
                else []
            )
            if not isinstance(assistant_mcp_bindings, list):
                assistant_mcp_bindings = []
            tools.extend(
                self.app_config_service.get_langchain_tools_by_mcp_bindings(assistant_mcp_bindings)
            )

        # 添加用户知识库检索工具（确保用户上传的文档可被 Agent 检索）
        # 同时挂载系统知识库（knowledge_scope='system'，admin 通过 enabled 开关控制），
        # 让系统级知识库/可管理提示词真正对 Agent 生效
        try:
            if self.retrieval_service is not None and has_app_context():
                from internal.model import KnowledgeBase
                from sqlalchemy import or_
                kb_records = (
                    self.db.session.query(KnowledgeBase)
                    .filter(
                        KnowledgeBase.enabled.is_(True),
                        or_(
                            KnowledgeBase.owner_account_id == account_id,
                            KnowledgeBase.knowledge_scope == "system",
                        ),
                    )
                    .all()
                )
                kb_ids = [kb.id for kb in kb_records]
                if kb_ids:
                    knowledge_tool = self.retrieval_service.create_knowledge_retrieval_tool(
                        flask_app=current_app._get_current_object(),
                        knowledge_base_ids=kb_ids,
                        account_id=account_id,
                    )
                    tools.append(knowledge_tool)
        except Exception:
            logger.warning("构建用户知识库检索工具失败，不影响其他工具", exc_info=True)

        # 基因2: 添加技能详情查询工具（Progressive Disclosure Tier1/Tier2, §8.6）
        try:
            if has_app_context():
                from internal.service.memory.skill_detail_tool import (
                    create_skill_detail_tool,
                )

                tools.append(
                    create_skill_detail_tool(
                        flask_app=current_app._get_current_object(),
                        account_id=account_id,
                    )
                )
        except Exception:
            logger.warning("构建技能详情工具失败，不影响其他工具", exc_info=True)

        # 基因4: 添加 Agent 主动记忆策展工具（memory_add/replace/remove, §2.5）
        try:
            if has_app_context():
                from internal.service.memory.agent_memory_tool import (
                    create_agent_memory_tools,
                )

                tools.extend(
                    create_agent_memory_tools(
                        flask_app=current_app._get_current_object(),
                        account_id=account_id,
                    )
                )
        except Exception:
            logger.warning("构建记忆策展工具失败，不影响其他工具", exc_info=True)

        return tools

    def _mount_runtime_tools(
        self,
        *,
        prebound_tools: list[BaseTool],
        routing_decision: dict | None,
        account_id: str,
        message_id: str,
    ) -> list[BaseTool]:
        """按 PRD 架构接通工具挂载：读取 tool_subset 决策，与固有工具合并治理。

        架构链路：
        orchestrator.tool_subset.selected_tools (决策结果)
          → RuntimeToolMountService.mount_tools (合并/限制/审计)
          → MCP 工具转为 BaseTool 与固有工具合并
          → 传给 Agent
        """
        if not routing_decision:
            return prebound_tools

        tool_subset = routing_decision.get("tool_subset") or {}
        selected_candidates = tool_subset.get("selected_tools") or []
        if not selected_candidates:
            return prebound_tools

        selected_descriptors: list[RuntimeToolDescriptor] = []
        for candidate in selected_candidates:
            try:
                if not isinstance(candidate, dict):
                    continue
                source_type = str(candidate.get("source_type") or "")
                runtime_name = "{}__{}".format(
                    source_type or "tool",
                    str(candidate.get("name") or "").replace(" ", "_").lower(),
                )
                descriptor = RuntimeToolDescriptor.from_candidate(
                    candidate,
                    runtime_name=runtime_name,
                    mount_reason="orchestrator_tool_subset",
                )
                selected_descriptors.append(descriptor)
            except Exception:
                logger.warning("工具候选转 RuntimeToolDescriptor 失败", exc_info=True)

        prebound_descriptors: list[RuntimeToolDescriptor] = []
        for tool in prebound_tools:
            try:
                prebound_descriptors.append(
                    RuntimeToolDescriptor(
                        tool_id=getattr(tool, "name", ""),
                        runtime_name=getattr(tool, "name", ""),
                        name=getattr(tool, "name", ""),
                        description=getattr(tool, "description", "") or "",
                        source_type="prebound",
                        provider_id="",
                        provider_name="",
                        audit_context={"mount_reason": "prebound_assistant_tool"},
                    )
                )
            except Exception:
                logger.warning("固有工具转 RuntimeToolDescriptor 失败", exc_info=True)

        mount_service = self.runtime_tool_mount_service or RuntimeToolMountService()
        try:
            mount_result = mount_service.mount_tools(
                selected_tools=selected_descriptors,
                prebound_tools=prebound_descriptors,
                account_id=account_id,
                agent_id=str(current_app.config.get("ASSISTANT_AGENT_ID", "")),
                request_id=message_id,
                max_tool_count=20,
            )
        except Exception:
            logger.warning("RuntimeToolMountService 挂载失败，回退固有工具", exc_info=True)
            return prebound_tools

        mounted_tools = mount_result.get("mounted_tools", []) or []

        # 按来源类型分组：MCP 用 provider_id 集合加载，builtin/api 单独加载
        mcp_provider_ids = {
            d.provider_id
            for d in mounted_tools
            if d.source_type == "mcp" and d.provider_id
        }
        non_mcp_descriptors = [
            d for d in mounted_tools
            if d.source_type in (
                "api",
                "api_tool",
                "builtin",
                "builtin_tool",
                "knowledge",
                "skill",
            )
        ]

        extra_tools: list[BaseTool] = []

        # 1. 加载 MCP 工具
        if mcp_provider_ids:
            extra_tools.extend(
                self._load_mcp_tools_by_provider_ids(account_id, mcp_provider_ids)
            )

        # 2. 加载非 MCP 工具（builtin / api_tool / knowledge）
        for descriptor in non_mcp_descriptors:
            loaded = self._load_non_mcp_tool(descriptor, account_id=account_id)
            if isinstance(loaded, list):
                extra_tools.extend(loaded)
            elif loaded is not None:
                extra_tools.append(loaded)

        if not extra_tools:
            logger.info(
                "工具挂载完成: 固有%d 动态0 总计%d hidden=%d (无动态工具加载成功)",
                len(prebound_tools),
                len(prebound_tools),
                len(mount_result.get("hidden_tools", [])),
            )
            return prebound_tools

        merged: list[BaseTool] = list(prebound_tools)
        existing_names = {getattr(t, "name", "") for t in merged}
        added = 0
        for tool in extra_tools:
            tool_name = getattr(tool, "name", "")
            if tool_name and tool_name not in existing_names:
                merged.append(tool)
                existing_names.add(tool_name)
                added += 1
        logger.info(
            "工具挂载完成: 固有%d 动态%d 总计%d hidden=%d",
            len(prebound_tools),
            added,
            len(merged),
            len(mount_result.get("hidden_tools", [])),
        )
        return merged

    def _load_non_mcp_tool(self, descriptor, *, account_id: str = "") -> BaseTool | list[BaseTool] | None:
        """根据 RuntimeToolDescriptor 加载 builtin/api_tool/knowledge/skill 类型的 LangChain 工具。

        - builtin: 通过 ``builtin_provider_manager.get_tool(provider_name, tool_name)`` 加载
        - api: 查询 ApiTool 后通过 ``api_provider_manager.get_tool`` 加载
        - knowledge: 通过 ``RetrievalService.create_knowledge_retrieval_tool`` 加载
        - skill: 通过 ``SkillToolFactory`` 展开技能包工具列表
        - 其他 source_type 返回 None
        """
        if descriptor is None or self.app_config_service is None:
            return None

        source_type = (getattr(descriptor, "source_type", "") or "").lower()
        tool_id = getattr(descriptor, "tool_id", "") or ""
        runtime_name = getattr(descriptor, "runtime_name", "") or getattr(descriptor, "name", "") or ""

        try:
            if source_type in ("builtin", "builtin_tool"):
                # builtin 工具 ID 格式: "builtin:{provider_name}:{tool_name}"
                # provider_id 字段在 builtin 候选里存的就是 provider_name
                provider_name = getattr(descriptor, "provider_id", "") or getattr(descriptor, "provider_name", "") or ""
                tool_name = getattr(descriptor, "name", "") or ""
                if not provider_name or not tool_name:
                    # 回退到从 tool_id 解析
                    parts = tool_id.split(":", 2)
                    if len(parts) >= 3:
                        provider_name = provider_name or parts[1]
                        tool_name = tool_name or parts[2]
                if not provider_name or not tool_name:
                    logger.warning("builtin 工具缺少 provider_name/tool_name: %s", tool_id)
                    return None
                builtin_tool_cls = self.app_config_service.builtin_provider_manager.get_tool(
                    provider_name, tool_name
                )
                if builtin_tool_cls is None:
                    logger.warning("builtin 工具未找到: provider=%s tool=%s", provider_name, tool_name)
                    return None
                # 内置工具类实例化（无参数）
                return builtin_tool_cls()

            if source_type in ("api", "api_tool"):
                # api 工具 ID 格式: "api_tool:{api_tool_uuid}"
                entity_id = tool_id.split(":", 1)[1] if ":" in tool_id else ""
                if not entity_id:
                    logger.warning("api 工具 ID 缺少实体 ID: %s", tool_id)
                    return None
                from internal.model import ApiTool
                api_tool_record = self.db.session.query(ApiTool).filter(ApiTool.id == entity_id).first()
                if api_tool_record is None:
                    logger.warning("api 工具记录未找到: %s", entity_id)
                    return None
                from internal.core.tools.api_tools.entities import ToolEntity
                tool_entity = ToolEntity(
                    id=str(api_tool_record.id),
                    name=api_tool_record.name,
                    url=api_tool_record.url,
                    method=api_tool_record.method,
                    description=api_tool_record.description or "",
                    headers=api_tool_record.provider.headers if api_tool_record.provider else [],
                    parameters=api_tool_record.parameters or [],
                )
                return self.app_config_service.api_provider_manager.get_tool(tool_entity)

            if source_type == "skill":
                return self._load_skill_tools(descriptor, account_id=account_id)

            if source_type == "knowledge":
                # knowledge 工具 ID 格式: "knowledge:{knowledge_base_id}"
                if self.retrieval_service is None:
                    logger.warning("knowledge 工具加载失败: RetrievalService 未注入, tool_id=%s", tool_id)
                    return None
                if not has_app_context():
                    logger.warning("knowledge 工具加载失败: 缺少 Flask application context, tool_id=%s", tool_id)
                    return None
                entity_id = tool_id.split(":", 1)[1] if ":" in tool_id else ""
                if not entity_id:
                    logger.warning("knowledge 工具 ID 缺少 knowledge_base_id: %s", tool_id)
                    return None
                try:
                    kb_uuid = UUID(str(entity_id))
                except (ValueError, TypeError):
                    logger.warning("knowledge 工具 knowledge_base_id 非法: %s", entity_id)
                    return None
                try:
                    account_uuid = UUID(str(account_id)) if account_id else None
                except (ValueError, TypeError):
                    account_uuid = None
                if account_uuid is None:
                    logger.warning("knowledge 工具加载失败: 缺少 account_id, tool_id=%s", tool_id)
                    return None
                flask_app = current_app._get_current_object()
                return self.retrieval_service.create_knowledge_retrieval_tool(
                    flask_app=flask_app,
                    knowledge_base_ids=[kb_uuid],
                    account_id=account_uuid,
                )

            logger.debug("未支持的工具 source_type=%s, 跳过", source_type)
            return None
        except Exception:
            logger.warning("加载非 MCP 工具失败: %s", tool_id, exc_info=True)
            return None

    def _load_skill_tools(self, descriptor, *, account_id: str = "") -> list[BaseTool]:
        """把 skill 类型候选展开为 LangChain 工具列表。"""
        from internal.core.skills import SkillScfClient, SkillToolFactory
        from internal.model import SkillPackage, SkillPackageVersion

        provider_id = (
            getattr(descriptor, "provider_id", "")
            or getattr(descriptor, "tool_id", "").split(":", 1)[-1]
        )
        if not provider_id:
            return []
        package = (
            self.db.session.query(SkillPackage)
            .filter(
                SkillPackage.id == provider_id,
                SkillPackage.enabled.is_(True),
            )
            .first()
        )
        if package is None:
            return []
        version = (
            self.db.session.query(SkillPackageVersion)
            .filter(
                SkillPackageVersion.skill_package_id == package.id,
                SkillPackageVersion.version == package.current_version,
            )
            .first()
        )
        if version is None:
            return []
        manifest = version.manifest or {}
        package_payload = {
            "source_key": package.source_key,
            "skill_id": str(package.id),
            "name": package.name,
            "label": package.label,
            "executor_type": package.executor_type,
            "bundle": version.bundle or {},
            "version": version.version,
        }
        try:
            return SkillToolFactory(SkillScfClient()).build_tools(
                package_payload,
                manifest.get("tools") or [],
                runtime_context={"account_id": account_id},
            )
        except Exception:
            logger.warning("技能工具展开失败: source_key=%s", package.source_key, exc_info=True)
            return []

    def _load_mcp_tools_by_provider_ids(
        self, account_id, provider_ids: set[str]
    ) -> list[BaseTool]:
        """根据 MCP provider_id 集合加载对应的 LangChain 工具。"""
        try:
            from internal.model import McpProvider
            providers = (
                self.db.session.query(McpProvider)
                .filter(McpProvider.id.in_([str(pid) for pid in provider_ids]))
                .all()
            )
            mcp_bindings = []
            for provider in providers:
                mcp_bindings.append({
                    "provider_id": str(provider.id),
                    "name": provider.name,
                    "url": getattr(provider, "url", ""),
                    "transport": getattr(provider, "transport", "http"),
                    "tool_names": list(provider.tool_names or []),
                    "enabled": True,
                })
            if not mcp_bindings or self.app_config_service is None:
                return []
            return self.app_config_service.get_langchain_tools_by_mcp_bindings(mcp_bindings)
        except Exception:
            logger.warning("按 provider_id 加载 MCP 工具失败", exc_info=True)
            return []

    def _emit_progress_sse(self, conversation, message, thought: str, started_at: float = 0) -> str:
        """发送进度提示事件，让前端能看到后台正在做什么。

        使用 agent_thought 事件，前端 AgentThought 组件会展示推理过程。
        使用固定 id（message.id），前端 upsertThought 会更新同一个思考框（状态变更），
        而非创建多个独立框。
        latency 单位为秒（浮点），与 react_agent / function_call_agent / deep_thinking_agent
        等执行器保持一致，前端 normalizeMessageMetrics 期望秒。
        """
        import time as _time
        latency = round(_time.perf_counter() - started_at, 3) if started_at else 0
        payload = {
            "id": str(message.id),
            "event": QueueEvent.AGENT_THOUGHT.value,
            "thought": thought,
            "observation": "",
            "tool": "",
            "tool_input": {},
            "answer": "",
            "conversation_id": str(conversation.id),
            "message_id": str(message.id),
            "latency": latency,
            "total_token_count": 0,
        }
        return f"event: {QueueEvent.AGENT_THOUGHT.value}\ndata:{json.dumps(payload, ensure_ascii=False)}\n\n"

    def chat(self, req: AssistantAgentChat, account: Account, invoke_from: str | None = None) -> Generator:
        """传递query与账号实现与辅助Agent进行会话

        Args:
            invoke_from: 调用来源标识（如定时任务传 InvokeFrom.SCHEDULE.value），
                用于消息/会话与正常对话作区分；不传默认 assistant_agent。
        """
        # 1.获取辅助Agent对应的id
        assistant_agent_id = current_app.config.get("ASSISTANT_AGENT_ID")

        # 2.获取当前会话信息（支持按conversation_id切换）
        conversation = self._resolve_assistant_agent_conversation(
            account=account,
            conversation_id=self._resolve_conversation_id(req.conversation_id.data),
            sync_active=True,
            allowed_invoke_from=invoke_from,
        )

        # 3.在落库前解析运行时模型能力，避免带图请求被静默降级
        if self.language_model_service is not None:
            model_resolution = self.language_model_service.resolve_runtime_language_model(
                self.language_model_service.get_assistant_agent_model_config(),
                image_urls=req.image_urls.data,
                entrypoint=LanguageModelService.ENTRYPOINT_ASSISTANT_AGENT,
                tier="3",
            )
            llm = model_resolution.llm
        else:
            # 兜底：language_model_service 未注入时走类方法获取默认模型
            model_resolution = None
            llm = LanguageModelService.get_chat_model_by_tier("3")
        resolved_model_name = ""
        if model_resolution is not None:
            effective_model_config = getattr(model_resolution, "effective_model_config", None) or {}
            resolved_model_name = str(effective_model_config.get("model", "") or "").strip()

        # 4.新建一条消息记录
        import time as _time
        _chat_started_at = _time.perf_counter()
        message = self.create(
            Message,
            app_id=assistant_agent_id,
            conversation_id=conversation.id,
            invoke_from=invoke_from or InvokeFrom.ASSISTANT_AGENT.value,
            created_by=account.id,
            query=req.query.data,
            image_urls=req.image_urls.data,
            status=MessageStatus.NORMAL.value,
        )

        # 注册 CancelToken：SSE 客户端断开时（GeneratorExit）由 finally 块取消，
        # 终止后台 agent 线程避免空烧 token。云端执行功能将走独立 Celery 通道，不受影响。
        cancel_token = CancelToken()
        self.register_cancel_token(message.id, cancel_token)

        routing_decision = None
        # 指挥官模式：ENABLE_CONDUCTOR 开关启用时，由 LLM 指挥官替代规则编排
        use_conductor = (
            self.conductor_service is not None
            and self.orchestration_feature_flag_service is not None
            and self.orchestration_feature_flag_service.is_enabled("ENABLE_CONDUCTOR")
        )
        if use_conductor:
            try:
                conductor_plan = self.conductor_service.plan(
                    req.query.data,
                    image_url_count=len(req.image_urls.data or []),
                )
                routing_decision = self.conductor_service.to_routing_decision_dict(conductor_plan)
                logger.info(
                    "指挥官决策 intent=%s mode=%s complexity=%s agents=%d",
                    conductor_plan.intent,
                    conductor_plan.execution_mode,
                    conductor_plan.complexity,
                    len(conductor_plan.agents),
                )
            except Exception as exc:
                logger.warning("指挥官决策失败，直接走 direct_answer 路径: %s", exc)
                # 直接走 direct_answer，跳过 orchestrator（避免又调一次 LLM 烧 token）
                routing_decision = {
                    "intent": "fallback",
                    "execution_mode": "direct_answer",
                    "complexity": "simple",
                    "needs_tools": False,
                    "needs_agent": False,
                    "risk_level": "safe",
                    "cost_policy": {"allowed": True},
                }

        if routing_decision is None and self.orchestrator_service is not None:
            try:
                decision_result = self.orchestrator_service.decide(
                    req.query.data,
                    account_id=account.id,
                    conversation_id=conversation.id,
                    message_id=message.id,
                    image_urls=req.image_urls.data,
                    enable_deep_thinking=bool(req.confirm_deep_thinking.data),
                    invoke_from=invoke_from or InvokeFrom.ASSISTANT_AGENT.value,
                )
                routing_log_id = getattr(decision_result, "routing_log_id", None)
                routing_decision = decision_result.to_dict()
                if routing_log_id:
                    routing_decision["routing_log_id"] = str(routing_log_id)
            except Exception as exc:
                logger.warning("辅助 Agent 调度决策失败，继续原流程: %s", exc)

        if routing_decision is not None:
            logger.info(
                "辅助 Agent 路由决策 intent=%s execution_mode=%s complexity=%s model_tier=%s risk=%s",
                routing_decision.get("intent"),
                routing_decision.get("execution_mode"),
                routing_decision.get("complexity"),
                routing_decision.get("recommended_model_tier"),
                routing_decision.get("risk_level"),
            )
            # 发送指挥官决策内容到思考框（固定 id，前端更新同一个框）
            mode_label = {
                "direct_answer": "直接回答",
                "single_agent": "单智能体执行",
                "single_agent_with_tools": "调用工具执行",
                "deep_thinking": "深度思考",
                "multi_agent": "多智能体协作",
                "multi_agent_parallel": "多智能体并行",
            }.get(routing_decision.get("execution_mode", ""), routing_decision.get("execution_mode", ""))
            decision_thought = (
                f"指挥官决策\n"
                f"执行模式：{mode_label}\n"
                f"意图：{routing_decision.get('intent', '')}\n"
                f"复杂度：{routing_decision.get('complexity', '')}\n"
                f"原因：{routing_decision.get('reason', '')}"
            )
            yield self._emit_progress_sse(
                conversation, message, decision_thought, _chat_started_at,
            )

        # 记忆基座重复任务检测：同应用相似需求高频出现时建议创建定时任务
        try:
            from internal.service.task_dedup_service import TaskDedupService
            suggestion = TaskDedupService().check_suggestion(
                account.id, assistant_agent_id, req.query.data, conversation.id,
            )
            if suggestion:
                yield "event: schedule_suggestion\ndata:" + json.dumps(suggestion) + "\n\n"
        except Exception as dedup_exc:
            logger.debug("定时任务建议检测跳过: %s", dedup_exc)

        # 5.构建三层混合上下文（近期原文层/远期摘要层/关键事实层）
        # 记忆检索不发送 progress thought，直接融入到 Agent 上下文
        token_buffer_memory = TokenBufferMemory(
            db=self.db,
            conversation=conversation,
            model_instance=llm,
            language_model_service=self.language_model_service,
        )
        context = token_buffer_memory.build_context(conversation.id, req.query.data, account)
        history = context["recent_messages"]
        distant_summary = context.get("distant_summary", "")

        # 6.构建首页助手运行时工具
        prebound_tools = self._build_assistant_runtime_tools(account.id)

        # 6.0 工具池治理挂载：读取 orchestrator 决策的 tool_subset，与固有工具合并
        tools = self._mount_runtime_tools(
            prebound_tools=prebound_tools,
            routing_decision=routing_decision,
            account_id=str(account.id),
            message_id=str(message.id),
        )

        # 7.构建辅助Agent专用智能体。根据路由决策的 execution_mode 选择执行路径：
        # 二阶段流程：confirm_deep_thinking=True 表示用户已确认，直接执行深度思考；
        # 否则阶段1判定，若需要深度思考则返回 deep_thinking_proposal 事件等待用户确认。
        execution_mode = routing_decision.get("execution_mode") if routing_decision else None
        is_confirm_phase = bool(req.confirm_deep_thinking.data)

        if not is_confirm_phase and routing_decision is not None:
            if not routing_decision.get("cost_policy", {}).get("allowed", True):
                yield from self._stream_insufficient_balance()
                # 补上 AGENT_END 事件和持久化，避免孤儿 Message
                yield f"event: {QueueEvent.AGENT_END.value}\ndata:{json.dumps({'id': str(message.id), 'conversation_id': str(conversation.id), 'message_id': str(message.id)}, ensure_ascii=False)}\n\n"
                self._persist_assistant_thoughts(
                    account, assistant_agent_id, conversation, message, {}, routing_decision,
                    _chat_started_at, resolved_model_name=resolved_model_name,
                )
                return
            if execution_mode == "deep_thinking":
                yield from self._stream_deep_thinking_proposal(routing_decision)
                # 补上 AGENT_END 事件和持久化，避免孤儿 Message
                yield f"event: {QueueEvent.AGENT_END.value}\ndata:{json.dumps({'id': str(message.id), 'conversation_id': str(conversation.id), 'message_id': str(message.id)}, ensure_ascii=False)}\n\n"
                self._persist_assistant_thoughts(
                    account, assistant_agent_id, conversation, message, {}, routing_decision,
                    _chat_started_at, resolved_model_name=resolved_model_name,
                )
                return
            if execution_mode == "direct_answer":
                yield from self._stream_direct_answer(req, account, conversation, message, routing_decision, _chat_started_at, llm=llm, tools=tools)
                # 与 single_agent 分支一致：从 message._collected_thoughts 读取流式期间
                # 收集的 AgentThought（推理链/工具调用等），避免 reload 时思考内容丢失
                collected_thoughts = getattr(message, '_collected_thoughts', None) or []
                # 推理链已包含完整思考过程（thought=reasoning_content），
                # 不再额外持久化 routing_decision 占位 thought，避免出现重复思考卡片
                if isinstance(routing_decision, dict):
                    message.routing_log_id = routing_decision.get("routing_log_id")
                    message.routing_decision = routing_decision
                self._persist_assistant_thoughts(
                    account, assistant_agent_id, conversation, message,
                    collected_thoughts, None, _chat_started_at,
                    resolved_model_name=resolved_model_name,
                )
                return
            if execution_mode in ("multi_agent", "multi_agent_parallel", "multi_agent_sequential"):
                # MultiAgent 执行路径已下线（_stream_multi_agent 方法已删除），
                # 指挥官应输出 single_agent/direct_answer，此处仅作防御性降级。
                logger.warning(
                    "MultiAgent 执行路径已下线，降级为 single_agent: execution_mode=%s",
                    execution_mode,
                )
                routing_decision = {**routing_decision, "execution_mode": "single_agent"}
                try:
                    yield from self._stream_single_agent(
                        req, account, conversation, message, routing_decision, llm, tools, history, False,
                        distant_summary=distant_summary,
                        invoke_from=invoke_from,
                    )
                finally:
                    self._terminate_agent_if_running(message.id, account.id)
                    self._persist_assistant_thoughts(
                        account, assistant_agent_id, conversation, message, {}, routing_decision,
                        _chat_started_at, resolved_model_name=resolved_model_name,
                    )
                return

        should_deep_think = is_confirm_phase or execution_mode == "deep_thinking"

        # 统一执行入口：single_agent / single_agent_with_tools / deep_thinking(已确认) /
        # reject_or_confirm / 路由决策缺失，全部经 ExecutionCoordinatorService 编排。
        if routing_decision is None:
            logger.warning("辅助 Agent 路由决策缺失，回退到默认单智能体执行路径")
            routing_decision = {
                "intent": "unknown",
                "execution_mode": "single_agent",
                "complexity": "unknown",
                "needs_tools": bool(tools),
                "needs_agent": True,
                "needs_multi_agent": False,
                "recommended_model_tier": "2",
                "risk_level": "safe",
                "reason": "路由决策缺失，回退到默认单智能体执行",
            }
            execution_mode = "single_agent"

        if execution_mode == "reject_or_confirm":
            logger.warning(
                "辅助 Agent 路由决策标记高风险任务，建议二次确认: intent=%s",
                routing_decision.get("intent"),
            )

        try:
            yield from self._stream_single_agent(
                req, account, conversation, message, routing_decision, llm, tools, history, should_deep_think,
                distant_summary=distant_summary,
                invoke_from=invoke_from,
            )
        finally:
            # 客户端断开（GeneratorExit）或正常结束时终止后台 agent 线程，避免空烧 token
            # 正常结束时无害（任务已完成）；云端执行走独立 Celery 通道不受影响
            self._terminate_agent_if_running(message.id, account.id)
            # 无论 Agent 流正常完成还是异常终止，都尝试落库
            # _persist_assistant_thoughts 内部已有 try/except，不会抛异常出去
            # 修复 reload 丢失：从 message._collected_thoughts 读取流式期间收集的 AgentThought
            collected_thoughts = getattr(message, '_collected_thoughts', None) or []
            self._persist_assistant_thoughts(
                account, assistant_agent_id, conversation, message,
                collected_thoughts, routing_decision, _chat_started_at,
                resolved_model_name=resolved_model_name,
            )
        return

    def _persist_assistant_thoughts(
        self, account, assistant_agent_id, conversation, message, agent_thoughts,
        routing_decision, _chat_started_at: float = 0, resolved_model_name: str = "",
    ):
        """持久化消息与推理过程到数据库。"""
        try:
            # 若 agent_thoughts 为空，从 Message 表读取已持久化的 answer 构造伪 thought，
            # 让 save_agent_thoughts 能更新 Message 状态并触发计费
            if not agent_thoughts:
                msg = self.get(Message, message.id)
                if msg and msg.answer:
                    from internal.core.agent.entities.queue_entity import AgentThought
                    import time as _time
                    _persist_latency = round(_time.perf_counter() - _chat_started_at, 3) if _chat_started_at else float(msg.latency or 0)
                    agent_thoughts = [
                        AgentThought(
                            id=message.id,
                            task_id=message.id,
                            event=QueueEvent.AGENT_MESSAGE,
                            thought="assistant_agent",
                            observation=msg.answer,
                            answer=msg.answer,
                            latency=_persist_latency,
                            total_token_count=0,
                        )
                    ]
            else:
                # 将 dict 形式的 agent_thoughts 转为 AgentThought 对象
                from internal.core.agent.entities.queue_entity import AgentThought
                raw_list = list(agent_thoughts.values()) if isinstance(agent_thoughts, dict) else (agent_thoughts or [])
                normalized = []
                for item in raw_list:
                    if isinstance(item, AgentThought):
                        normalized.append(item)
                    elif isinstance(item, dict):
                        event_val = item.get("event", QueueEvent.AGENT_MESSAGE.value)
                        # 字符串事件值转为 QueueEvent 枚举
                        if isinstance(event_val, str):
                            try:
                                event_val = QueueEvent(event_val)
                            except ValueError:
                                event_val = QueueEvent.AGENT_MESSAGE
                        normalized.append(AgentThought(
                            id=item.get("id", message.id),
                            task_id=item.get("task_id", message.id),
                            event=event_val,
                            thought=item.get("thought", ""),
                            observation=item.get("observation", ""),
                            answer=item.get("answer", ""),
                            latency=item.get("latency", 0),
                            total_token_count=item.get("total_token_count", 0),
                            tool=item.get("tool", ""),
                            tool_input=item.get("tool_input", {}),
                        ))
                agent_thoughts = normalized
            self.conversation_service.save_agent_thoughts(
                account_id=account.id,
                app_id=assistant_agent_id,
                app_config={
                    "long_term_memory": {"enable": True},
                },
                conversation_id=conversation.id,
                message_id=message.id,
                agent_thoughts=agent_thoughts,
                routing_decision=routing_decision,
            )
            # save_agent_thoughts 可能用 usage_summary.latency=0 覆盖 conductor 路径已设置的 latency，
            # 这里重新确保 Message.latency 为真实总耗时
            if _chat_started_at:
                try:
                    import time as _time
                    msg = self.get(Message, message.id)
                    if msg is not None:
                        correct_latency = round(_time.perf_counter() - _chat_started_at, 3)
                        if correct_latency > float(msg.latency or 0):
                            self.update(msg, latency=correct_latency)
                except Exception:
                    pass
            self._update_routing_log_execution(
                message, routing_decision, agent_thoughts, _chat_started_at,
                resolved_model_name=resolved_model_name,
            )
        except Exception:
            logger.warning("持久化推理过程失败", exc_info=True)

    def _update_routing_log_execution(
        self,
        message,
        routing_decision,
        agent_thoughts,
        started_at: float = 0,
        resolved_model_name: str = "",
    ) -> None:
        """把消息执行结果写回路由日志，让管理端能看到真实执行状态与工具调用。"""
        routing_log_id = (
            (routing_decision or {}).get("routing_log_id")
            or getattr(message, "routing_log_id", None)
        )
        if not routing_log_id:
            return
        try:
            import time as _time

            from internal.service.routing_log_service import RoutingLogService

            log_service = self.routing_log_service or RoutingLogService(db=self.db)
            msg = self.get(Message, message.id)
            tool_names: list[str] = []
            agent_names: list[str] = []
            thought_list = (
                list(agent_thoughts.values())
                if isinstance(agent_thoughts, dict)
                else (agent_thoughts or [])
            )
            for thought in thought_list:
                if isinstance(thought, dict):
                    tool = thought.get("tool") or ""
                    agent = thought.get("agent") or thought.get("task_id") or ""
                else:
                    tool = getattr(thought, "tool", "") or ""
                    agent = getattr(thought, "task_id", "") or ""
                if tool and tool not in tool_names:
                    tool_names.append(str(tool))
                agent_key = str(agent) if agent else ""
                if agent_key and agent_key not in agent_names:
                    agent_names.append(agent_key)

            base_decision = getattr(message, "routing_decision", None) or routing_decision or {}
            decision = dict(base_decision)
            decision["execution_status"] = "completed"
            decision["answer_length"] = len((msg.answer or "") if msg else "")
            decision["tool_calls"] = tool_names
            decision["agent_executed"] = agent_names or decision.get("agent_subset", {}).get(
                "selected_agents", []
            )

            latency_ms = (
                int((_time.perf_counter() - started_at) * 1000)
                if started_at
                else int(float((msg.latency if msg else 0) or 0) * 1000)
            )
            cost_summary = {
                "estimated_credits": float((msg.total_token_count if msg else 0) or 0),
                "total_tokens": int((msg.total_token_count if msg else 0) or 0),
                "answer_token_count": int((msg.answer_token_count if msg else 0) or 0),
                "message_token_count": int((msg.message_token_count if msg else 0) or 0),
                "total_price": float((msg.total_price if msg else 0) or 0),
            }
            model_selection = {
                "model_tier": decision.get("recommended_model_tier", ""),
                "model_id": resolved_model_name,
                "model_display_name": resolved_model_name,
                "cost_policy_allowed": bool(
                    (decision.get("cost_policy") or {}).get("allowed", True)
                ),
                "cost_policy": decision.get("cost_policy") or {},
                "execution_model": resolved_model_name or decision.get("recommended_model_tier", ""),
                "execution_ok": bool(
                    msg is not None and msg.status != MessageStatus.STOP.value
                ),
            }
            tool_subset = decision.get("tool_subset") or {}
            selected_tools = tool_subset.get("selected_tools") or []
            tool_pool_hits = (
                selected_tools
                if selected_tools and isinstance(selected_tools[0], dict)
                else [{"name": name} for name in tool_names]
            )
            agent_subset = decision.get("agent_subset") or {}
            selected_agents = agent_subset.get("selected_agents") or []
            agent_pool_hits = (
                selected_agents
                if selected_agents and isinstance(selected_agents[0], dict)
                else [{"name": name} for name in agent_names]
            )
            log_service.finalize(
                routing_log_id,
                routing_decision=decision,
                status="success" if msg is not None and msg.status != MessageStatus.STOP.value else "success",
                latency_ms=latency_ms,
                cost_summary=cost_summary,
                model_selection=model_selection,
                tool_pool_hits=tool_pool_hits,
                agent_pool_hits=agent_pool_hits,
            )
        except Exception:
            logger.warning("更新路由日志执行结果失败", exc_info=True)

    def generate_introduction(self, account: Account) -> Generator[str, None, None]:
        """流式生成首页辅助Agent个性化介绍（支持缓存优化）"""
        # 1.按账号全局查询最近5条有效对话消息（覆盖辅助Agent和其他Agent）
        latest_messages = (
            self.db.session.query(Message)
            .filter(
                Message.created_by == account.id,
                Message.status.in_(
                    [MessageStatus.STOP.value, MessageStatus.NORMAL.value]
                ),
                Message.query != "",
                Message.answer != "",
                ~Message.is_deleted,
            )
            .order_by(desc(Message.created_at))
            .limit(5)
            .all()
        )
        suggested_questions_message_id = (
            str(latest_messages[0].id) if len(latest_messages) > 0 else ""
        )

        # 2.查询账号维度最近会话摘要，增强跨会话语义理解
        summary_rows = (
            self.db.session.query(Conversation.summary)
            .filter(
                Conversation.created_by == account.id,
                Conversation.summary != "",
                ~Conversation.is_deleted,
            )
            .order_by(desc(Conversation.updated_at))
            .limit(3)
            .all()
        )
        summary_parts = [
            row[0].strip() for row in summary_rows if row and row[0] and row[0].strip()
        ]
        summary = "\n\n".join(summary_parts).strip()
        display_name = (account.name or "").strip() or "朋友"

        # 3.判断是否首次使用（无历史消息且无历史摘要）
        if len(latest_messages) == 0 and summary == "":
            data = {
                "content": "",
                "is_first_time": True,
                "message_id": "",
                "suggested_questions_message_id": "",
            }
            yield f"event: intro_done\ndata:{json.dumps(data, ensure_ascii=False, default=str)}\n\n"
            return

        # 4.生成消息指纹并尝试从缓存获取
        message_ids = [str(msg.id) for msg in latest_messages]
        fingerprint = self._generate_message_fingerprint(message_ids, summary)
        cached_data = self._get_cached_introduction(account.id, fingerprint)

        # 5.如果缓存命中，直接返回缓存内容（模拟流式输出）
        if cached_data:
            logger.info(
                f"辅助Agent介绍命中缓存，账号ID: {account.id}, 指纹: {fingerprint}"
            )
            # 模拟流式输出缓存内容，提升用户体验
            cached_introduction = cached_data.get("introduction", "")
            chunk_size = 20  # 每次输出20个字符
            for i in range(0, len(cached_introduction), chunk_size):
                chunk = cached_introduction[i : i + chunk_size]
                data = {"content": chunk}
                yield f"event: intro_chunk\ndata:{json.dumps(data, ensure_ascii=False, default=str)}\n\n"

            # 输出完成事件
            done_data = {
                "content": cached_introduction,
                "is_first_time": False,
                "message_id": cached_data.get("suggested_questions_message_id", ""),
                "suggested_questions_message_id": cached_data.get(
                    "suggested_questions_message_id", ""
                ),
            }
            yield f"event: intro_done\ndata:{json.dumps(done_data)}\n\n"
            return

        # 6.缓存未命中，调用LLM生成新内容
        logger.info(
            f"辅助Agent介绍缓存未命中，调用LLM生成，账号ID: {account.id}, 指纹: {fingerprint}"
        )

        # 7.准备 LLM 并构建提示消息（走数据库配置 + compatible_api 分发）
        llm = LanguageModelService.get_feature_model("assistant_agent_intro")

        prompt_messages = self._build_introduction_prompt_messages(
            account=account,
            summary=summary,
            messages=list(reversed(latest_messages)),
        )

        # 8.对提示消息做截断，防止上下文过长导致高耗时与高消耗
        max_token_limit = 1800
        try:
            prompt_messages = trim_messages(
                messages=prompt_messages,
                max_tokens=max_token_limit,
                token_counter=llm,
                strategy="last",
                start_on="human",
                end_on="human",
            )
        except Exception:
            logger.exception(
                "辅助Agent介绍提示词trim_messages失败，将退化为原始消息继续生成"
            )

        # 9.流式生成并持续返回前端（用活跃探针替代固定超时）
        from internal.service.memory.llm_activity_probe import (
            LLMActivityProbe,
            LLMActivityTimeoutError,
        )

        introduction = ""
        chunks = []
        try:
            for chunk in LLMActivityProbe.stream_messages_with_probe(
                llm, prompt_messages, feature_key="assistant_agent_intro"
            ):
                chunks.append(chunk)
                chunk_content = self._extract_chunk_content(
                    chunk.content if hasattr(chunk, "content") else chunk
                )
                if not chunk_content:
                    continue

                introduction += chunk_content
                data = {"content": chunk_content}
                yield f"event: intro_chunk\ndata:{json.dumps(data, ensure_ascii=False, default=str)}\n\n"
        except LLMActivityTimeoutError:
            logger.warning("辅助Agent介绍生成被探针终止（模型无响应）")
            error_data = {"observation": "个性化介绍生成超时，请稍后重试"}
            yield f"event: error\ndata:{json.dumps(error_data)}\n\n"
            return
        except Exception:
            logger.exception("辅助Agent介绍流式生成失败")
            error_data = {"observation": "个性化介绍生成失败，请稍后重试"}
            yield f"event: error\ndata:{json.dumps(error_data)}\n\n"
            return

        # 9.1 公共 AI 功能计费（流式调用，从 chunk 列表提取 token usage）
        token_usage = extract_token_usage_from_stream(chunks)
        if token_usage:
            charge_for_feature(
                self.credit_service,
                account.id,
                "assistant_agent_intro",
                token_usage["total_tokens"],
            )

        # 10.输出完成事件
        formatted_introduction = self._ensure_introduction_markdown(
            introduction=introduction.strip(),
            display_name=display_name,
        )
        done_data = {
            "content": formatted_introduction,
            "is_first_time": False,
            "message_id": suggested_questions_message_id,
            "suggested_questions_message_id": suggested_questions_message_id,
        }
        yield f"event: intro_done\ndata:{json.dumps(done_data)}\n\n"

        # 11.将生成的内容缓存到Redis（TTL: 1小时）
        cache_data = {
            "introduction": formatted_introduction,
            "suggested_questions_message_id": suggested_questions_message_id,
            "generated_at": datetime.now(UTC).isoformat(),
        }
        self._set_cached_introduction(account.id, fingerprint, cache_data, ttl=3600)

    @classmethod
    def stop_chat(cls, task_id: UUID, account: Account) -> None:
        """根据传递的任务id+账号停止某次响应会话"""
        AgentQueueManager.set_stop_flag(
            task_id, InvokeFrom.ASSISTANT_AGENT.value, account.id
        )
        cls._cancel_active_token(task_id)

    @classmethod
    def register_cancel_token(cls, task_id: UUID, token: CancelToken) -> CancelToken:
        cls._active_cancel_tokens[str(task_id)] = token
        return token

    @classmethod
    def _cancel_active_token(cls, task_id: UUID) -> None:
        token = cls._active_cancel_tokens.pop(str(task_id), None)
        if token is not None:
            token.cancel()

    def _terminate_agent_if_running(self, message_id: UUID, account_id: UUID) -> None:
        """SSE 客户端断开或正常结束时终止后台 agent 线程。

        双信号终止：
        1. AgentQueueManager.set_stop_flag：设置 Redis flag，让 agent 的 queue listen
           循环检测到 STOP 事件退出（覆盖 single_agent/deep_thinking 路径）
        2. _cancel_active_token：取消 CancelToken，让检测 token 的执行器退出

        正常结束时这些操作无害（任务已完成，stop flag 仅写入 Redis 缓存，过期自动清理）。
        云端执行功能将走独立 Celery 通道，不经过此方法，不受影响。
        """
        try:
            AgentQueueManager.set_stop_flag(
                message_id,
                InvokeFrom.ASSISTANT_AGENT.value,
                account_id,
            )
        except Exception:
            logger.warning(
                "设置 agent stop flag 失败: message_id=%s", message_id, exc_info=True
            )
        self._cancel_active_token(message_id)

    def get_conversation_messages_with_page(
        self, req: GetAssistantAgentMessagesWithPageReq, account: Account
    ) -> tuple[list[Message], Paginator]:
        """根据传递的请求+账号获取与辅助Agent对话的消息分页列表"""
        # 1.获取会话信息（支持按conversation_id切换）
        conversation = self._resolve_assistant_agent_conversation(
            account=account,
            conversation_id=self._resolve_conversation_id(req.conversation_id.data),
            sync_active=False,
        )

        # 2. 构建分页器并构建过滤条件
        paginator = Paginator(db=self.db, req=req)
        filters = [
            Message.conversation_id == conversation.id,
            Message.status.in_([MessageStatus.STOP.value, MessageStatus.NORMAL.value]),
            Message.query
            != "",  # 只过滤用户提问不为空的消息，允许答案为空（正在生成中）
            ~Message.is_deleted,
        ]

        if req.created_at.data:
            # 3. 将时间戳转换成 DateTime
            created_at_datetime = datetime.fromtimestamp(req.created_at.data, UTC)
            filters.append(Message.created_at <= created_at_datetime)

        # 4. 分页查询 ID 列表
        paginated_ids = paginator.paginate(
            self.db.session.query(Message.id)
            .filter(*filters)
            .order_by(desc(Message.created_at), desc(Message.id))
        )

        # 5. 加载完整的消息及其关联数据，避免 N+1 查询
        if not paginated_ids:
            return [], paginator

        # Extract IDs from paginated_ids (handle Row objects from SQLAlchemy)
        id_list = []
        for item in paginated_ids:
            # Row objects can be indexed like tuples
            if hasattr(item, "__getitem__"):
                id_list.append(item[0])
            else:
                id_list.append(item)

        messages = (
            self.db.session.query(Message)
            .options(selectinload(Message.agent_thoughts))
            .filter(Message.id.in_(id_list))
            .order_by(desc(Message.created_at), desc(Message.id))
            .all()
        )

        account_id = getattr(account, "id", None)
        if account_id is not None:
            self._schedule_introduction_prewarm(account_id)

        return messages, paginator

    def get_conversations(
        self,
        req: GetAssistantAgentConversationsReq,
        account: Account,
    ) -> list[dict]:
        """获取当前账号的辅助Agent最近会话列表"""
        assistant_agent_id = current_app.config.get("ASSISTANT_AGENT_ID")
        limit = req.limit.data or 20
        active_conversation_id = account.assistant_agent_conversation_id

        has_valid_message = (
            self.db.session.query(Message.id)
            .filter(
                and_(
                    Message.conversation_id == Conversation.id,
                    Message.status.in_(
                        [MessageStatus.STOP.value, MessageStatus.NORMAL.value]
                    ),
                    Message.query != "",  # 只过滤用户提问不为空的消息
                    ~Message.is_deleted,
                )
            )
            .exists()
        )

        conversations = (
            self.db.session.query(Conversation)
            .filter(
                Conversation.app_id == assistant_agent_id,
                Conversation.created_by == account.id,
                Conversation.invoke_from == InvokeFrom.ASSISTANT_AGENT.value,
                ~Conversation.is_deleted,
                has_valid_message,
            )
            .order_by(desc(Conversation.updated_at))
            .limit(limit)
            .all()
        )

        result = [
            {
                "id": conversation.id,
                "name": conversation.name,
                "is_active": conversation.id == active_conversation_id,
                "updated_at": datetime_to_timestamp(conversation.updated_at),
                "created_at": datetime_to_timestamp(conversation.created_at),
            }
            for conversation in conversations
        ]
        account_id = getattr(account, "id", None)
        if account_id is not None:
            self._schedule_introduction_prewarm(account_id)
        return result


    def delete_conversation(self, account: Account) -> None:
        """根据传递的账号，清空辅助Agent智能体会话消息列表"""
        # 清空会话时同时清除缓存
        self._clear_introduction_cache(account.id)
        # account 可能来自其他线程的 scoped session，直接 update 会触发
        # “already attached to session” 错误；在当前线程重新加载后再更新。
        try:
            from internal.model import Account
            fresh_account = self.db.session.query(Account).get(account.id)
            if fresh_account is not None:
                self.update(fresh_account, assistant_agent_conversation_id=None)
                return
        except Exception:
            logger.warning(
                "清空辅助Agent会话时重新加载账号失败，回退直接置空 account 字段",
                exc_info=True,
            )
        try:
            account.assistant_agent_conversation_id = None
            with self.db.auto_commit():
                self.db.session.add(account)
        except Exception:
            logger.warning(
                "清空辅助Agent会话时更新账号失败（忽略，不影响删除逻辑）",
                exc_info=True,
            )

    def _generate_introduction_cache_key(
        self, account_id: UUID, fingerprint: str
    ) -> str:
        """生成介绍内容的缓存键"""
        return f"assistant_agent:introduction:{account_id}:{fingerprint}"

    def _generate_message_fingerprint(
        self, message_ids: list[str], summary: str
    ) -> str:
        """生成消息指纹，用于检测内容是否变化"""
        # 将消息ID列表和摘要内容组合后生成MD5哈希
        content = f"{','.join(message_ids)}:{summary}"
        return hashlib.md5(content.encode("utf-8")).hexdigest()

    def _get_cached_introduction(
        self, account_id: UUID, fingerprint: str
    ) -> dict | None:
        """从Redis获取缓存的介绍内容"""
        cache_key = self._generate_introduction_cache_key(account_id, fingerprint)
        try:
            cached_data = self.redis_client.get(cache_key)
            if cached_data:
                return json.loads(cached_data)
        except Exception:
            logger.exception("获取辅助Agent介绍缓存失败")
        return None

    def _set_cached_introduction(
        self, account_id: UUID, fingerprint: str, data: dict, ttl: int = 3600
    ) -> None:
        """将介绍内容缓存到Redis"""
        cache_key = self._generate_introduction_cache_key(account_id, fingerprint)
        try:
            self.redis_client.setex(
                cache_key,
                ttl,
                json.dumps(data, ensure_ascii=False),
            )
        except Exception:
            logger.exception("设置辅助Agent介绍缓存失败")

    def _clear_introduction_cache(self, account_id: UUID) -> None:
        """清除指定账号的所有介绍缓存"""
        try:
            # 使用模式匹配删除该账号的所有缓存
            pattern = f"assistant_agent:introduction:{account_id}:*"
            cursor = 0
            while True:
                cursor, keys = self.redis_client.scan(
                    cursor=cursor, match=pattern, count=100
                )
                if keys:
                    self.redis_client.delete(*keys)
                if cursor == 0:
                    break
        except Exception:
            logger.exception("清除辅助Agent介绍缓存失败")

    @classmethod
    def _build_introduction_prompt_messages(
        cls,
        account: Account,
        summary: str,
        messages: list[Message],
    ) -> list:
        """构建个性化介绍提示消息列表"""
        user_name = (account.name or "").strip()
        display_name = user_name if user_name else "朋友"
        # 开场介绍人设从系统提示词库读取（可管理，YAML 兜底），避免硬编码在代码中
        from internal.service.system_prompt_library_service import SystemPromptLibraryService
        intro_template = SystemPromptLibraryService().get_prompt_or_default("assistant_agent_introduction")
        prompt_messages = [SystemMessage(content=intro_template.format(display_name=display_name))]

        # 把会话摘要作为人类消息注入，避免把 AI 回复混入介绍生成上下文
        if summary:
            prompt_messages.extend(
                [
                    HumanMessage(content=f"用户历史会话摘要如下：\n{summary}"),
                ]
            )

        # 最近消息作为上下文输入
        for item in messages:
            query = (item.query or "").strip()
            if query:
                prompt_messages.append(HumanMessage(content=query))

        return prompt_messages

    @classmethod
    def _extract_chunk_content(cls, chunk_content: object) -> str:
        """统一解析DeepSeek流式chunk内容，兼容字符串与分块结构"""
        if chunk_content is None:
            return ""

        if isinstance(chunk_content, str):
            return chunk_content

        if isinstance(chunk_content, dict):
            return str(chunk_content.get("text", ""))

        if isinstance(chunk_content, list):
            texts = []
            for item in chunk_content:
                if isinstance(item, str):
                    texts.append(item)
                elif isinstance(item, dict):
                    texts.append(str(item.get("text", "")))
                else:
                    texts.append(str(item))
            return "".join(texts)

        return str(chunk_content)

    @classmethod
    def _contains_markdown_syntax(cls, content: str) -> bool:
        """检测内容是否已经包含明显Markdown结构"""
        if "```" in content:
            return True

        markdown_pattern = re.compile(r"(^|\n)\s*(#{1,6}\s|[-*+]\s|\d+\.\s|>\s|\|.+\|)")
        inline_pattern = re.compile(r"`[^`]+`")
        return bool(markdown_pattern.search(content) or inline_pattern.search(content))

    @classmethod
    def _ensure_introduction_markdown(cls, introduction: str, display_name: str) -> str:
        """将介绍内容兜底格式化为Markdown，避免纯文本展示"""
        normalized = (introduction or "").strip()
        if not normalized:
            return (
                f"### Hi，{display_name}\n\n"
                "- 我可以帮你快速创建专属 AI 应用。\n"
                "- 你可以直接告诉我你的目标、行业和功能需求。"
            )

        if cls._contains_markdown_syntax(normalized):
            return normalized

        lines = [line.strip() for line in normalized.splitlines() if line.strip()]
        sentence_parts: list[str] = []
        for line in lines:
            sentence_parts.extend(
                [
                    part.strip()
                    for part in re.split(r"[。！？!?]\s*", line)
                    if part.strip()
                ]
            )

        if not sentence_parts:
            return f"### Hi，{display_name}\n\n{normalized}"

        title = f"### Hi，{display_name}"
        summary = sentence_parts[0]
        suggestions = sentence_parts[1:4]

        markdown_lines = [title, "", summary]
        if suggestions:
            markdown_lines.extend(["", "#### 建议下一步"])
            markdown_lines.extend([f"- {item}" for item in suggestions])

        return "\n".join(markdown_lines)

    @classmethod
    def convert_create_app_to_tool(cls, account_id: UUID) -> BaseTool:
        """定义自动创建Agent应用LangChain工具"""

        class CreateAppInput(BaseModel):
            """创建Agent/应用输入结构"""

            name: str = Field(
                description="需要创建的Agent/应用名称，长度不超过50个字符"
            )
            description: str = Field(
                description="需要创建的Agent/应用描述，请详细概括该应用的功能"
            )

        @tool("create_app", args_schema=CreateAppInput)
        def create_app(name: str, description: str) -> str:
            """仅当用户明确要求你创建/新建/生成/搭建一个新的Agent或应用时，才调用此工具。不要将其用于普通问答，不要用于“请使用某个智能体回答”这类场景，也不要因为一时未检索到合适的公共Agent就自动创建新应用。"""
            # 1.调用celery异步任务在后端创建应用
            auto_create_app.delay(name, description, account_id)

            # 2.返回成功提示
            return (
                "已调用后端异步任务创建Agent应用，并自动生成开场白和开场建议问题。"
                f"\n应用名称: {name}\n应用描述: {description}"
            )

        return create_app
