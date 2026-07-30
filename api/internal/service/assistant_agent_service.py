import hashlib
import json
import logging
import re

logger = logging.getLogger(__name__)

from dataclasses import dataclass
from datetime import UTC, datetime
from threading import Lock, Thread
from typing import Any, Generator
from uuid import UUID, uuid4

from flask import current_app, has_app_context
from injector import inject
from redis import Redis
from langchain_core.messages import (
    AIMessage,
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
from .conductor_service import ConductorService
from .orchestration_feature_flag_service import OrchestrationFeatureFlagService
from .result_synthesizer_service import ResultSynthesizerService
from .retrieval_service import RetrievalService
from .runtime_tool_mount_service import RuntimeToolMountService
from internal.entity.runtime_tool_entity import RuntimeToolDescriptor
from .public_agent_a2a_service import PublicAgentA2AService
from .public_agent_registry_service import PublicAgentRegistryService

ASSISTANT_AGENT_MARKDOWN_PRESET_PROMPT = """请遵守以下回复规范：
1. 默认使用Markdown格式输出，优先使用标题、列表、表格、引用和代码块来组织信息。
2. 涉及代码、命令、配置、SQL、JSON、YAML时，必须使用带语言标识的Markdown代码块。
3. 如果没有明确结构化内容需求，也请保持清晰的Markdown排版，不要输出纯大段文本。
4. 当需要调用工具时，优先调用工具；拿到结果后再按上述Markdown规范整理答案。
5. 当用户明确要求“使用/调用/交给某个智能体回答”，或问题明显更适合由某个已发布公共Agent处理时，必须优先调用 `route_public_agents` 工具。
6. `route_public_agents` 会自动完成“检索已有公共Agent + 调用对应Agent + 返回结果”，因此当用户直接要答案时，优先使用它，而不是只返回候选列表。
7. `create_app` 仅用于用户明确要求“我想要/帮我生成/创建/新建/生成/搭建一个新的Agent或应用”等类型的问题时，普通问答场景禁止调用。
8. 如果用户说“请使用xx智能体回答”“让xxAgent来回答”“帮我解决xx”“帮我解决xx等垂直问题”等这是调用已有Agent，不是创建新Agent，禁止调用 `create_app`。
9. 当“调用已有Agent”和“创建新Agent”存在歧义时，默认先调用 `route_public_agents`，不要擅自创建新应用。
""".strip()


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
    ) -> Conversation:
        """解析并返回辅助Agent会话，必要时同步账号当前会话指针"""
        if conversation_id is None:
            return account.assistant_agent_conversation

        conversation = self.get(Conversation, conversation_id)
        if (
            not conversation
            or conversation.created_by != account.id
            or conversation.is_deleted
            or conversation.invoke_from != InvokeFrom.ASSISTANT_AGENT.value
        ):
            raise NotFoundException(
                f"该{ASSISTANT_AGENT_DISPLAY_NAME}会话不存在或已被删除，请核实后重试"
            )

        if sync_active and account.assistant_agent_conversation_id != conversation.id:
            self.update(account, assistant_agent_conversation_id=conversation.id)

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

    def _stream_direct_answer(self, req, account, conversation, message, routing_decision=None):
        """direct_answer 路径：经 ExecutionCoordinatorService 编排 DirectAnswerExecutor。

        如果指挥官已给出 direct_answer 内容（routing_decision.task_plan_summary.direct_answer），
        直接使用，省一次 LLM 调用；否则走 DirectAnswerExecutor 重新生成。
        """
        from internal.entity.billing_metering_entity import BillingEventType
        from internal.service.billing_metering_service import BillingUsageAggregator
        from internal.service.executors.direct_answer_executor import DirectAnswerExecutor
        from internal.entity.execution_orchestration_entity import TaskPlan, TaskPlanItem
        from internal.entity.orchestrator_entity import ExecutionMode
        from internal.service.execution_coordinator_service import ExecutionCoordinatorService

        billing_aggregator = BillingUsageAggregator(task_id=str(message.id))
        billing_started = billing_aggregator.started()
        yield f"event: {BillingEventType.STARTED.value}\ndata:{json.dumps(billing_started.to_sse())}\n\n"

        # 指挥官直接回复路径：省一次 LLM 调用
        conductor_answer = None
        if routing_decision is not None:
            task_plan_summary = routing_decision.get("task_plan_summary") or {}
            conductor_answer = task_plan_summary.get("direct_answer")
        if conductor_answer and conductor_answer.strip():
            yield f"event: {QueueEvent.AGENT_MESSAGE.value}\ndata:{json.dumps({'answer': conductor_answer, 'id': str(message.id), 'conversation_id': str(conversation.id), 'message_id': str(message.id)}, ensure_ascii=False)}\n\n"
            yield f"event: {BillingEventType.FINAL.value}\ndata:{json.dumps(billing_aggregator.final().to_sse())}\n\n"
            yield f"event: {QueueEvent.AGENT_END.value}\ndata:{json.dumps({'id': str(message.id), 'conversation_id': str(conversation.id), 'message_id': str(message.id)}, ensure_ascii=False)}\n\n"
            return

        try:
            executor = DirectAnswerExecutor(
                language_model_service=self.language_model_service,
                credit_service=self.credit_service,
                account_id=account.id,
            )
            plan = TaskPlan(
                original_query=req.query.data,
                items=[
                    TaskPlanItem(
                        task_id="direct_answer",
                        title="直接回答",
                        description=req.query.data,
                        execution_order=0,
                    )
                ],
                execution_mode=ExecutionMode.DIRECT_ANSWER.value,
                reason="direct_answer_via_coordinator",
            )
            coordinator = ExecutionCoordinatorService(executor=executor)
            results = coordinator.execute(plan)

            final_answer = ""
            fallback_msg = ""
            for result in results:
                token_usage = (result.metadata or {}).get("token_usage") or {}
                if token_usage:
                    billing_delta = billing_aggregator.model_tokens(
                        "direct_answer",
                        input_tokens=token_usage.get("prompt_tokens", 0),
                        output_tokens=token_usage.get("completion_tokens", 0),
                        reason="direct_answer_llm_invoke",
                    )
                    yield f"event: {BillingEventType.DELTA.value}\ndata:{json.dumps(billing_delta.to_sse())}\n\n"
                if result.answer:
                    final_answer = result.answer
                yield f"event: {QueueEvent.AGENT_THOUGHT.value}\ndata:{json.dumps({'id': str(message.id), 'thought': result.task_id, 'observation': result.answer, 'answer': result.answer, 'conversation_id': str(conversation.id), 'message_id': str(message.id), 'latency': 0, 'total_token_count': 0}, ensure_ascii=False)}\n\n"

            if final_answer:
                yield f"event: {QueueEvent.AGENT_MESSAGE.value}\ndata:{json.dumps({'answer': final_answer, 'id': str(message.id), 'conversation_id': str(conversation.id), 'message_id': str(message.id)}, ensure_ascii=False)}\n\n"
            else:
                # LLM 调用失败或返回空回答时，提取错误信息发送兜底 AGENT_MESSAGE，
                # 避免用户看到空响应（DirectAnswerExecutor.execute 内部 try/except 会吞掉异常）
                error_detail = ""
                for result in results:
                    if result.errors:
                        error_detail = "; ".join(result.errors)
                        break
                # 同时从 metadata 提取原始错误信息（如果有的话）
                for result in results:
                    meta_error = (result.metadata or {}).get("error") or ""
                    if meta_error:
                        error_detail = f"{error_detail}: {meta_error}" if error_detail else meta_error
                        break
                fallback_msg = f"直接回答执行失败（{error_detail}），请稍后重试或换种方式提问。" if error_detail else "未获得有效回答，请稍后重试或换种方式提问。"
                logger.warning("direct_answer 路径未获得有效回答: errors=%s", error_detail)
                yield f"event: {QueueEvent.AGENT_MESSAGE.value}\ndata:{json.dumps({'answer': fallback_msg, 'id': str(message.id), 'conversation_id': str(conversation.id), 'message_id': str(message.id)}, ensure_ascii=False)}\n\n"

            billing_summary = billing_aggregator.summary()
            yield f"event: {BillingEventType.SUMMARY.value}\ndata:{json.dumps(billing_summary.to_sse())}\n\n"
            billing_final = billing_aggregator.final()
            yield f"event: {BillingEventType.FINAL.value}\ndata:{json.dumps(billing_final.to_sse())}\n\n"

            # 持久化 answer 到 Message 表（save_agent_thoughts 仅在 agent_thoughts 含 AGENT_MESSAGE 事件时更新 answer，
            # direct_answer 路径传入空 agent_thoughts，需在此显式落库，否则前端 reload 后 answer 为空）
            # final_answer 为空时持久化兜底消息，避免 reload 后 answer 仍为空
            answer_to_persist = final_answer or fallback_msg
            if answer_to_persist:
                try:
                    msg = self.get(Message, message.id)
                    if msg is not None:
                        self.update(msg, answer=answer_to_persist)
                except Exception:
                    logger.warning("持久化 direct_answer 到 Message.answer 失败", exc_info=True)

            # 对话后写入记忆（同步降级，不影响主流程）
            yield from self._write_memory_from_conversation(
                account, req.query.data, answer_to_persist, conversation.id
            )
        except Exception:
            logger.warning("direct_answer 经协调器执行失败", exc_info=True)
            billing_cancelled = billing_aggregator.cancelled(pending_phases=["直接回答"])
            yield f"event: {BillingEventType.CANCELLED.value}\ndata:{json.dumps(billing_cancelled.to_sse())}\n\n"
            yield f"event: {QueueEvent.AGENT_MESSAGE.value}\ndata:{json.dumps({'answer': '直接回答遇到问题，请稍后重试。', 'id': str(message.id), 'conversation_id': str(conversation.id), 'message_id': str(message.id)}, ensure_ascii=False)}\n\n"

    def _stream_multi_agent(self, req, account, conversation, message, routing_decision, llm, tools, history):
        """multi_agent 路径：委托 MultiAgentExecutor 协调多 Agent 执行，外层包裹计费事件。"""
        from internal.entity.billing_metering_entity import BillingEventType
        from internal.service.billing_metering_service import BillingUsageAggregator
        from internal.service.executors.multi_agent_executor import MultiAgentExecutor
        from internal.service.executors.task_decomposer import TaskDecomposer

        billing_aggregator = BillingUsageAggregator(task_id=str(message.id))
        billing_started = billing_aggregator.started()
        yield f"event: {BillingEventType.STARTED.value}\ndata:{json.dumps(billing_started.to_sse())}\n\n"

        try:
            from internal.service.dag_engine_service import DAGEngine
            from internal.service.agent_instance_pool import AgentInstancePool
            executor = MultiAgentExecutor(
                db=self.db,
                task_decomposer=TaskDecomposer(
                    language_model_service=self.language_model_service
                ),
                dag_engine=DAGEngine(db=self.db),
                agent_instance_pool=AgentInstancePool(),
            )
            final_answer = ""
            agent_message_event_prefix = f"event: {QueueEvent.AGENT_MESSAGE.value}"
            for chunk in executor.execute(
                query=req.query.data,
                account=account,
                conversation=conversation,
                message=message,
                routing_decision=routing_decision,
                llm=llm,
                tools=tools,
                history=history,
            ):
                # 截获 AGENT_MESSAGE 事件以提取最终答案，用于记忆写入
                if chunk.startswith(agent_message_event_prefix):
                    try:
                        data_part = chunk.split("data:", 1)[1].strip()
                        payload = json.loads(data_part)
                        if payload.get("answer"):
                            final_answer = payload["answer"]
                    except Exception:
                        pass
                yield chunk

            billing_summary = billing_aggregator.summary()
            yield f"event: {BillingEventType.SUMMARY.value}\ndata:{json.dumps(billing_summary.to_sse())}\n\n"
            billing_final = billing_aggregator.final()
            yield f"event: {BillingEventType.FINAL.value}\ndata:{json.dumps(billing_final.to_sse())}\n\n"

            # 持久化 answer 到 Message 表（同 direct_answer / single_agent 路径）
            if final_answer:
                try:
                    msg = self.get(Message, message.id)
                    if msg is not None:
                        self.update(msg, answer=final_answer)
                except Exception:
                    logger.warning("持久化 multi_agent answer 到 Message.answer 失败", exc_info=True)

            # 对话后写入记忆（同步降级，不影响主流程）
            yield from self._write_memory_from_conversation(
                account, req.query.data, final_answer, conversation.id
            )
        except Exception as e:
            logger.warning("多智能体执行失败: %s", e, exc_info=True)
            billing_cancelled = billing_aggregator.cancelled(pending_phases=["多智能体执行"])
            yield f"event: {BillingEventType.CANCELLED.value}\ndata:{json.dumps(billing_cancelled.to_sse())}\n\n"
            yield f"event: {QueueEvent.AGENT_MESSAGE.value}\ndata:{json.dumps({'answer': '多智能体执行遇到问题，请稍后重试。', 'id': str(message.id), 'conversation_id': str(conversation.id), 'message_id': str(message.id)}, ensure_ascii=False)}\n\n"

    def _stream_single_agent(
        self, req, account, conversation, message, routing_decision, llm, tools, history, should_deep_think,
        distant_summary="", user_memory_text="",
    ):
        """single_agent / deep_thinking 路径：经 ExecutionCoordinatorService 编排单 Agent。"""
        from internal.entity.billing_metering_entity import BillingEventType
        from internal.service.billing_metering_service import BillingUsageAggregator
        from internal.service.executors.single_agent_executor import SingleAgentExecutor
        from internal.entity.orchestrator_entity import ExecutionMode

        billing_aggregator = BillingUsageAggregator(task_id=str(message.id))
        billing_started = billing_aggregator.started()
        yield f"event: {BillingEventType.STARTED.value}\ndata:{json.dumps(billing_started.to_sse())}\n\n"

        try:
            agent_class = A2ADeepThinkingAgent if should_deep_think else FunctionCallAgent
            agent_config = AgentConfig(
                user_id=account.id,
                invoke_from=InvokeFrom.ASSISTANT_AGENT.value,
                preset_prompt=ASSISTANT_AGENT_MARKDOWN_PRESET_PROMPT,
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
            collected_answer = ""
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
                        collected_answer = payload.get("answer", "")
                    except Exception:
                        pass
                yield chunk

            billing_summary = billing_aggregator.summary()
            yield f"event: {BillingEventType.SUMMARY.value}\ndata:{json.dumps(billing_summary.to_sse())}\n\n"
            billing_final = billing_aggregator.final()
            yield f"event: {BillingEventType.FINAL.value}\ndata:{json.dumps(billing_final.to_sse())}\n\n"

            # 持久化 answer 到 Message 表（与 direct_answer 路径同理，
            # _persist_assistant_thoughts 传入空 agent_thoughts，需在此显式落库）
            if collected_answer:
                try:
                    msg = self.get(Message, message.id)
                    if msg is not None:
                        self.update(msg, answer=collected_answer)
                except Exception:
                    logger.warning("持久化 single_agent answer 到 Message.answer 失败", exc_info=True)

            yield from self._write_memory_from_conversation(account, req.query.data, collected_answer, conversation.id)
        except Exception as e:
            logger.warning("单智能体经协调器执行失败: %s", e, exc_info=True)
            billing_cancelled = billing_aggregator.cancelled(pending_phases=["单智能体执行"])
            yield f"event: {BillingEventType.CANCELLED.value}\ndata:{json.dumps(billing_cancelled.to_sse())}\n\n"
            yield f"event: {QueueEvent.AGENT_MESSAGE.value}\ndata:{json.dumps({'answer': '单智能体执行遇到问题，请稍后重试。', 'id': str(message.id), 'conversation_id': str(conversation.id), 'message_id': str(message.id)}, ensure_ascii=False)}\n\n"

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
                flask_app = current_app._get_current_object() if has_app_context() else None
                account_id = account.id

                def _bg_write():
                    """后台线程：push app context 后执行记忆写入。"""
                    if flask_app is None:
                        logger.warning("记忆写入后台线程跳过: 缺少 Flask app 引用")
                        return
                    ctx = flask_app.app_context()
                    ctx.push()
                    try:
                        from app.http.app import injector
                        memory_write_service = injector.get(MemoryWriteService)
                        memory_write_service.write_from_conversation(
                            account=account,
                            query=query,
                            ai_response=ai_response,
                            conversation_id=conversation_id,
                        )
                    except Exception:
                        logger.warning("后台记忆写入失败，不影响主流程", exc_info=True)
                    finally:
                        ctx.pop()

                Thread(target=_bg_write, daemon=True).start()
        except Exception:
            logger.warning("记忆写入调度失败，不影响主流程", exc_info=True)

        # 保持 generator 兼容性，不再 yield 任何 SSE 事件
        yield from ()

    def _build_assistant_runtime_tools(self, account_id: UUID) -> list[BaseTool]:
        """构建首页助手运行时工具，包括公共 Agent、创建应用和全局 MCP 绑定。"""
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
            if d.source_type in ("api", "api_tool", "builtin", "builtin_tool", "knowledge")
        ]

        extra_tools: list[BaseTool] = []

        # 1. 加载 MCP 工具
        if mcp_provider_ids:
            extra_tools.extend(
                self._load_mcp_tools_by_provider_ids(account_id, mcp_provider_ids)
            )

        # 2. 加载非 MCP 工具（builtin / api_tool / knowledge）
        for descriptor in non_mcp_descriptors:
            tool = self._load_non_mcp_tool(descriptor, account_id=account_id)
            if tool is not None:
                extra_tools.append(tool)

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

    def _load_non_mcp_tool(self, descriptor, *, account_id: str = "") -> BaseTool | None:
        """根据 RuntimeToolDescriptor 加载 builtin/api_tool/knowledge 类型的 LangChain 工具。

        - builtin: 通过 ``builtin_provider_manager.get_tool(provider_name, tool_name)`` 加载
        - api: 查询 ApiTool 后通过 ``api_provider_manager.get_tool`` 加载
        - knowledge: 通过 ``RetrievalService.create_knowledge_retrieval_tool`` 加载
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

    def chat(self, req: AssistantAgentChat, account: Account) -> Generator:
        """传递query与账号实现与辅助Agent进行会话"""
        # 1.获取辅助Agent对应的id
        assistant_agent_id = current_app.config.get("ASSISTANT_AGENT_ID")

        # 2.获取当前会话信息（支持按conversation_id切换）
        conversation = self._resolve_assistant_agent_conversation(
            account=account,
            conversation_id=self._resolve_conversation_id(req.conversation_id.data),
            sync_active=True,
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

        # 4.新建一条消息记录
        message = self.create(
            Message,
            app_id=assistant_agent_id,
            conversation_id=conversation.id,
            invoke_from=InvokeFrom.ASSISTANT_AGENT.value,
            created_by=account.id,
            query=req.query.data,
            image_urls=req.image_urls.data,
            status=MessageStatus.NORMAL.value,
        )
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
                logger.warning("指挥官决策失败，回退到规则编排: %s", exc)
                routing_decision = None

        if routing_decision is None and self.orchestrator_service is not None:
            try:
                routing_decision = self.orchestrator_service.decide(
                    req.query.data,
                    account_id=account.id,
                    conversation_id=conversation.id,
                    message_id=message.id,
                    image_urls=req.image_urls.data,
                    enable_deep_thinking=bool(req.confirm_deep_thinking.data),
                ).to_dict()
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

        # 5.构建三层混合上下文（近期原文层/远期摘要层/关键事实层）
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
                return
            if execution_mode == "deep_thinking":
                yield from self._stream_deep_thinking_proposal(routing_decision)
                return
            if execution_mode == "direct_answer":
                yield from self._stream_direct_answer(req, account, conversation, message, routing_decision)
                self._persist_assistant_thoughts(account, assistant_agent_id, conversation, message, {}, routing_decision)
                return
            if execution_mode in ("multi_agent", "multi_agent_parallel", "multi_agent_sequential"):
                yield from self._stream_multi_agent(req, account, conversation, message, routing_decision, llm, tools, history)
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
            )
        finally:
            # 无论 Agent 流正常完成还是异常终止，都尝试落库
            # _persist_assistant_thoughts 内部已有 try/except，不会抛异常出去
            self._persist_assistant_thoughts(account, assistant_agent_id, conversation, message, {}, routing_decision)
        return

    def _persist_assistant_thoughts(self, account, assistant_agent_id, conversation, message, agent_thoughts, routing_decision):
        """持久化消息与推理过程到数据库。"""
        try:
            self.conversation_service.save_agent_thoughts(
                account_id=account.id,
                app_id=assistant_agent_id,
                app_config={
                    "long_term_memory": {"enable": True},
                },
                conversation_id=conversation.id,
                message_id=message.id,
                agent_thoughts=[agent_thought for agent_thought in agent_thoughts.values()] if isinstance(agent_thoughts, dict) else (agent_thoughts or []),
                routing_decision=routing_decision,
            )
        except Exception:
            logger.warning("持久化推理过程失败", exc_info=True)

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
        self.update(account, assistant_agent_conversation_id=None)

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
        prompt_messages = [SystemMessage(content=f"""
你是OpenAgent，你的输出将直接展示在首页开场介绍中。
请基于用户历史信息生成一段"个性化欢迎介绍"，要求如下：
1. 开头必须包含问候语：Hi，{display_name}
2. 先识别该用户近期意图与关注方向，再给出针对性引导；不要编造不存在的信息。
3. 明确说明你支持基于用户输入进行 function call，自动调用工具并帮助生成垂直Agent的后端能力代码与应用配置。
4. 内容要兼顾"欢迎介绍 + 下一步建议"，可给2~4条简短建议。
5. 语气专业、自然、简洁，长度控制在120~260字，输出必须是Markdown格式。
6. 建议使用二级或三级标题 + 2~4条列表项，让排版更清晰；不要输出JSON。
7. 输出语言尽量与用户最近提问语言保持一致；如果无法判断则使用中文。
""".strip())]

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
