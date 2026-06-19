import json
import logging

from internal.core.agent.agents.function_call_agent import FunctionCallAgent
from internal.core.agent.entities.queue_entity import QueueEvent
from internal.entity.execution_orchestration_entity import TaskPlan, TaskPlanItem
from internal.service.agent_task_executor import AgentTaskExecutor
from internal.service.execution_coordinator_service import ExecutionCoordinatorService

logger = logging.getLogger(__name__)


class MultiAgentExecutor:
    def __init__(self, agent_config, tools, llm):
        self.agent_config = agent_config
        self.tools = tools or []
        self.llm = llm

    def stream(self, query, history, conversation_id, message_id, execution_mode="parallel"):
        try:
            executor = AgentTaskExecutor(
                agent_class=FunctionCallAgent,
                agent_config=self.agent_config,
                tools=self.tools,
                llm=self.llm,
                history=history or [],
                query=query,
            )
            plan_items = [
                TaskPlanItem(
                    task_id=str(message_id),
                    title=query,
                    description=query,
                    execution_order=0,
                )
            ]
            plan = TaskPlan(
                original_query=query,
                items=plan_items,
                execution_mode=execution_mode,
            )
            coordinator = ExecutionCoordinatorService(executor=executor)
            results = coordinator.execute(plan)

            final_answer = ""
            for result in results:
                if result.answer:
                    final_answer = result.answer
                yield self._thought_sse(result, conversation_id, message_id)

            yield self._message_sse(final_answer, conversation_id, message_id)
        except Exception as e:
            logger.warning("MultiAgentExecutor 执行失败: %s", e, exc_info=True)
            yield self._fallback_sse(conversation_id, message_id)

    @staticmethod
    def _thought_sse(result, conversation_id, message_id):
        payload = {
            "id": str(message_id),
            "thought": result.task_id,
            "observation": result.answer,
            "answer": result.answer,
            "conversation_id": str(conversation_id),
            "message_id": str(message_id),
            "latency": 0,
            "total_token_count": 0,
        }
        return f"event: {QueueEvent.AGENT_THOUGHT.value}\ndata:{json.dumps(payload, ensure_ascii=False)}\n\n"

    @staticmethod
    def _message_sse(final_answer, conversation_id, message_id):
        payload = {
            "answer": final_answer or "多智能体执行完成，但未获得有效回答。",
            "id": str(message_id),
            "conversation_id": str(conversation_id),
            "message_id": str(message_id),
        }
        return f"event: {QueueEvent.AGENT_MESSAGE.value}\ndata:{json.dumps(payload, ensure_ascii=False)}\n\n"

    @staticmethod
    def _fallback_sse(conversation_id, message_id):
        payload = {
            "answer": "多智能体执行遇到问题，请稍后重试。",
            "id": str(message_id),
            "conversation_id": str(conversation_id),
            "message_id": str(message_id),
        }
        return f"event: {QueueEvent.AGENT_MESSAGE.value}\ndata:{json.dumps(payload, ensure_ascii=False)}\n\n"
