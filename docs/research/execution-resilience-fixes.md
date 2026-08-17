# Agent 执行链路弹性修复（结构化输出 / Token 计数 / A2A 注入）

> 状态：已落地并验证。目标：修复 deepseek-v4-flash 等模型导致 Agent 执行链路瘫痪的问题。

## 背景与根因

线上 API 日志显示执行链路存在三类瘫痪点：

1. **结构化输出被模型提供方拒绝**
   `openai.BadRequestError: This response_format type is unavailable now`。
   会话命名、指挥官决策、任务分类、深度思考路由/大纲等关键路径直接 400。
2. **token 计数未实现**
   `NotImplementedError: get_num_tokens_from_messages() is not presently implemented for model deepseek-v4-flash`，
   上下文压缩链路只能跳过 trim。
3. **A2A 网关注入失败**
   `TypeError: Injecting Any is not supported`，导致 Agent 出站 A2A 工具构建失败。

## 参考的开源 Agent Harness 做法

主流 Agent 框架对“模型能力不完整”都采用确定性兜底，而不是让执行链中断：

- OpenAI Agents SDK / Vercel AI SDK：结构化输出失败时回退 JSON 模式，或使用普通文本 + 提示词约束 + 解析。
- smolagents：从模型文本中 `parse_json_blob()` 提取 JSON，容忍 Markdown 代码块和前后解释文字。
- LangGraph：`with_structured_output` 不具备 provider 原生支持时退化为 prompt + parser，并建议加入 Parse/Validate → Retry → Escalate 循环。
- OpenHands / strands-agent：token 计数不支持原生实现时使用 `tiktoken`，再退化为字符数估算。

## 落地实现

### 1. 结构化输出兜底（`api/internal/lib/structured_output.py`）

新增 `with_structured_output_fallback(llm, response_model)`，返回兼容 LangChain Runnable 的
`StructuredOutputFallbackRunnable`：

- 优先调用原生 `with_structured_output()`。
- 捕获“response_format 不可用 / 不支持结构化输出”类异常后，改用普通文本调用，
  在 prompt 中注入 JSON Schema，最后 `parse_json_blob()` 解析并 `model_validate()`。
- 同时支持 `invoke` / `stream` / `ainvoke` / `astream`，可被 `prompt | structured_llm` 链式组合。

已接入位置：

- `conversation_service.generate_conversation_name` / `generate_suggested_questions`
- `conductor_service`（指挥官计划）
- `pool_intent_resolver_service`（子池意图）
- `deep_thinking_agent`（路由决策 + 文档大纲）
- `LLMActivityProbe.invoke_structured_with_probe`（任务分类、记忆实体抽取等公共入口）

### 2. Token 计数兜底（`api/internal/service/language_model_service.py`）

`RuntimeFallbackLanguageModelProxy.get_num_tokens_from_messages()` 在底层模型抛
`NotImplementedError` / `ImportError` 时，回退到 `tiktoken cl100k_base` 估算，
再退化为 `字符数 // 4`。`assistant_agent_service.generate_introduction()` 等
`trim_messages(token_counter=llm)` 不再中断。

### 3. A2A 网关注入修复（`api/internal/service/a2a_gateway_service.py`）

`A2AGatewayService` 的字段类型由 `Any = None` 改为
`Optional[PublicAgentA2AService]` / `Optional[PublicAgentRegistryService]`，
injector 不再报 `Injecting Any is not supported`，Agent 出站 A2A 工具可正常挂载。

## 验证

- 新增单测：
  - `api/test/internal/lib/test_structured_output_fallback.py`
  - `api/test/internal/service/test_language_model_token_fallback.py`
  - `api/test/internal/service/test_a2a_gateway_service.py::test_a2a_gateway_service_can_be_resolved_by_injector`
- 相关回归测试共 159 项通过（会话命名/建议问题、指挥官、子池意图、深度思考、A2A 网关）。
- 在 API 容器内对真实 deepseek-v4-flash 调用会话命名，成功返回中文会话名，不再 400。
- 容器日志不再出现 `Injecting Any` / `response_format` 相关的执行链路报错。
