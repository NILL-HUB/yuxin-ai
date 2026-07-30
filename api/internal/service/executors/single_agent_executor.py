import json
import logging
import queue
import threading
import uuid
from contextlib import nullcontext
from dataclasses import dataclass, field
from typing import Any

from flask import current_app, has_app_context

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
    - 入口处先把 ``routing_decision`` 作为 ``orchestrator_routing`` 事件下发，让前端可见编排决策
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
            # 入口下发路由决策事件，让前端可见执行模式 / 模型档位 / 选中工具等
            yield from self._emit_routing_decision_sse(routing_decision, conversation_id, message_id)

            plan = self._build_plan(query, execution_mode)

            # 通过线程 + queue.Queue 让 coordinator.execute() 在后台执行，
            # 主线程实时消费 agent.stream() 产出的 AgentThought 并 yield SSE
            sse_queue: "queue.Queue[Any]" = queue.Queue()
            flask_app = current_app._get_current_object() if has_app_context() else None

            def _event_emitter(thought: AgentThought) -> None:
                """AgentTaskExecutor 的实时回调：把 thought 转 SSE 并放入队列。"""
                try:
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
                        coordinator = ExecutionCoordinatorService(executor=executor)
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
                item = sse_queue.get()
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
                        from internal.entity.billing_metering_entity import BillingEventType
                        from internal.service.billing_metering_service import BillingUsageAggregator
                        billing_delta = BillingUsageAggregator(task_id=message_id).model_tokens(
                            "single_agent",
                            input_tokens=token_usage.get("prompt_tokens", 0),
                            output_tokens=token_usage.get("completion_tokens", 0),
                            reason="agent_llm_invoke",
                        )
                        yield f"event: {BillingEventType.DELTA.value}\ndata:{json.dumps(billing_delta.to_sse())}\n\n"
                    # 主 thought 事件（兼容前端旧协议，将真实 answer 作为 observation）
                    yield self._thought_sse(result, conversation_id, message_id)
                    if result.answer:
                        final_answer = result.answer

                if not final_answer:
                    final_answer = self._pick_answer(results)
                yield self._message_sse(final_answer, conversation_id, message_id)

            # 收尾事件：让前端明确知道 Agent 执行结束
            yield self._agent_end_sse(conversation_id, message_id)
        except Exception as e:
            logger.warning("SingleAgentExecutor 执行失败: %s", e, exc_info=True)
            yield self._fallback_sse(conversation_id, message_id)

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
    def _emit_routing_decision_sse(routing_decision, conversation_id, message_id):
        """把 routing_decision 以 ``orchestrator_routing`` 事件下发，让前端展示编排决策。

        兼容旧前端：如果 routing_decision 为空则不发；前端不识别该事件也会被忽略。
        """
        if not routing_decision:
            return
        # 如果 routing_decision 是对象（dataclass / pydantic），先转 dict
        if isinstance(routing_decision, dict):
            payload_data = dict(routing_decision)
        else:
            payload_data = getattr(routing_decision, "__dict__", None) or {}
            if hasattr(routing_decision, "model_dump"):
                try:
                    payload_data = routing_decision.model_dump()
                except Exception:
                    payload_data = {}
        payload = {
            "id": message_id,
            "conversation_id": conversation_id,
            "message_id": message_id,
            "routing": payload_data,
            # 平铺几个关键字段方便前端直接读取
            "execution_mode": payload_data.get("execution_mode", ""),
            "intent": payload_data.get("intent", ""),
            "complexity": payload_data.get("complexity", ""),
            "recommended_model_tier": payload_data.get("recommended_model_tier", ""),
            "risk_level": payload_data.get("risk_level", ""),
            "needs_deep_thinking": payload_data.get("needs_deep_thinking", False),
            "needs_tools": payload_data.get("needs_tools", False),
            "needs_agent": payload_data.get("needs_agent", False),
            "needs_multi_agent": payload_data.get("needs_multi_agent", False),
        }
        yield f"event: {QueueEvent.ORCHESTRATOR_ROUTING.value}\ndata:{json.dumps(payload, ensure_ascii=False, default=str)}\n\n"

    @staticmethod
    def _pick_answer(results) -> str:
        for result in results:
            if getattr(result, "answer", ""):
                return result.answer
        return ""

    @staticmethod
    def _thought_to_realtime_sse(thought: AgentThought, conversation_id: str, message_id: str):
        """把 ``AgentThought`` 实时转为 SSE 字符串。

        - 跳过 ``AGENT_MESSAGE``：避免与最终 ``_message_sse`` 重复，同时避免缓冲文本被部分下发
        - 跳过 ``AGENT_END`` / ``PING``：``AGENT_END`` 由本执行器在末尾统一发出
        - 其余事件（如 ``agent_thought`` / ``agent_action`` / ``dataset_retrieval`` /
          ``long_term_memory_recall`` / ``deep_step`` / ``deep_complete`` / ``deep_artifact_created`` /
          ``tool_confirmation_required`` 等）实时转发
        """
        event_value = getattr(thought, "event", "") or ""
        if hasattr(event_value, "value"):
            event_value = event_value.value

        if event_value in (
            QueueEvent.AGENT_MESSAGE.value,
            QueueEvent.AGENT_END.value,
            QueueEvent.PING.value,
        ):
            return None

        thought_text = getattr(thought, "thought", "") or ""
        observation = getattr(thought, "observation", "") or ""
        tool_name = getattr(thought, "tool", "") or ""
        tool_input = getattr(thought, "tool_input", {}) or {}

        # 仅转发有内容的事件，避免空事件污染前端
        if not (thought_text or observation or tool_name):
            return None

        payload = {
            "id": str(getattr(thought, "id", uuid.uuid4())),
            "thought": thought_text,
            "observation": observation,
            "tool": tool_name,
            "tool_input": tool_input if isinstance(tool_input, dict) else {},
            "answer": "",
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
