import json
import logging
import queue
import threading
import uuid
from contextlib import nullcontext
from dataclasses import dataclass, field

from internal.context import current_app, has_app_context

from internal.core.agent.entities.queue_entity import AgentThought, QueueEvent
from internal.entity.execution_orchestration_entity import (
    TaskPlan,
    TaskPlanItem,
)
from internal.entity.orchestrator_entity import ExecutionMode
from internal.service.agent_task_executor import AgentTaskExecutor
from internal.service.execution_coordinator_service import ExecutionCoordinatorService

logger = logging.getLogger(__name__)

# SSE 队列中用于区分结果/异常/普通 SSE 的标记
_RESULT_MARKER = "__single_agent_result__"
_ERROR_MARKER = "__single_agent_error__"
_SENTINEL = "__single_agent_stop__"


@dataclass
class SingleAgentExecutor:
    """单智能体执行器：将单个 Agent 任务经 ``ExecutionCoordinatorService`` 统一编排。

    覆盖 ``single_agent`` / ``single_agent_with_tools`` / ``deep_thinking`` 三种模式，
    通过构造单条 ``TaskPlanItem`` 走协调器的 single_shot（或 deep_thinking 顺序）路径，
    使其与 multi_agent 路径共享同一套编排与容错能力。

    改造说明：
    - 通过 ``AgentTaskExecutor.event_emitter`` 回调把 ``AgentThought`` 实时推到队列
    - 在子线程中调用 ``coordinator.execute()``，主线程实时 ``yield`` SSE
    - 任务完成后仍发主 thought / message 兼容旧协议，并补一个 ``agent_end`` 收尾事件
    """

    agent_class: type
    agent_config: object = None
    tools: list = field(default_factory=list)
    llm: object = None
    history: list = field(default_factory=list)
    query: str = ""
    long_term_memory: str = ""
    user_memory: str = ""
    # 收集流式期间的 AgentThought 对象，供外层持久化（修复 reload 丢失根因）
    collected_thoughts: list = field(default_factory=list)
    # 子任务实时状态注册表（Hermes /agents 实时状态对齐）
    subtask_registry: object = None
    cancel_token: object = None

    def execute(
        self,
        *,
        query,
        conversation,
        message,
        execution_mode,
        routing_decision=None,
    ):
        conversation_id = str(conversation.id)
        message_id = str(message.id)
        try:
            plan = self._build_plan(query, execution_mode)
            if self.subtask_registry is not None and self.cancel_token is not None:
                try:
                    self.subtask_registry.register_cancel_token(message_id, self.cancel_token)
                except Exception:
                    logger.debug("注册取消令牌失败", exc_info=True)

            # 通过线程 + queue.Queue 让 coordinator.execute() 在后台执行，
            # 主线程实时消费 agent.stream() 产出的 AgentThought 并 yield SSE
            sse_queue: "queue.Queue[Any]" = queue.Queue()
            flask_app = current_app._get_current_object() if has_app_context() else None
            # 跟踪是否已通过流式发送了 answer（避免 _message_sse 重复累加）
            stream_state = {"has_streamed_answer": False}

            def _event_emitter(thought: AgentThought) -> None:
                """AgentTaskExecutor 的实时回调：把 thought 转 SSE 并放入队列。"""
                try:
                    # 收集 thought 对象供外层持久化（修复 reload 丢失根因）
                    self.collected_thoughts.append(thought)
                    # 检测是否是携带 answer 的 AGENT_MESSAGE 事件（流式 token）
                    event_name = getattr(thought, "event", "") or ""
                    if hasattr(event_name, "value"):
                        event_name = event_name.value
                    if (
                        event_name == QueueEvent.AGENT_MESSAGE.value
                        and getattr(thought, "answer", "")
                    ):
                        stream_state["has_streamed_answer"] = True
                    sse = self._thought_to_realtime_sse(thought, conversation_id, message_id)
                    if sse:
                        sse_queue.put(sse)
                except Exception:
                    logger.debug("实时 SSE 转换失败", exc_info=True)

            def _run_coordinator() -> None:
                app_ctx = flask_app.app_context() if flask_app is not None else nullcontext()
                with app_ctx:
                    try:
                        executor = AgentTaskExecutor(
                            agent_class=self.agent_class,
                            agent_config=self.agent_config,
                            tools=self.tools or [],
                            llm=self.llm,
                            history=self.history or [],
                            query=query,
                            long_term_memory=self.long_term_memory,
                            user_memory=self.user_memory,
                            event_emitter=_event_emitter,
                        )
                        coordinator = ExecutionCoordinatorService(
                            executor=executor,
                            cancel_token=self.cancel_token,
                            subtask_registry=self.subtask_registry,
                            request_id=message_id,
                        )
                        results = coordinator.execute(plan)
                        sse_queue.put((_RESULT_MARKER, results))
                    except Exception as e:  # noqa: BLE001
                        sse_queue.put((_ERROR_MARKER, e))
                    finally:
                        sse_queue.put(_SENTINEL)

            thread = threading.Thread(target=_run_coordinator, daemon=True)
            thread.start()

            results = None
            while True:
                try:
                    item = sse_queue.get(timeout=15)
                except queue.Empty:
                    # 长任务（如 Codex OS 自动化 preview）执行期间持续输出心跳，
                    # 避免 SSE 空闲超时把连接杀掉，也避免前端误以为流已中断。
                    yield self._keepalive_sse(conversation_id, message_id)
                    continue
                if item is _SENTINEL:
                    break
                if isinstance(item, tuple) and len(item) == 2 and isinstance(item[0], str) and item[0].startswith("__"):
                    marker, payload = item
                    if marker == _RESULT_MARKER:
                        results = payload
                    elif marker == _ERROR_MARKER:
                        raise payload
                    continue
                # 普通 SSE 字符串，实时下发
                if isinstance(item, str):
                    yield item

            # coordinator 执行完毕，发 billing + 主 thought + message
            if results:
                final_answer = ""
                for result in results:
                    token_usage = (result.metadata or {}).get("token_usage") or {}
                    if token_usage:
                        # 直接构造 BillingUsageDelta 用于 SSE 事件，不再创建独立 aggregator
                        # 外层 assistant_agent_service 的 billing_aggregator 负责累计与扣费
                        from internal.entity.billing_metering_entity import (
                            BillingEventType,
                            BillingUsageDelta,
                        )
                        input_tokens = token_usage.get("prompt_tokens", 0) or 0
                        output_tokens = token_usage.get("completion_tokens", 0) or 0
                        total_tokens = max(input_tokens, 0) + max(output_tokens, 0)
                        delta_credits = int(total_tokens / 1000)
                        billing_delta = BillingUsageDelta(
                            event_type=BillingEventType.DELTA.value,
                            task_id=message_id,
                            source_type="model",
                            source_name="single_agent",
                            delta_credits=delta_credits,
                            total_credits=delta_credits,
                            reason="agent_llm_invoke",
                            metadata={
                                "input_tokens": input_tokens,
                                "output_tokens": output_tokens,
                            },
                        )
                        yield f"event: {BillingEventType.DELTA.value}\ndata:{json.dumps(billing_delta.to_sse())}\n\n"
                    # 主 thought 事件（兼容前端旧协议，将真实 answer 作为 observation）
                    yield self._thought_sse(result, conversation_id, message_id)
                    if result.answer:
                        final_answer = result.answer

                if not final_answer:
                    final_answer = self._pick_answer(results)
                # 如果已通过流式发送了 answer，不再发完整 answer 的 _message_sse（避免前端重复累加）
                # 仅在未流式发送（例如 tool_calls 场景或 LLM 返回空）时发 _message_sse 兜底
                if not stream_state["has_streamed_answer"]:
                    yield self._message_sse(final_answer, conversation_id, message_id)

            # 收尾事件：让前端明确知道 Agent 执行结束
            yield self._agent_end_sse(conversation_id, message_id)
        except Exception as e:
            logger.warning("SingleAgentExecutor 执行失败: %s", e, exc_info=True)
            yield self._fallback_sse(conversation_id, message_id)
            # 补发 AGENT_END 事件，让前端能识别流结束
            yield self._agent_end_sse(conversation_id, message_id)

    @staticmethod
    def _keepalive_sse(conversation_id: str, message_id: str) -> str:
        """长任务执行期间的进度心跳，让前端知道任务仍在运行。"""
        payload = {
            "id": message_id,
            "event": QueueEvent.AGENT_THOUGHT.value,
            "thought": "系统自动化任务执行中，请稍候，我会持续更新状态。",
            "observation": "",
            "tool": "",
            "tool_input": {},
            "answer": "",
            "conversation_id": conversation_id,
            "message_id": message_id,
            "latency": 0.0,
            "total_token_count": 0,
        }
        return (
            f"event: {QueueEvent.AGENT_THOUGHT.value}\n"
            f"data:{json.dumps(payload, ensure_ascii=False)}\n\n"
        )

    def _build_plan(self, query, execution_mode) -> TaskPlan:
        mode = execution_mode or ExecutionMode.SINGLE_AGENT.value
        item = TaskPlanItem(
            task_id="single_agent_task",
            title="单智能体任务",
            description=query,
            execution_order=0,
        )
        return TaskPlan(
            original_query=query,
            items=[item],
            execution_mode=mode,
            reason="single_agent_via_coordinator",
        )

    @staticmethod
    def _pick_answer(results) -> str:
        for result in results:
            if getattr(result, "answer", ""):
                return result.answer
        return ""

    @staticmethod
    def _thought_to_realtime_sse(thought: AgentThought, conversation_id: str, message_id: str):
        """把 ``AgentThought`` 实时转为 SSE 字符串。

        - ``AGENT_MESSAGE``：实时转发（LLM 流式 token），让前端能看到逐字输出
          answer 字段携带 chunk 文本，前端 chat-stream.ts 会累加到 message.answer
        - 跳过 ``AGENT_END`` / ``PING``：``AGENT_END`` 由本执行器在末尾统一发出
        - 其余事件（如 ``agent_thought`` / ``agent_action`` / ``dataset_retrieval`` /
          ``long_term_memory_recall`` / ``deep_step`` / ``deep_complete`` / ``deep_artifact_created`` /
          ``tool_confirmation_required`` 等）实时转发
        """
        event_value = getattr(thought, "event", "") or ""
        if hasattr(event_value, "value"):
            event_value = event_value.value

        if event_value in (
            QueueEvent.AGENT_END.value,
            QueueEvent.PING.value,
        ):
            return None

        thought_text = getattr(thought, "thought", "") or ""
        observation = getattr(thought, "observation", "") or ""
        tool_name = getattr(thought, "tool", "") or ""
        tool_input = getattr(thought, "tool_input", {}) or {}
        answer = getattr(thought, "answer", "") or ""

        # AGENT_MESSAGE 事件：即使 thought_text 为空也转发（可能携带 token 统计）
        # 其他事件：仅转发有内容的事件，避免空事件污染前端
        if event_value != QueueEvent.AGENT_MESSAGE.value:
            if not (thought_text or observation or tool_name):
                return None

        # 对于 AGENT_MESSAGE：仅转发有 answer 内容的 chunk（跳过纯 token 统计的空 answer 事件）
        # 空 answer 的 AGENT_MESSAGE 由 coordinator 完成后统一处理（_thought_sse + _message_sse）
        if event_value == QueueEvent.AGENT_MESSAGE.value and not answer:
            return None

        payload = {
            "id": str(getattr(thought, "id", uuid.uuid4())),
            "thought": thought_text,
            "observation": observation,
            "tool": tool_name,
            "tool_input": tool_input if isinstance(tool_input, dict) else {},
            "confirmation_id": str(getattr(thought, "confirmation_id", "") or ""),
            "confirmation_status": str(getattr(thought, "confirmation_status", "") or ""),
            "execution_summary": str(getattr(thought, "execution_summary", "") or ""),
            "answer": answer,
            "conversation_id": conversation_id,
            "message_id": message_id,
            "latency": float(getattr(thought, "latency", 0.0) or 0.0),
            "total_token_count": int(getattr(thought, "total_token_count", 0) or 0),
        }
        return f"event: {event_value}\ndata:{json.dumps(payload, ensure_ascii=False, default=str)}\n\n"

    @staticmethod
    def _thought_sse(result, conversation_id, message_id) -> str:
        """主 thought 事件：使用真实 answer 作为观察内容，task_id 仅作为辅助标识。"""
        payload = {
            "id": message_id,
            "thought": "single_agent_task",
            "observation": result.answer,
            "answer": result.answer,
            "conversation_id": conversation_id,
            "message_id": message_id,
            "latency": float((result.metadata or {}).get("latency") or 0.0),
            "total_token_count": int((result.metadata or {}).get("token_usage", {}).get("total_tokens") or 0),
        }
        return f"event: {QueueEvent.AGENT_THOUGHT.value}\ndata:{json.dumps(payload, ensure_ascii=False)}\n\n"

    @staticmethod
    def _message_sse(final_answer, conversation_id, message_id) -> str:
        payload = {
            "answer": final_answer or "单智能体执行完成，但未获得有效回答。",
            "id": message_id,
            "conversation_id": conversation_id,
            "message_id": message_id,
        }
        return f"event: {QueueEvent.AGENT_MESSAGE.value}\ndata:{json.dumps(payload, ensure_ascii=False)}\n\n"

    @staticmethod
    def _agent_end_sse(conversation_id, message_id) -> str:
        """显式收尾事件，让前端明确知道 Agent 执行结束。

        与路径 A (AppRuntimeService.stream_agent_events) 保持一致，
        解决 ``agent_end`` 在路径 B 中此前被跳过、前端无法识别完成的问题。
        """
        payload = {
            "id": message_id,
            "conversation_id": conversation_id,
            "message_id": message_id,
        }
        return f"event: {QueueEvent.AGENT_END.value}\ndata:{json.dumps(payload, ensure_ascii=False)}\n\n"

    @staticmethod
    def _fallback_sse(conversation_id, message_id) -> str:
        payload = {
            "answer": "单智能体执行遇到问题，请稍后重试。",
            "id": message_id,
            "conversation_id": conversation_id,
            "message_id": message_id,
        }
        return f"event: {QueueEvent.AGENT_MESSAGE.value}\ndata:{json.dumps(payload, ensure_ascii=False)}\n\n"
