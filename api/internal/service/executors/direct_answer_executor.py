import json
import logging
import time
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_core.utils.function_calling import convert_to_openai_tool
from internal.core.agent.entities.queue_entity import QueueEvent
from internal.core.agent.usage_utils import charge_for_feature
from internal.service.language_model_service import LanguageModelService
from internal.service.memory.llm_activity_probe import LLMActivityProbe
from internal.service.system_prompt_library_service import SystemPromptLibraryService

logger = logging.getLogger(__name__)

# 知识库检索工具名（与 tool_policy / retrieval_service 保持一致）
KNOWLEDGE_RETRIEVAL_TOOL_NAMES = {"search_knowledge_base", "dataset_retrieval", "recall_dataset"}


class DirectAnswerExecutor:
    """轻量直接回答执行器，不经 Agent 循环，直接调 LLM。

    同时实现两种调用契约：
    - ``stream``: 面向 SSE 的流式生成（保留向后兼容）
    - ``execute``: 面向 ``ExecutionCoordinatorService`` 的 ``TaskExecutor`` 协议，
      返回 dict 结果，使 direct_answer 模式也能纳入协调器统一编排。

    v2 增强（对应「系统知识库生效 + 硬编码提示词可管理」需求）：
    - 支持注入 ``tools``（知识库检索等），直接回答阶段也能检索系统知识库；
    - system prompt 不再硬编码，改为从系统提示词库（SystemPromptLibraryService）
      读取可管理版本，未配置时回退到内置默认文本。
    """

    # 工具调用最大轮数（首轮可能出工具，随后带工具结果再请求，最多再请求 2 次）
    MAX_TOOL_ROUNDS = 2

    def __init__(self, language_model_service=None, credit_service=None, account_id=None, llm=None, tools=None):
        self.language_model_service = language_model_service
        self.credit_service = credit_service
        self.account_id = account_id
        # 外层传入的已解析 LLM 实例（优先使用，避免独立解析到不可用模型）
        self._injected_llm = llm
        # 知识库检索等工具（BaseTool 列表），为空时行为与旧版一致
        self.tools = list(tools or [])
        # 流式调用后填充，供外层做计费和持久化
        self.last_answer = ""
        self.last_token_usage = None
        # 流式期间收集的 AgentThought（推理链等），供外层持久化，避免 reload 时思考内容丢失
        self.collected_thoughts: list[dict] = []

    def _resolve_system_prompt(self) -> str:
        """从系统提示词库读取可管理的 direct_answer system prompt，未配置时回退 YAML 内置默认。"""
        try:
            return SystemPromptLibraryService().get_prompt_or_default("direct_answer_system_prompt")
        except Exception:
            logger.debug("读取系统提示词失败，回退 YAML 默认", exc_info=True)
            # YAML 兜底（数据文件，非代码硬编码）
            return SystemPromptLibraryService().load_yaml_prompts().get(
                "direct_answer_system_prompt", ""
            )

    def _build_tool_schemas(self):
        """把 langchain BaseTool 列表转换为 OpenAI 工具 schema；失败项跳过。"""
        schemas = []
        for tool in self.tools:
            try:
                schema = convert_to_openai_tool(tool)
                if schema:
                    schemas.append(schema)
            except Exception:
                logger.debug("工具转 OpenAI schema 失败 name=%s", getattr(tool, "name", ""), exc_info=True)
        return schemas

    def _find_tool(self, tool_name: str):
        for tool in self.tools:
            if getattr(tool, "name", "") == tool_name:
                return tool
        return None

    def _stream_round(self, native_client, model_name, messages, tool_schemas, answer_parts, reasoning_parts, _stream_started_at, message_id, conversation_id):
        """单轮流式请求：yield 推理/答案事件，返回 (tool_calls, final_usage)。

        tool_calls: list[dict]（id / name / arguments 累积完整）
        """
        tool_calls: list[dict] = []
        final_usage = None
        for chunk in LLMActivityProbe.monitor_stream(
            lambda: self._create_stream_request(native_client, model_name, messages, tool_schemas),
            feature_key="direct_answer",
        ):
            if chunk is None:
                continue
            choices = getattr(chunk, "choices", None) or []
            if not choices:
                continue
            delta = getattr(choices[0], "delta", None)
            if delta is not None:
                reasoning_content = getattr(delta, "reasoning_content", None) or ""
                if reasoning_content:
                    reasoning_parts.append(reasoning_content)
                    yield from self._emit_thought(message_id, conversation_id, reasoning_parts, round(time.monotonic() - _stream_started_at, 3))
                content = getattr(delta, "content", None) or ""
                if content:
                    answer_parts.append(content)
                    yield f"event: {QueueEvent.AGENT_MESSAGE.value}\ndata:{json.dumps({'answer': content, 'id': message_id, 'conversation_id': conversation_id, 'message_id': message_id}, ensure_ascii=False)}\n\n"
                delta_tool_calls = getattr(delta, "tool_calls", None)
                if delta_tool_calls:
                    for tc in delta_tool_calls:
                        idx = getattr(tc, "index", 0) or 0
                        while len(tool_calls) <= idx:
                            tool_calls.append({"id": "", "name": "", "arguments": ""})
                        tc_id = getattr(tc, "id", None)
                        if tc_id:
                            tool_calls[idx]["id"] = tc_id
                        fn = getattr(tc, "function", None)
                        if fn is not None:
                            name = getattr(fn, "name", None)
                            if name:
                                tool_calls[idx]["name"] = name
                            args = getattr(fn, "arguments", None)
                            if args:
                                tool_calls[idx]["arguments"] += args
            usage = getattr(choices[0], "usage", None)
            if usage:
                final_usage = usage
        return tool_calls, final_usage

    @staticmethod
    def _create_stream_request(native_client, model_name, messages, tool_schemas):
        kwargs = {
            "model": model_name,
            "messages": messages,
            "stream": True,
        }
        if tool_schemas:
            kwargs["tools"] = tool_schemas
        return native_client.create(**kwargs)

    def _execute_tool_calls(self, tool_calls, message_id, conversation_id):
        """执行工具调用并 yield 事件；返回追加到 messages 的 tool 结果消息列表。"""
        tool_messages = []
        for call in tool_calls:
            tool_name = call.get("name", "")
            call_id = call.get("id", "") or f"call_{int(time.time() * 1000)}"
            try:
                arguments = json.loads(call.get("arguments", "{}") or "{}")
            except Exception:
                arguments = {}
            tool = self._find_tool(tool_name)
            if tool is None:
                result = f"工具不存在: {tool_name}"
            else:
                try:
                    result = tool.invoke(arguments)
                    result = str(result or "")
                except Exception as e:
                    logger.warning("工具执行失败 name=%s", tool_name, exc_info=True)
                    result = f"工具执行失败: {e}"
            tool_messages.append({
                "role": "tool",
                "tool_call_id": call_id,
                "name": tool_name,
                "content": result,
            })
            event = (
                QueueEvent.DATASET_RETRIEVAL.value
                if tool_name in KNOWLEDGE_RETRIEVAL_TOOL_NAMES
                else QueueEvent.AGENT_ACTION.value
            )
            thought_payload = {
                "id": f"{message_id}:{tool_name}:{call_id}",
                "event": event,
                "thought": "",
                "observation": result,
                "tool": tool_name,
                "tool_input": arguments,
                "answer": "",
                "conversation_id": conversation_id,
                "message_id": message_id,
                "latency": 0,
                "total_token_count": 0,
            }
            yield f"event: {event}\ndata:{json.dumps(thought_payload, ensure_ascii=False)}\n\n"
            self._record_thought(thought_payload)
        return tool_messages

    def _record_thought(self, payload: dict) -> None:
        for idx, item in enumerate(self.collected_thoughts):
            if str(item.get("id", "")) == str(payload["id"]) and item.get("event") == payload.get("event"):
                self.collected_thoughts[idx] = payload
                return
        self.collected_thoughts.append(payload)

    def stream(self, query, history=None, conversation_id="", message_id=""):
        """真流式生成：逐 token yield AGENT_MESSAGE 事件 + 推理过程流式显示。

        使用 ChatOpenAI 底层原生 client 直接流式调用（绕过 langchain 的
        _convert_delta_to_message_chunk 转换，该转换会丢弃 reasoning_content 字段），
        从而：
        1. 推理过程（delta.reasoning_content）从 LLM 开始思考时即逐 chunk yield
           为 agent_thought SSE 事件，前端思考框实时滚动显示推理内容；
        2. 答案（delta.content）逐 chunk yield 为 agent_message SSE 事件。

        探针在 60s 无 chunk 产出时终止调用，防止死机。

        注意：本方法只负责 token 流（AGENT_THOUGHT/AGENT_MESSAGE）和错误（ERROR），
        计费、AGENT_END 等事件由外层 _stream_direct_answer 统一管理，
        避免重复事件。完整 answer 和 token_usage 通过实例属性 last_answer/
        last_token_usage 传递给外层。
        """
        answer_parts: list[str] = []
        reasoning_parts: list[str] = []
        final_usage = None
        _stream_started_at = time.monotonic()
        try:
            llm = self._resolve_llm()

            # 为支持推理的模型启用 reasoning 模式（reasoning_effort 参数）
            reasoning_llm = self._enable_reasoning(llm)

            # 取底层原生 client（openai.Completions），直接流式调用，
            # 保证 delta.reasoning_content 推理字段不被 langchain 转换层丢弃
            native_client = getattr(reasoning_llm, "client", None) or getattr(reasoning_llm, "openai_client", None)
            model_name = getattr(reasoning_llm, "model_name", None) or getattr(reasoning_llm, "model", None) or ""

            # system prompt 从系统提示词库读取（可管理），未配置时回退内置默认
            system_prompt = self._resolve_system_prompt()
            messages = (
                [{"role": "system", "content": system_prompt}]
                + (history or [])
                + [{"role": "user", "content": query}]
            )
            tool_schemas = self._build_tool_schemas()

            # 工具调用循环：首轮可出工具（知识库检索等），执行后带结果再请求，
            # 最多 MAX_TOOL_ROUNDS 轮工具执行，随后回合强制只出最终答案
            for round_index in range(self.MAX_TOOL_ROUNDS + 1):
                if native_client is not None:
                    tool_calls, round_usage = yield from self._stream_round(
                        native_client, model_name, messages, tool_schemas,
                        answer_parts, reasoning_parts, _stream_started_at,
                        message_id, conversation_id,
                    )
                else:
                    # 无原生 client 时回退 langchain stream（无法获得推理过程）
                    tool_calls, round_usage = yield from self._stream_round_langchain(
                        reasoning_llm, messages, tool_schemas,
                        answer_parts, reasoning_parts, _stream_started_at,
                        message_id, conversation_id,
                    )
                if round_usage:
                    final_usage = round_usage
                # 过滤掉无名称的残缺 tool_call；最后一轮不再执行工具
                executable_calls = [
                    c for c in tool_calls
                    if c.get("name") and (c.get("arguments") or c.get("id"))
                ]
                if not executable_calls or round_index >= self.MAX_TOOL_ROUNDS:
                    break
                # 执行工具：yield 事件，并把工具结果消息追加进对话
                tool_messages = yield from self._execute_tool_calls(
                    executable_calls, message_id, conversation_id,
                )
                messages.extend(tool_messages)

            # 流结束后填充实例属性，供外层计费和持久化
            if final_usage is not None:
                self.last_answer = "".join(answer_parts)
                if isinstance(final_usage, dict):
                    # 原生路径：usage 记录在最后一个 chunk 的 usage 字段
                    self.last_token_usage = self._extract_token_usage_from_dict(final_usage)
                else:
                    # langchain 回退路径：chunk 对象中提取 token_usage
                    self.last_token_usage = self._extract_token_usage(final_usage)
            else:
                self.last_answer = "".join(answer_parts)
                self.last_token_usage = None
        except Exception as e:
            logger.exception("DirectAnswerExecutor 流式生成失败")
            # 异常时也填充已收集的部分 answer，避免外层持久化空值
            self.last_answer = "".join(answer_parts)
            self.last_token_usage = None
            yield f"event: {QueueEvent.ERROR.value}\ndata:{json.dumps({'observation': str(e), 'id': message_id, 'conversation_id': conversation_id, 'message_id': message_id}, ensure_ascii=False)}\n\n"

    def _stream_round_langchain(self, llm, messages, tool_schemas, answer_parts, reasoning_parts, _stream_started_at, message_id, conversation_id):
        """langchain 回退路径的单轮流式（无原生 client 时使用，无法获得推理过程）。"""
        tool_calls: list[dict] = []
        final_chunk = None
        langchain_messages = [
            SystemMessage(content=str(messages[0]["content"]))
        ] + [
            HumanMessage(content=msg["content"]) if msg.get("role") == "user" else SystemMessage(content=msg["content"])
            for msg in messages[1:]
            if msg.get("role") in ("user", "system")
        ]
        try:
            for chunk in LLMActivityProbe.monitor_stream(
                lambda: llm.stream(langchain_messages), feature_key="direct_answer"
            ):
                if chunk is None:
                    continue
                final_chunk = chunk if final_chunk is None else final_chunk + chunk
                content = getattr(chunk, "content", "") or ""
                if content:
                    answer_parts.append(content)
                    yield f"event: {QueueEvent.AGENT_MESSAGE.value}\ndata:{json.dumps({'answer': content, 'id': message_id, 'conversation_id': conversation_id, 'message_id': message_id}, ensure_ascii=False)}\n\n"
        except Exception:
            logger.debug("langchain 回退流式失败", exc_info=True)
        return tool_calls, final_chunk

    def _emit_thought(self, message_id, conversation_id, reasoning_parts, latency=0):
        """推理过程流式发送到思考框（agent_thought 事件，固定 id 更新同一思考框）。"""
        thought_text = "".join(reasoning_parts)
        yield f"event: {QueueEvent.AGENT_THOUGHT.value}\ndata:{json.dumps({'id': message_id, 'event': QueueEvent.AGENT_THOUGHT.value, 'thought': thought_text, 'observation': '', 'tool': 'reasoning', 'tool_input': {}, 'answer': '', 'conversation_id': conversation_id, 'message_id': message_id, 'latency': latency, 'total_token_count': 0}, ensure_ascii=False)}\n\n"
        # 记录到 collected_thoughts（按 id upsert，仅保留最新完整推理链），
        # 供外层持久化到 DB（reload 时思考内容不丢失），避免每次流式 chunk
        # append 一条导致 DB 中出现大量重复 thought 记录
        for idx, item in enumerate(self.collected_thoughts):
            if str(item.get("id", "")) == str(message_id) and item.get("event") == QueueEvent.AGENT_THOUGHT.value:
                self.collected_thoughts[idx]["thought"] = thought_text
                self.collected_thoughts[idx]["latency"] = latency
                return
        self.collected_thoughts.append({
            "id": message_id,
            "event": QueueEvent.AGENT_THOUGHT.value,
            "thought": thought_text,
            "observation": "",
            "tool": "reasoning",
            "tool_input": {},
            "answer": "",
            "latency": latency,
            "total_token_count": 0,
        })

    def execute(self, item) -> dict:
        """``TaskExecutor`` 协议实现：供 ``ExecutionCoordinatorService`` 编排调用。

        以单次 LLM 调用完成任务，将回答与 token 用量写入结果字典，
        由协调器的 ``_execute_item`` 包装为 ``OrchestratedAgentResult``。

        使用 llm.stream() 真正流式调用，避免长时间无反馈。
        """
        try:
            query = getattr(item, "description", "") or ""
            llm = self._resolve_llm()

            messages = (
                [SystemMessage(content=self._resolve_system_prompt())]
                + [HumanMessage(content=query)]
            )
            # 使用流式调用，收集完整 answer 和 token 用量
            answer_parts = []
            final_chunk = None
            for chunk in llm.stream(messages):
                if chunk is None:
                    continue
                final_chunk = chunk if final_chunk is None else final_chunk + chunk
                content = getattr(chunk, "content", "")
                if content:
                    answer_parts.append(content)

            answer = "".join(answer_parts) if answer_parts else (
                final_chunk.content if final_chunk and hasattr(final_chunk, "content") else ""
            )
            token_usage = self._extract_token_usage(final_chunk) if final_chunk else None

            # 公共 AI 功能计费（非消息上下文）
            if token_usage and self.account_id is not None:
                charge_for_feature(
                    self.credit_service,
                    self.account_id,
                    "direct_answer",
                    token_usage["total_tokens"],
                )

            return {
                "agent_id": getattr(item, "task_id", ""),
                "task_id": getattr(item, "task_id", ""),
                "answer": answer,
                "confidence": 1.0,
                "sources": [],
                "tool_calls": [],
                "warnings": [],
                "errors": [],
                "cost": {"token_usage": token_usage} if token_usage else {},
                "metadata": {
                    "title": getattr(item, "title", ""),
                    "token_usage": token_usage,
                },
            }
        except Exception as e:
            logger.exception("DirectAnswerExecutor.execute 失败")
            return {
                "agent_id": "",
                "task_id": getattr(item, "task_id", ""),
                "answer": "",
                "errors": ["direct_answer_failed"],
                "warnings": [],
                "confidence": 0,
                "metadata": {"error": str(e)},
            }

    def _resolve_llm(self):
        # 优先使用外层注入的 LLM 实例（与主路径一致的 tier=3 模型）
        # 避免独立解析 get_feature_model() 时走到不可用的模型链路
        if self._injected_llm is not None:
            return self._injected_llm
        return LanguageModelService.get_feature_model("direct_answer")

    @staticmethod
    def _enable_reasoning(llm):
        """为支持推理的模型启用深度推理模式。

        DeepSeek-V4-Flash 通过 SiliconFlow API 的 reasoning_effort 参数启用推理模式：
        - reasoning_effort="high"：标准推理模式（默认推荐）
        - reasoning_effort="max"：最大推理模式（适合复杂 Agent 任务）

        启用后，API 返回的流式 chunk 中 delta.reasoning_content 字段包含推理过程，
        langchain_openai.ChatOpenAI 会将其映射到 chunk.additional_kwargs.reasoning_content。

        仅对支持 reasoning_effort 的模型生效（通过 model_fields 检测），
        不支持的模型直接返回原实例，不影响正常调用。
        """
        try:
            model_fields = getattr(llm.__class__, "model_fields", {}) or {}
            if "reasoning_effort" not in model_fields:
                return llm
            # 已设置 reasoning_effort 的模型不重复设置
            current = getattr(llm, "reasoning_effort", None)
            if current:
                return llm
            # 绑定 reasoning_effort 参数
            bound = llm.bind(reasoning_effort="high")
            return bound
        except Exception:
            logger.debug("启用 reasoning 模式失败，回退到普通模式", exc_info=True)
            return llm

    @staticmethod
    def _extract_token_usage_from_dict(usage):
        """从原生 SDK 流式最终 chunk 的 usage 字段提取 token 用量。"""
        if not usage:
            return None
        if isinstance(usage, dict):
            return {
                "prompt_tokens": usage.get("prompt_tokens", usage.get("input_tokens", 0)),
                "completion_tokens": usage.get("completion_tokens", usage.get("output_tokens", 0)),
                "total_tokens": usage.get("total_tokens", 0),
            }
        return {
            "prompt_tokens": getattr(usage, "prompt_tokens", 0) or getattr(usage, "input_tokens", 0) or 0,
            "completion_tokens": getattr(usage, "completion_tokens", 0) or getattr(usage, "output_tokens", 0) or 0,
            "total_tokens": getattr(usage, "total_tokens", 0) or 0,
        }

    @staticmethod
    def _extract_token_usage(response):
        metadata = getattr(response, "response_metadata", None) or {}
        usage = metadata.get("token_usage") or metadata.get("usage") or {}
        if not usage:
            return None
        return {
            "prompt_tokens": usage.get("prompt_tokens", usage.get("input_tokens", 0)),
            "completion_tokens": usage.get("completion_tokens", usage.get("output_tokens", 0)),
            "total_tokens": usage.get("total_tokens", 0),
        }
