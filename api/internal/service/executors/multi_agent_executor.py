"""多智能体执行器。

对齐 Hermes 子代理委派：把路由决策中的多个子任务按 ``TaskPlan`` 交给
``ExecutionCoordinatorService`` 执行（parallel / sequential），执行期间通过
``subtask_started`` / ``subtask_running`` / ``subtask_completed`` SSE 事件实时
推送状态，并把状态写入 ``SubtaskRegistryService`` 供 ``GET /subtasks/<request_id>`` 查询。
"""

import json
import logging
import queue
import threading
from contextlib import nullcontext
from dataclasses import dataclass, field
from typing import Any

from internal.context import current_app, has_app_context
from internal.core.agent.entities.queue_entity import AgentThought, QueueEvent
from internal.entity.execution_orchestration_entity import TaskPlan, TaskPlanItem
from internal.service.agent_task_executor import AgentTaskExecutor
from internal.service.execution_coordinator_service import ExecutionCoordinatorService
from internal.service.executors.single_agent_executor import SingleAgentExecutor

logger = logging.getLogger(__name__)

_RESULT_MARKER = "__multi_agent_result__"
_ERROR_MARKER = "__multi_agent_error__"
_SENTINEL = "__multi_agent_stop__"

_MULTI_AGENT_MODES = {
    "multi_agent",
    "multi_agent_parallel",
    "multi_agent_sequential",
}


