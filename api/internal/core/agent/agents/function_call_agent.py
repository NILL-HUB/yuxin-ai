import json
import logging
import re
import time
import uuid
from typing import Literal, Any, ClassVar

import tiktoken
from langchain_core.messages import HumanMessage, SystemMessage, ToolMessage, RemoveMessage, AIMessage
from langchain_core.messages import messages_to_dict
from langgraph.constants import END
from langgraph.graph import StateGraph
from langgraph.graph.state import CompiledStateGraph
from internal.core.agent.entities.agent_entity import (
    AgentState,
    get_agent_system_prompt_template,
    get_max_iteration_response,
)
from internal.core.agent.entities.sandbox_policy_entity import SandboxPolicy
from internal.core.agent.entities.tool_policy_entity import ToolPolicy
from internal.core.agent.entities.queue_entity import AgentThought, QueueEvent
from internal.core.agent.adapters.hermes.midturn_redirect import (
    consume_redirect as _consume_redirect,
    build_redirect_decision as _build_redirect_decision,
)
from internal.core.agent.usage_utils import normalize_usage_text
from internal.exception import FailException
from .base_agent import BaseAgent
from internal.core.language_model.entities.model_entity import ModelFeature

logger = logging.getLogger(__name__)


class FunctionCallAgent(BaseAgent):
    """基于函数/工具调用的智能体"""

    _PROMPT_ONLY_SKILL_LOADER_PREFIX: ClassVar[str] = "skill_prompt__"
    _CONFIRMATION_WAIT_SECONDS: ClassVar[int] = 600
    _CONFIRMATION_POLL_INTERVAL_SECONDS: ClassVar[float] = 1.0

    def _build_agent(self) -> CompiledStateGraph:
        """构建LangGraph图结构编译程序"""
        # 1.创建图
        graph = StateGraph(AgentState)

        # 2.添加节点
        graph.add_node("preset_operation", self._preset_operation_node)
        graph.add_node("long_term_memory_recall", self._long_term_memory_recall_node)
        graph.add_node("llm", self._llm_node)
        graph.add_node("tools", self._tools_node)

        # 3.添加边，并设置起点和终点
        graph.set_entry_point("preset_operation")
        graph.add_conditional_edges("preset_operation", self._preset_operation_condition)
        graph.add_edge("long_term_memory_recall", "llm")
        graph.add_conditional_edges("llm", self._tools_condition)
        graph.add_edge("tools", "llm")

        # 4.编译应用并返回（兼容 object.__new__ 构造的测试实例：agent_config 可能不存在）
        agent_config = getattr(self, "agent_config", None)
        if agent_config is not None and getattr(agent_config, "enable_checkpoint", False):
            from internal.core.agent.checkpointer import get_async_checkpointer
            checkpointer = get_async_checkpointer()
            if checkpointer is not None:
                agent = graph.compile(checkpointer=checkpointer)
                return agent
        agent = graph.compile()

        return agent

    @classmethod
    def _sanitize_sandbox_artifact_text(cls, content: str) -> str:
        """去除用户可见文本中的沙箱本地路径与伪下载链接。"""
        return SandboxPolicy.sanitize_sandbox_artifact_text(content)

    def _preset_operation_node(self, state: AgentState) -> AgentState:
        """预设操作，涵盖：输入审核、数据预处理、条件边等"""
        # 1.获取审核配置与用户输入query
        review_config = self.agent_config.review_config
        query = state["messages"][-1].content

        # 2.检测是否开启审核配置
        if review_config["enable"] and review_config["inputs_config"]["enable"]:
            contains_keyword = any(keyword in query for keyword in review_config["keywords"])
            # 3.如果包含敏感词则执行后续步骤
            if contains_keyword:
                preset_response = review_config["inputs_config"]["preset_response"]
                self.agent_queue_manager.publish(state["task_id"], AgentThought(
                    id=uuid.uuid4(),
                    task_id=state["task_id"],
                    event=QueueEvent.AGENT_MESSAGE.value,
                    thought=preset_response,
                    message=messages_to_dict(state["messages"]),
                    answer=preset_response,
                    latency=0,
                ))
                self.agent_queue_manager.publish(state["task_id"], AgentThought(
                    id=uuid.uuid4(),
                    task_id=state["task_id"],
                    event=QueueEvent.AGENT_END.value,
                ))
                return {"messages": [AIMessage(preset_response)]}

        return {"messages": []}

    def _long_term_memory_recall_node(self, state: AgentState) -> AgentState:
        """长期记忆召回节点"""
        # 1.根据传递的智能体配置判断是否需要召回长期记忆
        long_term_memory = ""
        if self.agent_config.enable_long_term_memory:
            long_term_memory = state["long_term_memory"]
            self.agent_queue_manager.publish(state["task_id"], AgentThought(
                id=uuid.uuid4(),
                task_id=state["task_id"],
                event=QueueEvent.LONG_TERM_MEMORY_RECALL.value,
                observation=long_term_memory,
            ))

        # 2.构建预设消息列表，并将preset_prompt+long_term_memory+user_memory填充到系统消息中
        user_memory = state.get("user_memory", "") or ""
        preset_messages = [
            SystemMessage(get_agent_system_prompt_template("agent_system_prompt_template").format(
                preset_prompt=self.agent_config.preset_prompt,
                long_term_memory=long_term_memory,
                user_memory=user_memory,
            ))
        ]

        # 3.将短期历史消息添加到消息列表中
        history = state["history"]
        if isinstance(history, list) and len(history) > 0:
            # 4.校验历史消息是不是复数形式，也就是[人类消息, AI消息, 人类消息, AI消息, ...]
            if len(history) % 2 != 0:
                self.agent_queue_manager.publish_error(state["task_id"], "智能体历史消息列表格式错误")
                logging.exception(
                    f"智能体历史消息列表格式错误, len(history)={len(history)}, history={json.dumps(messages_to_dict(history), ensure_ascii=False, default=str)}"
                )
                raise FailException("智能体历史消息列表格式错误")
            # 5.拼接历史消息
            preset_messages.extend(history)

        # 6.拼接当前用户的提问信息
        human_message = state["messages"][-1]
        preset_messages.append(HumanMessage(human_message.content))

        # 7.处理预设消息，将预设消息添加到用户消息前，先去删除用户的原始消息，然后补充一个新的代替
        return {
            "messages": [RemoveMessage(id=human_message.id), *preset_messages],
        }

    async def _llm_node(self, state: AgentState) -> AgentState:
        """大语言模型节点（async：LLM 流式调用使用 astream，不阻塞事件循环）"""
        # 1.检测当前Agent迭代次数是否符合需求
        if state["iteration_count"] > self.agent_config.max_iteration_count:
            max_iteration_response = get_max_iteration_response()
            self.agent_queue_manager.publish(
                state["task_id"],
                AgentThought(
                    id=uuid.uuid4(),
                    task_id=state["task_id"],
                    event=QueueEvent.AGENT_MESSAGE.value,
                    thought=max_iteration_response,
                    message=messages_to_dict(state["messages"]),
                    answer=max_iteration_response,
                    latency=0,
                ))
            self.agent_queue_manager.publish(
                state["task_id"],
                AgentThought(
                    id=uuid.uuid4(),
                    task_id=state["task_id"],
                    event=QueueEvent.AGENT_END.value,
                ))
            return {"messages": [AIMessage(max_iteration_response)], "pending_skill_prompts": []}

        # 2.从智能体配置中提取大语言模型
        id = uuid.uuid4()
        start_at = time.perf_counter()
        llm = self.llm
        pending_skill_prompts = self._deduplicate_pending_skill_prompts(state.get("pending_skill_prompts") or [])
        llm_messages = self._inject_pending_skill_prompts(state["messages"], pending_skill_prompts)
        try:
            from internal.core.agent.adapters.hermes.midturn_redirect import (
                consume_request_redirect,
            )

            redirect_message = consume_request_redirect(str(state["task_id"]))
            if redirect_message:
                llm_messages = list(llm_messages) + [
                    HumanMessage(content=redirect_message)
                ]
                self.agent_queue_manager.publish(
                    state["task_id"],
                    AgentThought(
                        id=uuid.uuid4(),
                        task_id=state["task_id"],
                        event=QueueEvent.AGENT_ACTION.value,
                        observation=f"已收到执行中纠正，将按新指令重新规划：{redirect_message}",
                        latency=0,
                    ),
                )
        except Exception:
            logger.exception("注入 mid-turn redirect 失败")

        # 3.检测大语言模型实例是否有bind_tools方法，如果没有则不绑定，如果有还需要检测tools是否为空，不为空则绑定
        if (
            ModelFeature.TOOL_CALL.value in (getattr(llm, "features", None) or [])
            and hasattr(llm, "bind_tools")
            and callable(getattr(llm, "bind_tools"))
            and len(self.agent_config.tools) > 0
        ):
            llm = llm.bind_tools(self.agent_config.tools)

        # 4.流式调用LLM输出对应内容
        gathered = None
        buffered_text_chunks: list[str] = []
        saw_tool_calls = False
        try:
            async for chunk in llm.astream(llm_messages):
                if chunk is None:  # 跳过无效 chunk
                    continue
                if gathered is None:
                    gathered = chunk
                else:
                    gathered += chunk
                    if gathered is None:  # 防止部分chunk合并实现返回None
                        gathered = chunk

                if getattr(chunk, "tool_calls", None):
                    saw_tool_calls = True

                content = self._normalize_chunk_content(getattr(chunk, "content", ""))
                if content:
                    reviewed = self._apply_output_review(content)
                    buffered_text_chunks.append(reviewed)
                    # 实时推送流式 token，让前端能看到 LLM 正在逐字输出
                    # 前端 chat-stream.ts 的 agentMessage 处理是 message.answer += answerChunk
                    self.agent_queue_manager.publish(state["task_id"], AgentThought(
                        id=id,
                        task_id=state["task_id"],
                        event=QueueEvent.AGENT_MESSAGE.value,
                        thought=reviewed,
                        message=messages_to_dict(state["messages"]),
                        answer=reviewed,
                        latency=0,
                    ))
        except Exception as e:
            logging.exception(f"LLM节点发生错误, 错误信息: {str(e)}")
            self.agent_queue_manager.publish_failure(
                state["task_id"],
                e,
                context="LLM节点发生错误",
            )
            raise

        if gathered is None:
            if pending_skill_prompts:
                logger.info(
                    "技能 prompt 租约已回收: lease_ids=%s",
                    [
                        str(item.get("lease_id") or item.get("skill_id") or item.get("source_key") or "")
                        for item in pending_skill_prompts
                        if isinstance(item, dict)
                    ],
                )
            return {
                "messages": [AIMessage(content="")],
                "iteration_count": state["iteration_count"] + 1,
                "pending_skill_prompts": [],
            }

        # 8.计算LLM的输入+输出的token总数
        input_token_count, output_token_count, total_token_count, total_price, unit, input_price, output_price = (
            self._calculate_usage(state, gathered, messages=llm_messages)
        )

        # 11.如果类型为推理则添加智能体推理事件
        final_tool_calls = getattr(gathered, "tool_calls", []) or []
        # 某些流式实现会先在中间 chunk 暴露 tool_calls，再在最终聚合对象里补齐。
        if saw_tool_calls or final_tool_calls:
            self.agent_queue_manager.publish(state["task_id"], AgentThought(
                id=id,
                task_id=state["task_id"],
                event=QueueEvent.AGENT_THOUGHT.value,
                thought=json.dumps(final_tool_calls, ensure_ascii=False, default=str),
                # 消息相关字段
                message=messages_to_dict(state["messages"]),
                message_token_count=input_token_count,  # 消息花费的token数
                message_unit_price=input_price,  # 单价
                message_price_unit=unit,  # 价格单位
                # 答案相关字段
                answer="",
                answer_token_count=output_token_count,
                answer_unit_price=output_price,
                answer_price_unit=unit,
                # Agent推理相关字段
                total_token_count=total_token_count,
                total_price=total_price,
                latency=(time.perf_counter() - start_at),
            ))
            return {
                "messages": [gathered],
                "iteration_count": state["iteration_count"] + 1,
                "pending_skill_prompts": [],
            }

        final_content = self._finalize_llm_output(state, "".join(buffered_text_chunks))
        final_content = self._postprocess_llm_output(state, final_content)

        if buffered_text_chunks:
            # 流式 chunk 已通过上面的循环实时推送，这里只发一条空 answer 的 AGENT_MESSAGE
            # 用于 token 统计和触发 AGENT_END（避免前端重复累加完整 answer）
            if pending_skill_prompts:
                logger.info(
                    "技能 prompt 租约已回收: lease_ids=%s",
                    [
                        str(item.get("lease_id") or item.get("skill_id") or item.get("source_key") or "")
                        for item in pending_skill_prompts
                        if isinstance(item, dict)
                    ],
                )
            self.agent_queue_manager.publish(state["task_id"], AgentThought(
                id=id,
                task_id=state["task_id"],
                event=QueueEvent.AGENT_MESSAGE.value,
                thought="",
                # 消息相关字段
                message=messages_to_dict(state["messages"]),
                message_token_count=input_token_count,  # 消息花费的token数
                message_unit_price=input_price,  # 单价
                message_price_unit=unit,  # 价格单位
                # 答案相关字段
                answer="",
                answer_token_count=output_token_count,
                answer_unit_price=output_price,
                answer_price_unit=unit,
                # Agent推理相关字段
                total_token_count=total_token_count,
                total_price=total_price,
                latency=(time.perf_counter() - start_at),
            ))
            self.agent_queue_manager.publish(state["task_id"], AgentThought(
                id=uuid.uuid4(),
                task_id=state["task_id"],
                event=QueueEvent.AGENT_END.value,
            ))
        else:
            # 无流式 chunk（例如 LLM 返回空内容或仅 tool_calls 已处理），发完整 answer 兜底
            self.agent_queue_manager.publish(state["task_id"], AgentThought(
                id=id,
                task_id=state["task_id"],
                event=QueueEvent.AGENT_MESSAGE.value,
                thought=final_content,
                message=messages_to_dict(state["messages"]),
                answer=final_content,
                latency=(time.perf_counter() - start_at),
            ))

        return {
            "messages": [AIMessage(content=final_content)],
            "iteration_count": state["iteration_count"] + 1,
            "pending_skill_prompts": [],
        }

    def _finalize_llm_output(self, state: AgentState, content: str) -> str:
        """把最终输出收口成用户可见文本。"""
        return self._sanitize_sandbox_artifact_text(self._apply_output_review(content))

    def _postprocess_llm_output(self, state: AgentState, content: str) -> str:
        """给最终输出留一个可覆写的后处理钩子。"""
        return content

    def _tools_node(self, state: AgentState) -> AgentState:
        """工具执行节点"""
        # 1.将工具列表转换成字典，便于调用指定的工具
        tool_policy = getattr(self.agent_config, "tool_policy", None) or ToolPolicy()
        tools_by_name = {tool.name: tool for tool in self.agent_config.tools}
        tools_by_alias = {}
        for tool in self.agent_config.tools:
            alias = self._normalize_tool_alias(tool.name)
            if alias and alias not in tools_by_alias:
                tools_by_alias[alias] = tool

        # 2.提取消息中的工具调用参数
        tool_calls = state["messages"][-1].tool_calls

        # 3.循环执行工具组装工具消息
        messages = []
        pending_skill_prompts = self._deduplicate_pending_skill_prompts(state.get("pending_skill_prompts") or [])
        pending_prompt_keys = {
            self._prompt_only_skill_identity_key(item)
            for item in pending_skill_prompts
            if isinstance(item, dict)
        }
        loaded_skill_prompt_keys = set(state.get("loaded_skill_prompt_keys") or [])
        authorized_tools = list(state.get("authorized_tools") or [])
        for tool_call in tool_calls:
            # 4.创建智能体动作事件id并记录开始时间
            id = uuid.uuid4()
            start_at = time.perf_counter()
            confirmation_id = ""

            try:
                # 5.获取工具并调用工具
                tool = self._resolve_tool(tool_call["name"], tools_by_name, tools_by_alias)
                if tool is None:
                    raise LookupError(self._build_tool_not_found_result(tool_call["name"], tools_by_name))

                if tool_policy.is_dangerous_tool(tool_call["name"]):
                    tool_result = "危险工具禁止自动调用，请联系管理员处理"
                    self.agent_queue_manager.publish(state["task_id"], AgentThought(
                        id=id,
                        task_id=state["task_id"],
                        event=QueueEvent.AGENT_ACTION.value,
                        observation=tool_result,
                        tool=tool_call["name"],
                        tool_input=tool_call["args"],
                        latency=(time.perf_counter() - start_at),
                    ))
                    messages.append(ToolMessage(
                        tool_call_id=tool_call["id"],
                        content=tool_result,
                        name=tool_call["name"],
                    ))
                    continue

                if tool_policy.is_high_risk_tool(tool_call["name"]):
                    account_id = (
                        getattr(self.agent_config, "user_id", None)
                        or getattr(state, "user_id", None)
                        or getattr(state, "account_id", None)
                    )
                    host_workflow_tool = tool_call["name"] in {
                        "run_os_task",
                        "os_file_task",
                    }
                    already_authorized = (
                        tool_call["name"] in authorized_tools
                        or (
                            host_workflow_tool
                            and self._is_tool_authorized(account_id, tool_call["name"])
                        )
                    )
                    if not already_authorized and self._smart_approval_allows(
                        tool_call["name"],
                        tool_input=tool_call.get("args") or {},
                    ):
                        authorized_tools.append(tool_call["name"])
                        already_authorized = True
                    if not already_authorized:
                        confirmation = self._create_tool_confirmation(
                            state,
                            tool_call,
                            tool_policy,
                        )
                        if confirmation is None:
                            # 确认机制创建失败时阻止执行，不允许高风险工具绕过确认直接执行
                            tool_result = f"高风险工具 {tool_call['name']} 确认机制不可用，已阻止执行"
                            self.agent_queue_manager.publish(state["task_id"], AgentThought(
                                id=id,
                                task_id=state["task_id"],
                                event=QueueEvent.AGENT_ACTION.value,
                                observation=tool_result,
                                tool=tool_call["name"],
                                tool_input=tool_call["args"],
                                latency=(time.perf_counter() - start_at),
                            ))
                            messages.append(ToolMessage(
                                tool_call_id=tool_call["id"],
                                content=tool_result,
                                name=tool_call["name"],
                            ))
                            continue
                        confirmation_id = str(confirmation.get("id", ""))
                        summary = self._build_confirmation_summary(
                            tool_call["name"],
                            tool_call["args"],
                        )
                        self.agent_queue_manager.publish(state["task_id"], AgentThought(
                            id=id,
                            task_id=state["task_id"],
                            event=QueueEvent.TOOL_CONFIRMATION_REQUIRED.value,
                            thought=(
                                f"高风险工具 {tool_call['name']} 需要用户授权后才能执行。"
                            ),
                            observation=(
                                f"高风险工具 {tool_call['name']} 需要用户授权后才能执行。"
                                f"确认ID: {confirmation_id}。"
                                "授权后 Agent 才会继续执行，并会在执行前给出可读计划。"
                            ),
                            tool=tool_call["name"],
                            tool_input=tool_call["args"],
                            confirmation_id=confirmation_id,
                            confirmation_status="pending",
                            execution_summary=summary,
                            latency=(time.perf_counter() - start_at),
                        ))
                        decision = self._wait_for_confirmation(
                            confirmation_id,
                            account_id=account_id,
                        )
                        if decision == "cancelled":
                            tool_result = (
                                f"高风险工具 {tool_call['name']} 已被用户取消，未执行。"
                            )
                            self.agent_queue_manager.publish(state["task_id"], AgentThought(
                                id=id,
                                task_id=state["task_id"],
                                event=QueueEvent.TOOL_CONFIRMATION_REQUIRED.value,
                                thought="用户已取消工具执行。",
                                observation=tool_result,
                                tool=tool_call["name"],
                                tool_input=tool_call["args"],
                                confirmation_id=confirmation_id,
                                confirmation_status="cancelled",
                                execution_summary="用户已取消执行",
                                latency=(time.perf_counter() - start_at),
                            ))
                            messages.append(ToolMessage(
                                tool_call_id=tool_call["id"],
                                content=tool_result,
                                name=tool_call["name"],
                            ))
                            continue
                        if decision == "timeout":
                            self._update_confirmation_summary(
                                confirmation_id,
                                "等待用户确认超时，已按安全默认取消执行",
                                status="cancelled",
                            )
                            tool_result = (
                                f"高风险工具 {tool_call['name']} 等待用户确认超时，"
                                "已按安全默认取消执行。"
                            )
                            self.agent_queue_manager.publish(state["task_id"], AgentThought(
                                id=id,
                                task_id=state["task_id"],
                                event=QueueEvent.TOOL_CONFIRMATION_REQUIRED.value,
                                thought="等待用户确认超时，已按安全默认取消。",
                                observation=tool_result,
                                tool=tool_call["name"],
                                tool_input=tool_call["args"],
                                confirmation_id=confirmation_id,
                                confirmation_status="cancelled",
                                execution_summary="等待用户确认超时，已按安全默认取消执行",
                                latency=(time.perf_counter() - start_at),
                            ))
                            messages.append(ToolMessage(
                                tool_call_id=tool_call["id"],
                                content=tool_result,
                                name=tool_call["name"],
                            ))
                            continue
                        if decision.startswith("redirect:"):
                            # mid-turn redirect：不执行原动作，把纠正消息注入当前轮。
                            redirect_message = decision[len("redirect:"):]
                            state["messages"] = list(state.get("messages") or []) + [
                                HumanMessage(content=redirect_message)
                            ]
                            tool_result = (
                                f"已收到用户执行中纠正，取消本次 {tool_call['name']} 执行，"
                                "将按新指令重新规划。"
                            )
                            self.agent_queue_manager.publish(state["task_id"], AgentThought(
                                id=id,
                                task_id=state["task_id"],
                                event=QueueEvent.AGENT_ACTION.value,
                                observation=tool_result,
                                tool=tool_call["name"],
                                tool_input=tool_call["args"],
                                confirmation_id=confirmation_id,
                                confirmation_status="cancelled",
                                execution_summary=redirect_message,
                                latency=(time.perf_counter() - start_at),
                            ))
                            messages.append(ToolMessage(
                                tool_call_id=tool_call["id"],
                                content=tool_result,
                                name=tool_call["name"],
                            ))
                            continue
                        authorized_tools.append(tool_call["name"])
                        if host_workflow_tool:
                            # 授权后先进入只读扫描，由 Agent 给出清理方案并反问用户，
                            # 不在授权这一步直接执行删除/清理。
                            tool_call["args"] = dict(tool_call.get("args") or {})
                            tool_call["args"]["mode"] = "preview"

                tool_result = tool.invoke(tool_call["args"])
            except LookupError as e:
                tool_result = str(e)
            except Exception as e:
                if tool_policy.is_hard_fail_tool(tool_call["name"]):
                    self.agent_queue_manager.publish_failure(
                        state["task_id"],
                        e,
                        context=f"{tool_call['name']}执行失败",
                    )
                    raise
                # 6.添加错误工具信息
                tool_result = f"工具执行出错: {str(e)}"

            public_tool_result = tool_result
            prompt_lease = None
            if self._is_prompt_only_skill_loader_tool(tool_call["name"]):
                public_tool_result, prompt_lease = self._build_prompt_only_skill_loader_result(tool_result)
                if prompt_lease:
                    prompt_key = self._prompt_only_skill_identity_key(prompt_lease)
                    if (
                        prompt_key
                        and prompt_key not in pending_prompt_keys
                        and prompt_key not in loaded_skill_prompt_keys
                    ):
                        pending_skill_prompts.append(prompt_lease)
                        pending_prompt_keys.add(prompt_key)
                        loaded_skill_prompt_keys.add(prompt_key)

            serialized_tool_result = (
                public_tool_result
                if isinstance(public_tool_result, str)
                else json.dumps(public_tool_result, ensure_ascii=False, default=str)
            )
            user_visible_tool_result = self._build_user_visible_tool_result(
                tool_call["name"],
                serialized_tool_result,
            )

            if tool_call["name"] == "run_os_task" and confirmation_id:
                try:
                    result_payload = json.loads(serialized_tool_result)
                except Exception:
                    result_payload = {}
                summary = str(
                    result_payload.get("summary") or serialized_tool_result or "执行完成"
                )
                self._update_confirmation_summary(confirmation_id, summary)

            # 7.将工具消息添加到消息列表中
            messages.append(ToolMessage(
                tool_call_id=tool_call["id"],
                content=serialized_tool_result,
                name=tool_call["name"],
            ))

            # 7.判断执行工具的名字，提交不同事件，涵盖智能体动作以及知识库检索
            # 注意：LLM 实际输出的工具名可能是 search_knowledge_base（检索工具注册名），
            # 也可能是 dataset_retrieval / recall_dataset 等历史别名，统一归一到知识库检索事件
            event = (
                QueueEvent.DATASET_RETRIEVAL.value
                if tool_call["name"] in {
                    tool_policy.dataset_retrieval_tool_name,
                    "search_knowledge_base",
                    "recall_dataset",
                }
                else QueueEvent.AGENT_ACTION.value
            )
            self.agent_queue_manager.publish(state["task_id"], AgentThought(
                id=id,
                task_id=state["task_id"],
                event=event,
                observation=user_visible_tool_result,
                tool=tool_call["name"],
                tool_input=tool_call["args"],
                confirmation_id=confirmation_id or "",
                latency=(time.perf_counter() - start_at),
            ))

        try:
            from internal.core.context_compression import compress_langchain_tool_messages

            compress_langchain_tool_messages(messages, protect_recent=0)
        except Exception:
            logger.exception("context compression skipped for agent tool messages")

        return {
            "messages": messages,
            "pending_skill_prompts": pending_skill_prompts,
            "authorized_tools": authorized_tools,
            "loaded_skill_prompt_keys": list(loaded_skill_prompt_keys),
        }

    @staticmethod
    def _smart_approval_allows(
        tool_name: str,
        tool_input: dict[str, Any] | None = None,
    ) -> bool:
        """命中管理员智能审批策略时自动放行高风险工具（daemon 危险命令除外）。"""
        try:
            from app.http.app import injector
            from internal.service.smart_approval_policy_service import (
                SmartApprovalPolicyService,
            )

            return injector.get(SmartApprovalPolicyService).should_auto_approve(
                tool_name,
                tool_input=tool_input,
            )
        except Exception:
            logger.exception("智能审批策略判断失败，按需确认处理")
            return False

    @staticmethod
    def _build_confirmation_summary(tool_name: str, tool_input: dict[str, Any]) -> str:
        """生成用户可见的授权摘要，避免把原始 Markdown/JSON 直接铺到卡片上。"""
        if tool_name == "run_os_task":
            task = str((tool_input or {}).get("task", "") or "").strip()
            if task:
                return (
                    f"请求授权在宿主机执行系统自动化任务：{task}。"
                    "授权后我会先做只读扫描并整理方案，不会直接删除或修改文件。"
                )
            return (
                "请求授权在宿主机执行系统自动化任务。"
                "授权后我会先做只读扫描并整理方案，不会直接删除或修改文件。"
            )
        if tool_name == "os_file_task":
            operation = str((tool_input or {}).get("op") or "patch")
            if operation == "read":
                return "请求授权在宿主机安全目录内读取文件，仅返回文件内容。"
            return (
                "请求授权在宿主机安全目录内应用 V4A 补丁修改文件。"
                "授权后我会先校验补丁并展示影响，不会在未确认前直接修改文件。"
            )
        return f"请求授权调用高风险工具 {tool_name}，授权后 Agent 才会继续执行。"

    @staticmethod
    def _build_user_visible_tool_result(tool_name: str, serialized_result: str) -> str:
        """工具结果只展示给用户可读摘要，避免把 approval_token/原始命令泄露到思考区。"""
        if tool_name not in {"run_os_task", "os_file_task"}:
            return serialized_result
        try:
            result = json.loads(serialized_result)
        except Exception:
            return serialized_result
        if not isinstance(result, dict):
            return serialized_result
        summary = str(result.get("summary", "") or "")
        if not summary:
            return json.dumps(
                {"ok": bool(result.get("ok")), "error": result.get("error", "")},
                ensure_ascii=False,
            )
        return FunctionCallAgent._strip_markdown_artifacts(summary)

    @staticmethod
    def _strip_markdown_artifacts(text: str) -> str:
        """把工具结果里的 Markdown 装饰符去掉，避免用户思考区出现 **/```/- 等噪音。"""
        lines = []
        for raw_line in str(text or "").splitlines():
            line = raw_line.strip()
            if not line:
                continue
            line = re.sub(r"^#{1,6}\s*", "", line)
            line = re.sub(r"^[-*+]\s+", "", line)
            line = re.sub(r"^\d+\.\s+", "", line)
            line = line.replace("**", "").replace("`", "")
            lines.append(line)
        return "\n".join(lines)

    def _is_tool_authorized(
        self,
        account_id,
        tool_name: str,
        *,
        max_age_seconds: int = 1800,
    ) -> bool:
        """检查当前账号近期是否已确认过该高风险工具授权。"""
        if not account_id:
            return False
        try:
            from datetime import UTC, datetime

            from sqlalchemy import desc

            from internal.extension.database_extension import db
            from internal.model.tool_confirmation import ToolConfirmation

            with db.sync_auto_commit() as session:
                expire_all = getattr(session, "expire_all", None)
                if callable(expire_all):
                    expire_all()
                confirmation = (
                    session.query(ToolConfirmation)
                    .filter_by(
                        owner_account_id=account_id,
                        tool_name=tool_name,
                        status="confirmed",
                    )
                    .order_by(desc(ToolConfirmation.updated_at))
                    .first()
                )
                if confirmation is None:
                    return False
                updated_at = confirmation.updated_at or confirmation.created_at
                if updated_at is None:
                    return True
                now = datetime.now(UTC).replace(tzinfo=None)
                age = now - updated_at
                return age.total_seconds() <= max_age_seconds
        except Exception:
            logger.warning("检查工具授权状态失败: tool=%s", tool_name, exc_info=True)
            return False

    def _create_tool_confirmation(
        self,
        state: AgentState,
        tool_call: dict[str, Any],
        tool_policy: ToolPolicy,
    ) -> dict[str, Any] | None:
        try:
            from internal.extension.database_extension import db
            from internal.model.tool_confirmation import ToolConfirmation

            tool_name = tool_call.get("name", "")
            is_sensitive = tool_name in {"send_email", "send_sms"}
            risk_level = "sensitive" if is_sensitive else "high"
            account_id = (
                getattr(self.agent_config, "user_id", None)
                or getattr(state, "user_id", None)
                or getattr(state, "account_id", None)
            )
            tool_input = dict(tool_call.get("args", {}) or {})
            with db.sync_auto_commit() as session:
                confirmation = ToolConfirmation(
                    owner_account_id=account_id,
                    tool_name=tool_name,
                    risk_level=risk_level,
                    tool_input=tool_input,
                    status="pending",
                    spent_credits=0,
                    reason=f"Agent 调用高风险工具 {tool_name}，等待用户确认",
                )
                session.add(confirmation)
            return {"id": str(confirmation.id), "status": confirmation.status}
        except Exception:
            logger.exception("创建高风险工具确认记录失败: tool=%s", tool_call.get("name", ""))
            return None

    def _wait_for_confirmation(
        self,
        confirmation_id: str,
        *,
        account_id=None,
        timeout_seconds: float | None = None,
        poll_interval: float | None = None,
    ) -> str:
        """挂起等待用户在确认卡片上选择，超时按安全默认取消。

        pending=等待中，confirmed=用户已确认，cancelled=用户已取消，
        timeout=等待超时（调用方按安全默认处理）。
        """
        from internal.extension.database_extension import db
        from internal.model.tool_confirmation import ToolConfirmation

        deadline = time.monotonic() + (
            timeout_seconds
            if timeout_seconds is not None
            else self._CONFIRMATION_WAIT_SECONDS
        )
        interval = (
            poll_interval
            if poll_interval is not None
            else self._CONFIRMATION_POLL_INTERVAL_SECONDS
        )
        while True:
            status = "pending"
            try:
                with db.sync_auto_commit() as session:
                    # 会话配置了 expire_on_commit=False，同一 scoped session 复用时会
                    # 命中旧身份映射；强制过期后再查询，才能读到用户刚提交的确认状态。
                    expire_all = getattr(session, "expire_all", None)
                    if callable(expire_all):
                        expire_all()
                    query = session.query(ToolConfirmation).filter_by(id=confirmation_id)
                    if account_id is not None:
                        query = query.filter_by(owner_account_id=account_id)
                    confirmation = query.one_or_none()
                    if confirmation is not None:
                        status = str(confirmation.status or "pending")
            except Exception:
                logger.warning("等待工具确认时查询记录失败", exc_info=True)

            if status != "pending":
                return status
            redirect_message = _consume_redirect(confirmation_id)
            if redirect_message:
                self._update_confirmation_summary(
                    confirmation_id,
                    "用户发送了执行中纠正，已取消本次工具执行并重新规划",
                    status="cancelled",
                )
                return _build_redirect_decision(redirect_message)
            if time.monotonic() >= deadline:
                return "timeout"
            time.sleep(interval)

    def _update_confirmation_summary(
        self,
        confirmation_id: str,
        summary: str,
        *,
        status: str = "",
    ) -> None:
        """把执行结果/超时状态写回确认记录，供轮询与审计使用。"""
        try:
            from internal.extension.database_extension import db
            from internal.model.tool_confirmation import ToolConfirmation

            with db.sync_auto_commit() as session:
                confirmation = (
                    session.query(ToolConfirmation)
                    .filter_by(id=confirmation_id)
                    .one_or_none()
                )
                if confirmation is None:
                    return
                if summary:
                    confirmation.execution_summary = summary
                if status:
                    confirmation.status = status
        except Exception:
            logger.warning("回写工具确认结果失败: confirmation=%s", confirmation_id, exc_info=True)

    @staticmethod
    def _build_tool_not_found_result(tool_call_name: str, tools_by_name: dict[str, Any]) -> str:
        """把可用工具名回灌给模型，促使其基于真实列表重新选择。"""
        available_tool_names = list(tools_by_name.keys())
        preview_limit = 30
        preview = available_tool_names[:preview_limit]
        suffix = ""
        if len(available_tool_names) > preview_limit:
            suffix = f" 等共 {len(available_tool_names)} 个工具"
        available_text = ", ".join(preview) if preview else "无"
        return (
            f"工具未找到: {tool_call_name}。"
            f"请从当前可用工具列表中重新选择并调用: {available_text}{suffix}。"
        )

    def _resolve_tool(
        self,
        tool_call_name: str,
        tools_by_name: dict[str, Any],
        tools_by_alias: dict[str, Any],
    ) -> Any | None:
        """按精确名、别名顺序解析工具。"""
        tool_policy = getattr(self.agent_config, "tool_policy", None) or ToolPolicy()
        requested_name = tool_policy.resolve_tool_name(tool_call_name)

        candidates = (
            requested_name,
        )
        for candidate in candidates:
            if not candidate:
                continue
            tool = tools_by_name.get(candidate)
            if tool is not None:
                return tool

            tool = tools_by_alias.get(candidate)
            if tool is not None:
                return tool

        return None

    @staticmethod
    def _normalize_tool_alias(tool_name: str | None) -> str:
        if not tool_name:
            return ""

        normalized = str(tool_name).strip()
        if not normalized:
            return ""

        parts = normalized.split("__", 2)
        if len(parts) == 3:
            return parts[2]
        return normalized.replace("-", "_").replace(" ", "_")

    @classmethod
    def _is_prompt_only_skill_loader_tool(cls, tool_name: str | None) -> bool:
        return str(tool_name or "").startswith(cls._PROMPT_ONLY_SKILL_LOADER_PREFIX)

    @staticmethod
    def _build_prompt_only_skill_loader_result(tool_result: Any) -> tuple[Any, dict[str, Any] | None]:
        """把 prompt-only 技能全文加载结果拆成公开结果与待注入全文。"""
        if not isinstance(tool_result, dict):
            return tool_result, None

        prompt_text = str(tool_result.get("prompt") or tool_result.get("readme") or "").strip()
        if not prompt_text:
            return tool_result, None

        public_result = {
            "skill_id": str(tool_result.get("skill_id") or "").strip(),
            "source_key": str(tool_result.get("source_key") or "").strip(),
            "name": str(tool_result.get("name") or "").strip(),
            "label": str(tool_result.get("label") or "").strip(),
            "description": str(tool_result.get("description") or "").strip(),
            "category": str(tool_result.get("category") or "").strip(),
            "executor_type": str(tool_result.get("executor_type") or "").strip(),
            "prompt_length": len(prompt_text),
            "lease_id": str(tool_result.get("lease_id") or "").strip(),
            "ephemeral": True,
            "loaded": True,
        }
        pending_skill_prompt = {
            "lease_id": public_result["lease_id"],
            "skill_id": public_result["skill_id"],
            "source_key": public_result["source_key"],
            "name": public_result["name"],
            "label": public_result["label"],
            "description": public_result["description"],
            "category": public_result["category"],
            "executor_type": public_result["executor_type"],
            "prompt": prompt_text,
        }
        return public_result, pending_skill_prompt

    @staticmethod
    def _prompt_only_skill_identity_key(skill_payload: dict[str, Any]) -> str:
        return str(
            skill_payload.get("skill_id")
            or skill_payload.get("source_key")
            or skill_payload.get("lease_id")
            or ""
        ).strip()

    @classmethod
    def _deduplicate_pending_skill_prompts(
        cls,
        pending_skill_prompts: list[dict[str, Any]] | None,
    ) -> list[dict[str, Any]]:
        if not isinstance(pending_skill_prompts, list):
            return []

        deduplicated: list[dict[str, Any]] = []
        seen_keys: set[str] = set()
        for prompt_item in pending_skill_prompts:
            if not isinstance(prompt_item, dict):
                continue
            prompt_key = cls._prompt_only_skill_identity_key(prompt_item)
            if not prompt_key or prompt_key in seen_keys:
                continue
            prompt_text = str(prompt_item.get("prompt") or "").strip()
            if not prompt_text:
                continue
            deduplicated.append(prompt_item)
            seen_keys.add(prompt_key)
        return deduplicated

    @classmethod
    def _build_pending_skill_prompt_messages(
        cls,
        pending_skill_prompts: list[dict[str, Any]] | None,
    ) -> list[SystemMessage]:
        """把待注入的 prompt-only 技能全文合并成仅供当前轮次使用的系统消息。"""
        deduplicated = cls._deduplicate_pending_skill_prompts(pending_skill_prompts)
        if not deduplicated:
            return []

        from internal.service.system_prompt_library_service import SystemPromptLibraryService
        wrapper = SystemPromptLibraryService().get_prompt_or_default(
            "prompt_only_skill_wrapper"
        )
        sections: list[str] = [wrapper, ""]
        for prompt_item in deduplicated:
            title = str(prompt_item.get("label") or prompt_item.get("name") or prompt_item.get("source_key") or "Skill").strip()
            source_key = str(prompt_item.get("source_key") or "").strip()
            prompt_text = str(prompt_item.get("prompt") or "").strip()
            if not prompt_text:
                continue
            header = f"### {title}"
            if source_key:
                header += f" (`{source_key}`)"
            sections.extend([header, prompt_text, ""])

        content = "\n".join(sections).strip()
        if not content:
            return []
        return [SystemMessage(content=content)]

    @classmethod
    def _inject_pending_skill_prompts(
        cls,
        messages: list[Any],
        pending_skill_prompts: list[dict[str, Any]] | None,
    ) -> list[Any]:
        if not isinstance(messages, list):
            return []

        injected_messages = list(messages)
        prompt_messages = cls._build_pending_skill_prompt_messages(pending_skill_prompts)
        if not prompt_messages:
            return injected_messages

        insert_at = 0
        while insert_at < len(injected_messages) and isinstance(injected_messages[insert_at], SystemMessage):
            insert_at += 1

        for index, prompt_message in enumerate(prompt_messages):
            injected_messages.insert(insert_at + index, prompt_message)

        return injected_messages

    @classmethod
    def _tools_condition(cls, state: AgentState) -> Literal["tools", "__end__"]:
        """检测下一个节点是执行tools节点，还是直接结束"""
        # 1.提取状态中的最后一条消息(AI消息)
        messages = state["messages"]
        ai_message = messages[-1]

        # 2.检测是否存在tools_calls这个参数，如果存在则执行tools节点，否则结束
        if hasattr(ai_message, "tool_calls") and len(ai_message.tool_calls) > 0:
            return "tools"

        return END

    @classmethod
    def _preset_operation_condition(cls, state: AgentState) -> Literal["long_term_memory_recall", "__end__"]:
        """预设操作条件边，用于判断是否触发预设响应"""
        # 1.提取状态的最后一条消息
        message = state["messages"][-1]

        # 2.判断消息的类型，如果是AI消息则说明触发了审核机制，直接结束
        if message.type == "ai":
            return END

        return "long_term_memory_recall"

    def _calculate_usage(
        self,
        state: AgentState,
        gathered,
        *,
        messages: list[Any] | None = None,
    ) -> tuple[int, int, int, float, float, float, float]:
        """计算输入输出token以及价格"""
        encoding = tiktoken.get_encoding("cl100k_base")
        input_token_count = len(encoding.encode(normalize_usage_text(state["messages"])))
        output_token_count = len(encoding.encode(normalize_usage_text(gathered)))
        input_price, output_price, unit = self.llm.get_pricing()
        total_token_count = input_token_count + output_token_count
        total_price = (input_token_count * input_price + output_token_count * output_price) * unit
        return input_token_count, output_token_count, total_token_count, total_price, unit, input_price, output_price

    def _apply_output_review(self, content: str) -> str:
        """按输出审核规则处理文本"""
        review_config = self.agent_config.review_config
        if review_config["enable"] and review_config["outputs_config"]["enable"]:
            for keyword in review_config["keywords"]:
                content = re.sub(re.escape(keyword), "**", content, flags=re.IGNORECASE)
        return content

    @classmethod
    def _normalize_chunk_content(cls, content) -> str:
        """将chunk content规范化为文本"""
        if isinstance(content, str):
            return content
        return ""
