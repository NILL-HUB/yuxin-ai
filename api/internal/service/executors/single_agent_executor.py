import json
import logging

from internal.core.agent.agents.function_call_agent import FunctionCallAgent
from internal.core.agent.entities.queue_entity import QueueEvent

logger = logging.getLogger(__name__)


class SingleAgentExecutor:
    def __init__(self, agent_config, tools, llm):
        self.agent_config = agent_config
        self.tools = tools or []
        self.llm = llm

    def stream(self, query, history, conversation_id, message_id):
        try:
            agent = FunctionCallAgent(llm=self.llm, agent_config=self.agent_config)
            human_message = self.llm.convert_to_human_message(query, [])
            for agent_thought in agent.stream({
                "messages": [human_message],
                "history": history or [],
                "long_term_memory": "",
                "user_memory": "",
            }):
                try:
                    sse = self._to_sse(agent_thought, conversation_id, message_id)
                    if sse:
                        yield sse
                except Exception:
                    logger.warning("SingleAgentExecutor 序列化事件失败", exc_info=True)
        except Exception as e:
            logger.warning("SingleAgentExecutor 执行失败: %s", e, exc_info=True)
            yield self._error_sse(e, conversation_id, message_id)

    @staticmethod
    def _to_sse(agent_thought, conversation_id, message_id):
        event_value = (
            agent_thought.event.value
            if hasattr(agent_thought.event, "value")
            else str(agent_thought.event)
        )
        payload = agent_thought.model_dump(
            include={
                "event",
                "thought",
                "observation",
                "tool",
                "tool_input",
                "answer",
                "latency",
                "total_token_count",
            }
        )
        payload["id"] = str(message_id)
        payload["conversation_id"] = str(conversation_id)
        payload["message_id"] = str(message_id)
        payload["task_id"] = str(getattr(agent_thought, "task_id", ""))
        return f"event: {event_value}\ndata:{json.dumps(payload, ensure_ascii=False)}\n\n"

    @staticmethod
    def _error_sse(error, conversation_id, message_id):
        payload = {
            "observation": str(error),
            "id": str(message_id),
            "conversation_id": str(conversation_id),
            "message_id": str(message_id),
        }
        return f"event: {QueueEvent.ERROR.value}\ndata:{json.dumps(payload, ensure_ascii=False)}\n\n"
