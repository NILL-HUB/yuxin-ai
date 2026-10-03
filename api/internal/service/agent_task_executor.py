import logging
import re
import uuid
from typing import Callable, Optional

from internal.core.agent.entities.queue_entity import AgentThought, QueueEvent
from internal.core.agent.usage_utils import summarize_agent_thoughts

logger = logging.getLogger(__name__)

# 子代理「无法完成」约定标记：模型按系统提示词要求在确实无法完成任务时，
# 于回答中输出「无法完成：<原因>」。零成本检测此标记即可把「跑完但没做成」
# 与「真的成功」区分开，进而在编排层触发指挥官重规划。
_BLOCK_MARKER_PATTERN = re.compile(r"无法完成\s*[:：]\s*(?P<reason>[^\n\r]*)")

# 「可疑」零成本判定阈值：回答短于该长度、且任务描述足够具体时，补一次
# LLM 自评，兜底捕捉「模型未按约定标记、但实际没做成」的情况。
_SUSPICIOUS_ANSWER_MAX_LEN = 20
_MIN_TASK_DESCRIPTION_LEN = 20


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
        # 申请追加工具的 provider：(query, reason, current_tools) -> (说明文本, 新工具列表)。
        # 由上层（assistant_agent_service）注入；为 None 时不挂载 request_more_tools。
        extra_tool_provider: Optional[Callable[..., object]] = None,
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
        self.extra_tool_provider = extra_tool_provider

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

    @staticmethod
    def _detect_blocked(answer: str) -> tuple[bool, str]:
        """检测子代理是否按约定标记申明「无法完成」。

        返回 (blocked, reason)。仅命中约定标记时 blocked=True；未命中表示
        「未申明阻塞」，由上游按可疑度判断是否补一次语义自评。
        """
        if not answer:
            return False, ""
        match = _BLOCK_MARKER_PATTERN.search(answer)
        if not match:
            return False, ""
        reason = (match.group("reason") or "").strip()
        return True, reason

    @staticmethod
    def _looks_suspicious(item, answer: str) -> bool:
        """零成本可疑度判定：回答为空/极短，且任务描述足够具体。

        只对「本该有实质产出却没产出」的情况补一次语义自评，trivial 任务
        （如“输出 hello”）不触发额外 LLM 调用。
        """
        text = (answer or "").strip()
        if len(text) >= _SUSPICIOUS_ANSWER_MAX_LEN:
            return False
        description = str(getattr(item, "description", "") or "").strip()
        return len(description) >= _MIN_TASK_DESCRIPTION_LEN

    def _evaluate_completion(self, item, answer: str) -> tuple[bool, str] | None:
        """可疑时补一次 LLM 自评，判定子任务是否真正完成。

        返回 ``(blocked, blocking_reason)``；返回 None 表示自评不可用
        （无模型 / 调用异常），此时保持原判定，避免误报阻塞。
        """
        try:
            from langchain_core.messages import HumanMessage, SystemMessage

            from internal.service.language_model_service import LanguageModelService
            from internal.service.system_prompt_library_service import SystemPromptLibraryService

            llm = LanguageModelService.get_feature_model("subtask_completion_evaluation")
            if llm is None:
                return None
            system_prompt = SystemPromptLibraryService().get_prompt_or_default(
                "subtask_completion_evaluator"
            )
            description = str(getattr(item, "description", "") or "").strip()
            response = llm.invoke([
                SystemMessage(content=system_prompt),
                HumanMessage(
                    content=(
                        f"子任务描述：\n{description}\n\n"
                        f"子代理回答：\n{answer.strip() or '（空）'}"
                    )
                ),
            ])
            text = str(getattr(response, "content", "") or "").strip()
            if not text:
                return None
            lines = [line.strip() for line in text.splitlines() if line.strip()]
            headline = (lines[0] if lines else "").upper()
            if "NOT_COMPLETED" in headline or "NOT COMPLETED" in headline:
                reason = lines[1] if len(lines) > 1 else ""
                return True, (reason or "自评判定子任务未完成")
            return False, ""
        except Exception:
            logger.warning("子任务完成度自评失败，保持原判定", exc_info=True)
            return None

    def _run_once(self, item, context: dict | None = None) -> dict:
        try:
            agent_config = self._resolve_agent_config(item)
            agent = self.agent_class(llm=self.llm, agent_config=agent_config)
            self._attach_meta_tools(agent)

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

            blocked, blocking_reason = self._detect_blocked(collected_answer)
            # 约定标记未命中时，对「可疑」结果补一次语义自评（覆盖模型未按约定
            # 输出标记、但实际并未完成任务的情况）。
            if not blocked and self._looks_suspicious(item, collected_answer):
                evaluated = self._evaluate_completion(item, collected_answer)
                if evaluated is not None:
                    blocked, blocking_reason = evaluated
            return {
                "agent_id": item.task_id,
                "task_id": item.task_id,
                "answer": collected_answer,
                "confidence": 1.0,
                "sources": [],
                "tool_calls": tool_calls,
                "warnings": [],
                "errors": [],
                "blocked": blocked,
                "blocking_reason": blocking_reason,
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
                    "agent_blocked": blocked,
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

    def _attach_meta_tools(self, agent) -> None:
        """把 ``request_more_tools`` 元工具注入 Agent 实例的工具列表。

        追加的工具直接写回 ``agent.agent_config.tools``：``FunctionCallAgent`` 每轮
        LLM 调用都会重读该列表，因此本轮申请到的工具在**同一执行的后续轮次**即生效。
        未注入 provider（如无编排链路）时不挂载，保持原行为。
        """
        provider = self.extra_tool_provider
        if provider is None:
            return
        config = getattr(agent, "agent_config", None)
        if config is None or not hasattr(config, "model_copy"):
            return
        try:
            from internal.core.agent.meta_tools.request_more_tools import (
                REQUEST_MORE_TOOLS_NAME,
                build_request_more_tools_tool,
            )
        except Exception:
            logger.warning("加载 request_more_tools 元工具失败", exc_info=True)
            return

        def _provide(query: str, reason: str) -> str:
            current = list(
                getattr(getattr(agent, "agent_config", None), "tools", None) or []
            )
            try:
                result = provider(query, reason, current)
            except Exception:
                logger.warning("申请追加工具失败", exc_info=True)
                return "申请追加工具失败，请继续用现有工具尽力完成。"
            text, new_tools = "", []
            if isinstance(result, tuple) and len(result) == 2:
                text, new_tools = result
            elif isinstance(result, str):
                text = result
            if new_tools:
                self._merge_into_agent_tools(agent, new_tools)
            return text or "已处理工具申请，请继续完成任务。"

        existing = list(getattr(config, "tools", None) or [])
        if any(
            getattr(tool, "name", "") == REQUEST_MORE_TOOLS_NAME for tool in existing
        ):
            return
        meta_tool = build_request_more_tools_tool(_provide)
        try:
            agent.agent_config = config.model_copy(
                update={"tools": [*existing, meta_tool]}
            )
        except Exception:
            logger.warning("挂载 request_more_tools 失败", exc_info=True)

    @staticmethod
    def _merge_into_agent_tools(agent, new_tools) -> None:
        """把新工具并入 Agent 实例的工具列表（按工具名去重）。"""
        config = getattr(agent, "agent_config", None)
        if config is None or not hasattr(config, "model_copy"):
            return
        current = list(getattr(config, "tools", None) or [])
        names = {getattr(tool, "name", "") for tool in current}
        merged = list(current)
        for tool in new_tools:
            name = getattr(tool, "name", "")
            if name and name not in names:
                merged.append(tool)
                names.add(name)
        if len(merged) == len(current):
            return
        try:
            agent.agent_config = config.model_copy(update={"tools": merged})
        except Exception:
            logger.warning("追加工具到 Agent 失败", exc_info=True)

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
