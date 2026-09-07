import logging
import uuid
from typing import Callable, Optional

from internal.core.agent.entities.queue_entity import AgentThought, QueueEvent
from internal.core.agent.usage_utils import summarize_agent_thoughts

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

    def execute(self, item, context: dict | None = None) -> dict:
        """执行单个 Agent 任务（带一次安全续跑）。

        续跑语义（断点续传-编排层）：Agent 执行中断且**未产生任何工具调用与可见
        回答**时（失败点只可能是纯 LLM 推理阶段，无工具副作用），用同一份完整
        上下文（history + query + 记忆）自动重放一次。LLM 调用级的重连/换模型已由
        RuntimeFallbackLanguageModelProxy 负责；本层兜底「模型池全故障后短暂恢复」
        等极端场景。一旦执行过程中已调用过工具，则不再重放（避免副作用重复）。
        """
        result = self._run_once(item, context)
        if self._is_replayable_failure(result):
            logger.warning(
                "Agent 执行无副作用失败（无工具调用/无可见输出），继承上下文续跑一次 task_id=%s",
                item.task_id,
            )
            result = self._run_once(item, context)
        return result

    @staticmethod
    def _is_replayable_failure(result: dict) -> bool:
        """判断是否可安全续跑：LLM/Agent 执行终态失败且未调用工具（无副作用）。

        判定依据：
        - 执行过程中出现过 ERROR/TIMEOUT/STOP 终态事件（metadata.terminal_failure）；
        - 未调用过任何工具（tool_calls 为空）——避免工具副作用重复；
        - errors 为空（errors 代表代码/构造级失败，重放也会同样失败）。
        """
        if not result:
            return False
        errors = result.get("errors") or []
        if errors:
            return False
        tool_calls = result.get("tool_calls") or []
        if tool_calls:
            return False
        metadata = result.get("metadata") or {}
        return bool(metadata.get("terminal_failure"))

    def _run_once(self, item, context: dict | None = None) -> dict:
        try:
            agent_config = self._resolve_agent_config(item)
            agent = self.agent_class(llm=self.llm, agent_config=agent_config)

            collected_answer = ""
            tool_calls: list[dict] = []
            agent_thoughts: list[dict] = []
            thought_objects: list = []
            total_token_count = 0
            total_price = 0.0
            latency = 0.0
            total_cached_tokens = 0
            saw_terminal_failure = False

            for thought in agent.stream({
                "messages": [
                    self.llm.convert_to_human_message(
                        self._resolve_query(item, context),
                        [],
                    )
                ],
                "history": self.history,
                "long_term_memory": self.long_term_memory,
                "user_memory": self.user_memory,
            }):
                thought_objects.append(thought)
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
                cached_val = getattr(thought, "cached_token_count", 0)
                if isinstance(cached_val, (int, float)) and cached_val > 0:
                    total_cached_tokens += int(cached_val)
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

                # 检测 LLM/Agent 执行终态失败（ERROR/TIMEOUT/STOP）：
                # 失败被 base_agent 吸收为终态事件而非异常，这里记录信号供安全续跑判定
                if event_name in (
                    QueueEvent.ERROR.value,
                    QueueEvent.TIMEOUT.value,
                    QueueEvent.STOP.value,
                ):
                    saw_terminal_failure = True

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

            usage_summary = summarize_agent_thoughts(thought_objects)
            prompt_tokens = int(getattr(usage_summary, "total_token_count", 0) or 0)
            tokens = {
                "prompt_tokens": prompt_tokens,
                "completion_tokens": 0,
                "total_tokens": prompt_tokens,
                "cached_input_tokens": total_cached_tokens,
            }

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
                    "token_usage": tokens,
                    "latency": latency,
                    "terminal_failure": saw_terminal_failure,
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

    def _resolve_query(self, item, context: dict | None = None) -> str:
        base_query = item.description or self.query
        upstream = (context or {}).get("upstream_results") or {}
        if not upstream:
            return base_query
        sections = []
        for task_id, result in upstream.items():
            answer = (result or {}).get("answer", "")
            if answer:
                sections.append(f"[子任务 {task_id}]\n{answer}")
        if not sections:
            return base_query
        return (
            f"{base_query}\n\n"
            "以下是本次任务依赖的上游子任务输出，请基于这些输出继续完成：\n"
            + "\n\n".join(sections)
        )

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
