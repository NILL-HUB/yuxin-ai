import logging
import uuid
from typing import Callable, Optional

from internal.core.agent.entities.queue_entity import AgentThought, QueueEvent

logger = logging.getLogger(__name__)


class AgentTaskExecutor:
    """将 Agent 类适配为 ExecutionCoordinator 的 TaskExecutor。

    支持通过 ``event_emitter`` 回调实时转发 ``AgentThought`` 事件，
    让上层执行器（如 ``SingleAgentExecutor``）能在 Agent 执行过程中即时 yield SSE，
    而不必等待整个任务完成才能批量回放。
    """

    def __init__(
        self,
        agent_class,
        agent_config=None,
        tools=None,
        llm=None,
        history=None,
        query="",
        long_term_memory="",
        user_memory="",
        event_emitter: Optional[Callable[[AgentThought], None]] = None,
    ):
        self.agent_class = agent_class
        self.agent_config = agent_config
        self.tools = tools or []
        self.llm = llm
        self.history = history or []
        self.query = query
        self.long_term_memory = long_term_memory
        self.user_memory = user_memory
        # 实时事件回调：每次从 agent.stream() 收到 AgentThought 时调用一次
        # 用于把推理/工具调用/记忆召回等中间事件实时推给前端
        self.event_emitter = event_emitter

    def execute(self, item) -> dict:
        try:
            agent_config = self._resolve_agent_config(item)
            agent = self.agent_class(llm=self.llm, agent_config=agent_config)

            collected_answer = ""
            tool_calls: list[dict] = []
            agent_thoughts: list[dict] = []
            total_token_count = 0
            total_price = 0.0
            latency = 0.0

            for thought in agent.stream({
                "messages": [self.llm.convert_to_human_message(item.description or self.query, [])],
                "history": self.history,
                "long_term_memory": self.long_term_memory,
                "user_memory": self.user_memory,
            }):
                event_name = getattr(thought, "event", "") or ""
                if hasattr(event_name, "value"):
                    event_name = event_name.value
                thought_text = getattr(thought, "thought", "") or ""
                observation = getattr(thought, "observation", "") or ""
                tool_name = getattr(thought, "tool", "") or ""
                tool_input = getattr(thought, "tool_input", {}) or {}
                answer = getattr(thought, "answer", "") or ""

                # 实时转发事件给回调（如果有），让前端能立即看到推理/工具调用/记忆召回等中间状态
                if self.event_emitter is not None:
                    try:
                        self.event_emitter(thought)
                    except Exception:
                        logger.debug("event_emitter 转发事件失败", exc_info=True)

                # 聚合 token/价格/延迟统计（取最大累加值，AGENT_MESSAGE 末尾事件会带累计值）
                # 使用 isinstance 检查防止 MagicMock 等非数字类型导致 max() 抛出 TypeError
                token_count_val = getattr(thought, "total_token_count", 0)
                if isinstance(token_count_val, (int, float)) and token_count_val > total_token_count:
                    total_token_count = int(token_count_val)
                total_price_val = getattr(thought, "total_price", 0.0)
                if isinstance(total_price_val, (int, float)) and total_price_val > total_price:
                    total_price = float(total_price_val)
                latency_val = getattr(thought, "latency", 0.0)
                if isinstance(latency_val, (int, float)) and latency_val > 0:
                    latency += float(latency_val)

                # 记录所有 AgentThought 到 metadata
                try:
                    agent_thoughts.append({
                        "id": str(getattr(thought, "id", uuid.uuid4())),
                        "event": event_name,
                        "thought": thought_text,
                        "observation": observation,
                        "tool": tool_name,
                        "tool_input": tool_input if isinstance(tool_input, dict) else {},
                        "answer": answer,
                        "latency": float(getattr(thought, "latency", 0.0) or 0.0),
                        "total_token_count": int(getattr(thought, "total_token_count", 0) or 0),
                    })
                except Exception:
                    logger.debug("agent_thought 序列化失败", exc_info=True)

                # 收集工具调用事件（AGENT_ACTION / DATASET_RETRIEVAL）
                if event_name in (
                    QueueEvent.AGENT_ACTION.value,
                    QueueEvent.DATASET_RETRIEVAL.value,
                ) and tool_name:
                    tool_calls.append({
                        "name": tool_name,
                        "args": tool_input if isinstance(tool_input, dict) else {},
                        "result": observation,
                        "event": event_name,
                    })

                # 累加 AGENT_MESSAGE 的 answer 作为最终答案
                if event_name == QueueEvent.AGENT_MESSAGE.value and answer:
                    collected_answer = collected_answer + answer if collected_answer else answer

            return {
                "agent_id": item.task_id,
                "task_id": item.task_id,
                "answer": collected_answer,
                "confidence": 1.0,
                "sources": [],
                "tool_calls": tool_calls,
                "warnings": [],
                "errors": [],
                "cost": {
                    "total_tokens": total_token_count,
                    "total_price": total_price,
                },
                "metadata": {
                    "title": item.title,
                    "agent_thoughts": agent_thoughts,
                    "token_usage": {
                        "total_tokens": total_token_count,
                        "prompt_tokens": 0,
                        "completion_tokens": 0,
                    },
                    "latency": latency,
                },
            }
        except Exception as e:
            logger.warning("AgentTaskExecutor 执行失败: %s", e, exc_info=True)
            return {
                "agent_id": "",
                "task_id": item.task_id,
                "answer": "",
                "errors": ["agent_execution_failed"],
                "warnings": [],
                "confidence": 0,
            }

    def _resolve_agent_config(self, item):
        agent_config = self.agent_config
        item_tools = getattr(item, "tools", None) or []
        if not item_tools:
            return agent_config
        try:
            from internal.core.agent.entities.agent_entity import AgentConfig

            if isinstance(agent_config, AgentConfig):
                base_tools = list(agent_config.tools or [])
                if not base_tools:
                    return agent_config
                requested = {str(name).strip() for name in item_tools if name}
                filtered = [
                    tool for tool in base_tools
                    if getattr(tool, "name", None) in requested
                ]
                if filtered and len(filtered) != len(base_tools):
                    return agent_config.model_copy(update={"tools": filtered})
        except Exception:
            return agent_config
        return agent_config