@dataclass
class MultiAgentExecutor:
    """把多子任务计划经 ExecutionCoordinatorService 统一执行并实时推送状态。"""

    agent_class: type
    agent_config: object = None
    tools: list = field(default_factory=list)
    llm: object = None
    history: list = field(default_factory=list)
    query: str = ""
    long_term_memory: str = ""
    user_memory: str = ""
    subtask_registry: object = None
    cancel_token: object = None
    collected_thoughts: list = field(default_factory=list)

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
        routing_decision = routing_decision or {}
        try:
            plan = self._build_plan(query, execution_mode, routing_decision)
            if self.subtask_registry is not None and self.cancel_token is not None:
                try:
                    self.subtask_registry.register_cancel_token(message_id, self.cancel_token)
                except Exception:
                    logger.debug("注册取消令牌失败", exc_info=True)
            # 先下发完整任务规划，前端据此初始化子任务看板
            yield self._subtask_plan_sse(plan, conversation_id, message_id)

            sse_queue: "queue.Queue[Any]" = queue.Queue()
            flask_app = current_app._get_current_object() if has_app_context() else None
            stream_state = {"has_streamed_answer": False}

            def _event_emitter(thought: AgentThought) -> None:
                """AgentTaskExecutor 实时回调：把 thought 转 SSE 并放入队列。"""
                try:
                    self.collected_thoughts.append(thought)
                    event_name = getattr(thought, "event", "") or ""
                    if hasattr(event_name, "value"):
                        event_name = event_name.value
                    if (
                        event_name == QueueEvent.AGENT_MESSAGE.value
                        and getattr(thought, "answer", "")
                    ):
                        stream_state["has_streamed_answer"] = True
                    sse = SingleAgentExecutor._thought_to_realtime_sse(
                        thought, conversation_id, message_id
                    )
                    if sse:
                        sse_queue.put(sse)
                except Exception:
                    logger.debug("实时 SSE 转换失败", exc_info=True)

            def _run_coordinator() -> None:
                app_ctx = flask_app.app_context() if flask_app is not None else nullcontext()
                with app_ctx:
                    try:
                        task_executor = _SubtaskTaskExecutor(
                            host=self,
                            event_emitter=_event_emitter,
                            sse_queue=sse_queue,
                            conversation_id=conversation_id,
                            message_id=message_id,
                        )
                        coordinator = ExecutionCoordinatorService(
                            executor=task_executor,
                            cancel_token=self.cancel_token,
                            subtask_registry=self.subtask_registry,
                            request_id=message_id,
                        )
                        results = coordinator.execute(plan, request_id=message_id)
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
                    yield self._keepalive_sse(conversation_id, message_id)
                    continue
                if item is _SENTINEL:
                    break
                if (
                    isinstance(item, tuple)
                    and len(item) == 2
                    and isinstance(item[0], str)
                    and item[0].startswith("__")
                ):
                    marker, payload = item
                    if marker == _RESULT_MARKER:
                        results = payload
                    elif marker == _ERROR_MARKER:
                        raise payload
                    continue
                if isinstance(item, str):
                    yield item

            if results:
                final_answer, synthesis_meta = self._aggregate(
                    results,
                    plan.aggregation_strategy,
                )
                for result in results:
                    yield self._billing_delta_sse(result, conversation_id, message_id)
                if final_answer:
                    stream_state["has_streamed_answer"] = True
                yield self._message_sse(
                    final_answer,
                    synthesis_meta,
                    conversation_id,
                    message_id,
                )
            yield self._agent_end_sse(conversation_id, message_id)
        except Exception as e:
            logger.warning("MultiAgentExecutor 执行失败: %s", e, exc_info=True)
            yield self._fallback_sse(conversation_id, message_id)
            yield self._agent_end_sse(conversation_id, message_id)

    def _build_plan(self, query, execution_mode, routing_decision: dict) -> TaskPlan:
        mode = execution_mode if execution_mode in _MULTI_AGENT_MODES else "multi_agent_parallel"
        task_plan_summary = routing_decision.get("task_plan_summary") or {}
        agents = task_plan_summary.get("agents") or []
        if not agents:
            agent_subset = routing_decision.get("agent_subset") or {}
            agents = (
                agent_subset.get("selected")
                or agent_subset.get("selected_agents")
                or []
            )

        items: list[TaskPlanItem] = []
        for index, agent in enumerate(agents):
            if not isinstance(agent, dict):
                continue
            task_id = str(agent.get("task_id") or f"task-{index + 1}")
            items.append(
                TaskPlanItem(
                    task_id=task_id,
                    title=str(agent.get("title") or f"子任务 {index + 1}"),
                    description=str(agent.get("description") or query),
                    agent_pool=str(agent.get("agent_pool") or "general"),
                    required_capabilities=list(agent.get("required_capabilities") or []),
                    depends_on=list(agent.get("depends_on") or []),
                    execution_order=int(agent.get("execution_order") or index),
                    risk_level=str(agent.get("risk_level") or "safe"),
                    agent_id=str(agent.get("agent_id") or task_id),
                    tools=list(agent.get("tools") or []),
                    timeout_seconds=float(agent.get("timeout_seconds") or 0),
                )
            )

        if not items:
            items.append(
                TaskPlanItem(
                    task_id="task-1",
                    title="子任务",
                    description=query,
                    agent_pool="general",
                )
            )

        return TaskPlan(
            original_query=query,
            items=items,
            execution_mode=mode,
            reason=str(routing_decision.get("reason") or "multi_agent"),
            aggregation_strategy=self._aggregation_strategy(routing_decision),
        )

    @staticmethod
    def _aggregation_strategy(routing_decision: dict) -> str:
        task_plan_summary = routing_decision.get("task_plan_summary") or {}
        strategy = str(
            task_plan_summary.get("aggregation_strategy")
            or routing_decision.get("aggregation_strategy")
            or "concat"
        )
        return strategy if strategy in {"concat", "summarize", "best_of"} else "concat"

    def _aggregate(self, results, strategy: str):
        valid = [result for result in results if getattr(result, "answer", "")]
        if strategy == "best_of" and valid:
            best = max(valid, key=lambda result: float(result.confidence or 0))
            return best.answer, {
                "summary": best.answer,
                "confidence": float(best.confidence or 0),
                "visible_sources": list(getattr(best, "sources", []) or []),
                "user_warnings": list(getattr(best, "warnings", []) or []),
            }

        answers = [str(result.answer or "").strip() for result in valid if str(result.answer or "").strip()]
        summary = "\n\n".join(answers)
        if strategy == "summarize":
            summary = self._llm_summarize(answers) or summary
        sources: list[str] = []
        warnings: list[str] = []
        confidence_values: list[float] = []
        for result in valid:
            for source in list(getattr(result, "sources", []) or []):
                if source not in sources:
                    sources.append(str(source))
            for warning in list(getattr(result, "warnings", []) or []):
                if warning not in warnings:
                    warnings.append(str(warning))
            try:
                confidence_values.append(float(result.confidence or 0))
            except (TypeError, ValueError):
                confidence_values.append(0.0)
        return summary, {
            "summary": summary,
            "confidence": round(sum(confidence_values) / len(confidence_values), 4)
            if confidence_values
            else 0.0,
            "visible_sources": sources,
            "user_warnings": warnings,
        }

    def _llm_summarize(self, answers: list[str]) -> str:
        """用 LLM 综合各子任务答案；失败或不可用时回退拼接。"""
        if self.llm is None or not answers:
            return ""
        invoke = getattr(self.llm, "invoke", None)
        if not callable(invoke):
            return ""
        try:
            from langchain_core.messages import HumanMessage, SystemMessage

            payload = "\n\n".join(
                f"[子任务 {index + 1}]\n{text}"
                for index, text in enumerate(answers)
            )
            response = invoke(
                [
                    SystemMessage(
                        content=(
                            "你是多智能体结果汇总器。请综合以下各子任务的答案，"
                            "输出一份连贯、去重、保留关键事实与来源线索的最终结论。"
                        )
                    ),
                    HumanMessage(content=payload),
                ]
            )
            content = getattr(response, "content", "")
            if content is None:
                content = str(response)
            return str(content).strip()
        except Exception as exc:
            logger.warning("LLM 结果合成失败，回退拼接: %s", exc, exc_info=True)
            return ""

    @staticmethod
    def _subtask_plan_sse(plan: TaskPlan, conversation_id: str, message_id: str) -> str:
        items = [
            {
                "task_id": item.task_id,
                "title": item.title,
                "description": item.description,
                "depends_on": list(item.depends_on),
                "execution_order": item.execution_order,
                "agent_id": item.agent_id,
                "tools": list(item.tools),
                "risk_level": item.risk_level,
                "timeout_seconds": item.timeout_seconds,
            }
            for item in plan.items
        ]
        payload = {
            "id": message_id,
            "task_id": message_id,
            "conversation_id": conversation_id,
            "message_id": message_id,
            "execution_mode": plan.execution_mode,
            "aggregation_strategy": plan.aggregation_strategy,
            "reason": plan.reason,
            "task_count": len(plan.items),
            "items": items,
        }
        return f"event: {QueueEvent.SUBTASK_STARTED.value}\ndata:{json.dumps(payload, ensure_ascii=False)}\n\n"

    @staticmethod
    def _subtask_running_sse(item: TaskPlanItem, conversation_id: str, message_id: str) -> str:
        payload = {
            "id": message_id,
            "task_id": item.task_id,
            "agent_id": item.agent_id or item.task_id,
            "status": "running",
            "conversation_id": conversation_id,
            "message_id": message_id,
        }
        return f"event: {QueueEvent.SUBTASK_RUNNING.value}\ndata:{json.dumps(payload, ensure_ascii=False)}\n\n"

    @staticmethod
    def _subtask_completed_sse(
        item: TaskPlanItem,
        result: dict,
        conversation_id: str,
        message_id: str,
    ) -> str:
        errors = list(result.get("errors") or [])
        payload = {
            "id": message_id,
            "task_id": item.task_id,
            "agent_id": str(result.get("agent_id") or item.agent_id or item.task_id),
            "status": "failed" if errors else "completed",
            "answer_preview": str(result.get("answer") or "")[:200],
            "confidence": float(result.get("confidence") or 0),
            "errors": errors,
            "conversation_id": conversation_id,
            "message_id": message_id,
        }
        return f"event: {QueueEvent.SUBTASK_COMPLETED.value}\ndata:{json.dumps(payload, ensure_ascii=False)}\n\n"

    @staticmethod
    def _keepalive_sse(conversation_id: str, message_id: str) -> str:
        payload = {
            "id": message_id,
            "event": QueueEvent.AGENT_THOUGHT.value,
            "thought": "多智能体任务执行中，请稍候，我会持续更新子任务状态。",
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

    @staticmethod
    def _billing_delta_sse(result, conversation_id: str, message_id: str) -> str:
        token_usage = (result.metadata or {}).get("token_usage") or {}
        if not token_usage:
            return ""
        from internal.entity.billing_metering_entity import (
            BillingEventType,
            BillingUsageDelta,
        )

        input_tokens = int(token_usage.get("prompt_tokens") or 0)
        output_tokens = int(token_usage.get("completion_tokens") or 0)
        total_tokens = max(input_tokens, 0) + max(output_tokens, 0)
        if total_tokens <= 0:
            return ""
        delta_credits = int(total_tokens / 1000)
        billing_delta = BillingUsageDelta(
            event_type=BillingEventType.DELTA.value,
            task_id=message_id,
            source_type="model",
            source_name="multi_agent",
            delta_credits=delta_credits,
            total_credits=delta_credits,
            reason="agent_llm_invoke",
            metadata={
                "input_tokens": input_tokens,
                "output_tokens": output_tokens,
                "task_id": result.task_id,
            },
        )
        return f"event: {BillingEventType.DELTA.value}\ndata:{json.dumps(billing_delta.to_sse())}\n\n"

    @staticmethod
    def _message_sse(
        final_answer: str,
        synthesis_meta: dict,
        conversation_id: str,
        message_id: str,
    ) -> str:
        payload = {
            "answer": final_answer or "多智能体执行完成，但未获得有效回答。",
            "id": message_id,
            "conversation_id": conversation_id,
            "message_id": message_id,
            "summary": synthesis_meta.get("summary", ""),
            "confidence": synthesis_meta.get("confidence", 0.0),
            "visible_sources": synthesis_meta.get("visible_sources", []),
            "user_warnings": synthesis_meta.get("user_warnings", []),
        }
        return f"event: {QueueEvent.AGENT_MESSAGE.value}\ndata:{json.dumps(payload, ensure_ascii=False)}\n\n"

    @staticmethod
    def _agent_end_sse(conversation_id: str, message_id: str) -> str:
        payload = {
            "id": message_id,
            "conversation_id": conversation_id,
            "message_id": message_id,
        }
        return f"event: {QueueEvent.AGENT_END.value}\ndata:{json.dumps(payload, ensure_ascii=False)}\n\n"

    @staticmethod
    def _fallback_sse(conversation_id: str, message_id: str) -> str:
        payload = {
            "answer": "多智能体执行遇到问题，请稍后重试。",
            "id": message_id,
            "conversation_id": conversation_id,
            "message_id": message_id,
        }
        return f"event: {QueueEvent.AGENT_MESSAGE.value}\ndata:{json.dumps(payload, ensure_ascii=False)}\n\n"


class _SubtaskTaskExecutor:
    """ExecutionCoordinator 的 TaskExecutor 适配：每个子任务包一层实时事件。"""

    def __init__(
        self,
        *,
        host: MultiAgentExecutor,
        event_emitter,
        sse_queue: "queue.Queue[Any]",
        conversation_id: str,
        message_id: str,
    ):
        self.host = host
        self.event_emitter = event_emitter
        self.sse_queue = sse_queue
        self.conversation_id = conversation_id
        self.message_id = message_id

    def execute(self, item: TaskPlanItem) -> dict:
        try:
            self.sse_queue.put(
                MultiAgentExecutor._subtask_running_sse(
                    item,
                    self.conversation_id,
                    self.message_id,
                )
            )

            def _event_emitter_with_activity(thought: AgentThought) -> None:
                if self.host.subtask_registry is not None:
                    try:
                        self.host.subtask_registry.mark_activity(
                            self.message_id,
                            item.task_id,
                        )
                    except Exception:
                        pass
                if self.event_emitter is not None:
                    self.event_emitter(thought)

            task_executor = AgentTaskExecutor(
                agent_class=self.host.agent_class,
                agent_config=self.host.agent_config,
                tools=self.host.tools or [],
                llm=self.host.llm,
                history=self.host.history or [],
                query=item.description or self.host.query,
                long_term_memory=self.host.long_term_memory,
                user_memory=self.host.user_memory,
                event_emitter=_event_emitter_with_activity,
            )
            result = task_executor.execute(item)
            if self.host.subtask_registry is not None:
                try:
                    self.host.subtask_registry.mark_activity(
                        self.message_id,
                        item.task_id,
                    )
                except Exception:
                    pass
            self.sse_queue.put(
                MultiAgentExecutor._subtask_completed_sse(
                    item,
                    result,
                    self.conversation_id,
                    self.message_id,
                )
            )
            return result
        except Exception as e:  # noqa: BLE001
            logger.warning("子任务执行失败: %s", e, exc_info=True)
            result = {
                "agent_id": item.agent_id or item.task_id,
                "task_id": item.task_id,
                "answer": "",
                "errors": ["agent_execution_failed"],
                "warnings": [],
                "confidence": 0,
            }
            self.sse_queue.put(
                MultiAgentExecutor._subtask_completed_sse(
                    item,
                    result,
                    self.conversation_id,
                    self.message_id,
                )
            )
            return result
