import json
import logging
from dataclasses import dataclass, field

from internal.core.agent.entities.queue_entity import QueueEvent
from internal.entity.execution_orchestration_entity import (
    TaskPlan,
    TaskPlanItem,
)
from internal.entity.orchestrator_entity import ExecutionMode
from internal.service.agent_task_executor import AgentTaskExecutor
from internal.service.execution_coordinator_service import ExecutionCoordinatorService

logger = logging.getLogger(__name__)


@dataclass
class SingleAgentExecutor:
    """单智能体执行器：将单个 Agent 任务经 ``ExecutionCoordinatorService`` 统一编排。

    覆盖 ``single_agent`` / ``single_agent_with_tools`` / ``deep_thinking`` 三种模式，
    通过构造单条 ``TaskPlanItem`` 走协调器的 single_shot（或 deep_thinking 顺序）路径，
    使其与 multi_agent 路径共享同一套编排与容错能力。
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
            plan = self._build_plan(query, execution_mode)
            executor = AgentTaskExecutor(
                agent_class=self.agent_class,
                agent_config=self.agent_config,
                tools=self.tools or [],
                llm=self.llm,
                history=self.history or [],
                query=query,
                long_term_memory=self.long_term_memory,
                user_memory=self.user_memory,
            )
            coordinator = ExecutionCoordinatorService(executor=executor)
            results = coordinator.execute(plan)

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
                yield self._thought_sse(result, conversation_id, message_id)

            final_answer = self._pick_answer(results)
            yield self._message_sse(final_answer, conversation_id, message_id)
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
    def _pick_answer(results) -> str:
        for result in results:
            if getattr(result, "answer", ""):
                return result.answer
        return ""

    @staticmethod
    def _thought_sse(result, conversation_id, message_id) -> str:
        payload = {
            "id": message_id,
            "thought": result.task_id,
            "observation": result.answer,
            "answer": result.answer,
            "conversation_id": conversation_id,
            "message_id": message_id,
            "latency": 0,
            "total_token_count": 0,
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
    def _fallback_sse(conversation_id, message_id) -> str:
        payload = {
            "answer": "单智能体执行遇到问题，请稍后重试。",
            "id": message_id,
            "conversation_id": conversation_id,
            "message_id": message_id,
        }
        return f"event: {QueueEvent.AGENT_MESSAGE.value}\ndata:{json.dumps(payload, ensure_ascii=False)}\n\n"
