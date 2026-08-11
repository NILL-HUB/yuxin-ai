# Headroom 调研：给 LLM 上下文做压缩的“中间层”

> 调研时间：2026-08-12。结论基于 GitHub 仓库元数据、README、官方 docs 源码、PyPI/npm 元数据、MCP `server.json` 以及本项目代码现状。

## 结论

Headroom 与钰心AI/OpenAgent 高度适配，而且比 CLI-Anything 更贴近我们的核心运行路径。它解决的是我们最疼的一个问题：工具输出、RAG 检索结果、沙箱产物、长会话历史一起塞进 LLM 上下文，token 成本高且容易逼近上下文窗口。

它的价值集中在三个场景：

1. **工具结果压缩**：JSON/日志/检索结果通常可压缩 60% 到 95%，这正是我们知识库检索、MCP 工具、深思考沙箱输出最常用的内容形态。
2. **长会话与多轮 Agent**：我们 `FunctionCallAgent`/`DeepThinkingAgent` 会把 ToolMessage 累积进 LangGraph 状态，Headroom 的 live-zone + cache 模式可以在不破坏 provider prefix cache 的前提下做增量压缩。
3. **模型侧成本**：我们接 OpenAI、Anthropic、DeepSeek、硅基流动等多家供应商，Headroom 支持 LangChain ChatModel 包装、代理和 MCP 三种接入，不必逐家改造。

但需要先做 PoC 验证三件事：`headroom-ai[langchain]` 与当前 `langchain==1.2.18` / `langchain-openai==1.1.10` 的兼容性；中文长文/中文日志的真实压缩率；流式 token 计费（`_calculate_usage`）在包装后是否仍准确。

落地状态（2026-08-12）：已完成 PoC 验证并落地。实测 `headroom-ai 0.34.0` 的结构化压缩（JSON/日志）有效，但重型压缩器是 Rust 扩展、且依赖树与项目锁定的 `aiohttp==3.13.3` 等版本冲突；中文纯文本需要额外 `[ml]` 模型且当前环境不可用。因此没有整体引入 `headroom-ai`，而是按它的核心设计（内容路由 + JSON 数组压缩 + 日志折叠 + 保护消息 + 失败放行）在 `api/internal/core/context_compression/` 实现了一个零额外依赖的精简模块，并已接入 `FunctionCallAgent` 与 `DirectAnswerExecutor`，默认关闭、按环境变量开启。

## 它是什么

- 官方仓库：<https://github.com/headroomlabs-ai/headroom>（原 `chopratejas/headroom`，GitHub 会自动重定向）
- 定位：The context compression layer for AI agents。在 Agent/应用与 LLM 之间加一层本地压缩，压缩工具输出、日志、文件、RAG chunks、对话历史后再发给模型
- 作者：Tejas Chopra（PyPI/GitHub 账号 `chopratejas`），多家媒体称其当时任职 Netflix，属二手信息
- 许可：Apache License 2.0
- 版本：Python 包 `headroom-ai` 最新 0.34.0（2026-08-05）；npm `headroom-ai` 最新 0.22.4，仅 TypeScript SDK，无 CLI
- 规模：GitHub API 截至 2026-08-12 约 65.9k stars、5.0k forks、637 open issues；仓库创建于 2026-01-07，版本从 0.x 到 0.34.0，迭代非常快
- 文档：<https://headroom-docs.vercel.app/docs>、<https://docs.headroomlabs.ai/docs>；HuggingFace 模型：<https://huggingface.co/chopratejas/kompress-v2-base>

## 核心机制

### 1. 压缩管线

Headroom 的请求生命周期固定为：Setup → Input Received → Routed → Compressed → Remembered → Pre-Send → Response。核心是 `ContentRouter`，按内容类型路由到不同压缩器：

| 内容类型 | 压缩器 | 官方宣称节省 |
|---|---|---|
| JSON 数组（工具输出） | SmartCrusher | 70% 到 90% |
| 搜索/grep 结果 | SearchCompressor | 80% 到 95% |
| 构建/测试日志 | LogCompressor | 85% 到 95% |
| diff | DiffCompressor | 40% 到 80% |
| HTML | HTMLExtractor | 约 95% |
| 表格 CSV/TSV | TabularCompressor | 60% 到 90% |
| YAML/TOML/INI | ConfigCompressor | 40% 到 70% |
| 纯文本 | TextCrusher/Kompress | 30% 到 60% |
| 源码 | 默认透传，AST 压缩可选 | 默认 0% |

重压缩器在 Rust 核心（PyO3）里跑，ML 兜底是 ModernBERT/ONNX 的 Kompress。管道“fails open”：任何压缩失败都原样返回内容，不影响请求。

### 2. 三种运行模式

- **Proxy**：`headroom proxy --port 8787`，把任意 OpenAI/Anthropic 兼容客户端的 base URL 指过来即可，零代码改动。支持 `--backend litellm-<provider>`、`--mode cache|token`、预算、限流、OpenTelemetry/Prometheus。
- **Library/SDK**：Python `compress(messages)`、TypeScript `await compress(messages, { model })`，以及 OpenAI/Anthropic SDK 包装。
- **MCP**：`headroom mcp serve`，暴露 `headroom_compress`、`headroom_retrieve`、`headroom_stats` 三个工具，可给 Claude Code、Codex、Cursor 以及我们自己的 MCP client 用。

另有 `headroom wrap claude|codex|grok|copilot|...` 包装外部 CLI Agent，以及 `headroom learn` 失败会话挖掘，这两个对我们 Web 平台不直接适用。

### 3. 可逆压缩（CCR）与缓存

- 压缩时原文存本地 SQLite/CCR store，模型需要时调用 `headroom_retrieve` 取回，不会永久丢信息。
- 默认 `cache` 模式只压缩最新 delta，历史消息字节不变，避免打断 Anthropic/OpenAI 的 prefix cache。
- `--lossless` 可做格式原生无损折叠，`--no-ccr` 可关闭检索标记。

### 4. 安全与运维

- 遥测默认关闭且仅本地统计；旧的匿名 beacon 已移除；`--offline` 硬禁所有外联。
- `HEADROOM_PROXY_TOKEN` 要求 bearer token；`/v1/compress` 默认仅 loopback。
- x86 无 AVX2 时自动降级；Windows/Linux/macOS 都有预编译 wheel。
- 安装依赖两个外部资产：`cdn.pyke.io` 的 ONNX Runtime、HuggingFace 的 Kompress 模型；可预置并离线运行。

## 与钰心AI/OpenAgent 的适配分析

### 高度契合的点

- **我们是 LangChain/LangGraph 栈**：`api/requirements.txt` 使用 `langchain==1.2.18`、`langchain-openai==1.1.10`、`langchain-anthropic==1.4.3`，Headroom 官方提供 `HeadroomChatModel(ChatOpenAI(...))`、`HeadroomChatMessageHistory`、`HeadroomDocumentCompressor`、`wrap_tools_with_headroom`，直接对应我们四种场景：模型调用、会话历史、知识检索、Agent 工具。
- **模型实例化有唯一入口**：`api/internal/service/language_model_service.py` 的 `_instantiate_model` 统一创建 ChatOpenAI/ChatAnthropic 等，并按模型配置注入 `base_url`、`timeout`、UA。在这里按 feature flag 包一层 `HeadroomChatModel`，就能覆盖大部分调用链，而不需要改每个调用方。
- **Agent 工具消息是主要成本源**：`function_call_agent.py::_tools_node` 把 `ToolMessage` 追加进 LangGraph 状态，`_llm_node` 再整包发给 `llm.astream`。Headroom 对 JSON 数组、日志、检索结果的压缩率最高，正好命中。
- **深思考/沙箱场景天然匹配**：`DeepThinkingAgent` 会积累沙箱输出、文档片段、结构化 plan，`direct_answer_executor.py::stream` 也会多轮追加工具结果；这些长块非常适合压缩。
- **RAG 场景可用**：知识库检索先召回更多、再压缩保留高相关项，能提升召回上限而不爆窗口；`HeadroomDocumentCompressor` 可以直接包在现有检索服务外层。
- **MCP 基础设施可复用**：我们已有 `api/internal/core/tools/mcp_tools/providers/mcp_stdio_client.py`，可以把 `headroom mcp serve` 注册成一个标准 stdio provider，让 Agent 在需要时主动压缩/取回。
- **多供应商模型池不受限**：我们通过 `compatible_api` 区分 openai/claude，Headroom wrapper 对任意 BaseChatModel 可用；代理模式也支持 OpenAI-compatible 和 Anthropic。
- **Docker 部署可做成 sidecar**：`docker/docker-compose.yaml` 已有 llmops-api/celery/nginx 等，可以新增 `llmops-headroom` 服务，api/celery 通过内网地址调用。

### 需要注意/不适合的点

- **代码和短文本默认不压缩**：官方 Limitations 明确源码透传、短消息（<300 tokens）跳过、图片不压缩、纯文本有延迟开销。我们如果大量短轮聊天，收益有限。
- **中文场景缺乏官方基准**：README 的 benchmark 以英文/代码为主，release notes 提到 CJK-aware diff relevance，但中文日志、中文 RAG chunk 的真实压缩率和精度需要自己测。
- **版本兼容风险**：`headroom-ai[langchain]` 依赖的 LangChain 版本可能和我们锁定的 `langchain 1.x` 有出入；`RuntimeFallbackLanguageModelProxy` 再包 Headroom wrapper 后，`bind_tools`、`astream`、usage metadata 都要回归测试。
- **流式/计费链路要验证**：`direct_answer_executor` 走 ChatOpenAI 原生 `client.chat.completions.create` 流式，绕过了 LangChain；只在 `_instantiate_model` 包 wrapper 覆盖不到这条路径，需要单独在 `stream()` 里压缩 messages，或用代理模式。
- **离线/网络约束**：Kompress 模型和 ONNX Runtime 需要提前进镜像；SCF 沙箱可能无法跑本地 Rust/ONNX 服务，只适合轻量 `compress()` 或关掉 ML。
- **不是上下文管理替代品**：Headroom 不删历史消息，只压缩；我们自己的 `memory/`、checkpointer、会话裁剪仍是主结构，Headroom 是叠加优化。
- **项目迭代快**：0.x 阶段 7 个月到 0.34，API 和配置会变，接入后需要固定版本并做升级窗口。

## 接入建议（按优先级）

### P0：LangChain ChatModel 包装 + Agent 工具输出压缩

1. 在 `api/requirements.in` 加 `headroom-ai[langchain]`（固定版本），先做最小安装验证，不动 `langchain` 主版本。
2. 在 `language_model_service._instantiate_model` 加 `HEADROOM_ENABLED` 开关：实例化完成后，若开启则用 `HeadroomChatModel` 包住 inner instance，再走现有 `RuntimeFallbackLanguageModelProxy`。先只开测试环境。
3. 在 `function_call_agent._tools_node` 或 `_llm_node` 增加可选的 `wrap_tools_with_headroom` / `compress()`：只对超过阈值（如 `HEADROOM_MIN_TOKENS=500`）的 ToolMessage 压缩，user 消息和最近 2 轮保护。
4. 回归项：`bind_tools` 调用链、`astream` 流式、`_calculate_usage` 的 token/price、tool_call id 完整性、deep timeline 里的原始工具输出展示。

### P1：Headroom Proxy 作为模型网关 sidecar

1. `docker/docker-compose.yaml` 新增 `llmops-headroom` 服务，镜像用官方 Docker 或 Python 3.11 + `headroom-ai[proxy]`；api/celery 通过 `http://llmops-headroom:8787` 访问。
2. 模型池里加“Headroom”虚拟 provider，或把某个 provider 的 `default_base_url` 指到 proxy；多 provider 场景用 `x-headroom-base-url` 头按请求路由到真实上游。
3. 开启 `HEADROOM_SAVINGS_PROFILE=general`（我们偏非 coding），`--mode cache` 保持 prefix cache；量大的再评估 `balanced`/`agent-90`。
4. 离线镜像内预置 ONNX Runtime 和 Kompress 模型，`HEADROOM_OFFLINE=1`，避免运行时外联。

### P2：MCP 工具接入

1. 把 `headroom mcp serve` 注册为 MCP stdio provider（复用 `mcp_stdio_client.py`），工具名 `headroom_compress`、`headroom_retrieve`、`headroom_stats`。
2. 在系统提示词或技能里说明：遇到超大工具输出先 `headroom_compress`，需要原文再 `headroom_retrieve`。注意官方提示 MCP 调用本身也会占上下文，重子代理场景优先用 proxy 自动压缩。

### P3：RAG 与长会话

1. `retrieval_service` 外层用 `ContextualCompressionRetriever` + `HeadroomDocumentCompressor`，召回 top-k 调大、返回 top-n 压缩结果。
2. 会话历史层可评估 `HeadroomChatMessageHistory`，但我们的对话持久化在 DB/Redis，直接换 history 实现需要适配；更稳妥的是在组装 messages 时对历史中的长 tool/file 内容做一次压缩。

### 最小 PoC 建议

- 独立 venv 安装 `headroom-ai[langchain]`，用我们真实的 `LanguageModelService.get_feature_model("direct_answer")` 拿一个模型，构造一组“知识库检索 JSON + 沙箱日志 + 长对话”消息，对比 `tokens_before/after` 和中文回答质量。
- 只对 `direct_answer_executor` 的一个入口（例如 DebugChat）加 feature flag 包装，跑现有 `api/test/` 里的 direct answer / deep thinking 测试。
- 重点验证三件事：LangChain 1.x 兼容、中文压缩效果、token 计费不变。

## 来源

官方/一手：

- GitHub 仓库：<https://github.com/headroomlabs-ai/headroom>
- README：<https://github.com/headroomlabs-ai/headroom/blob/main/README.md>
- 官方文档：<https://headroom-docs.vercel.app/docs>
- Architecture：<https://github.com/headroomlabs-ai/headroom/blob/main/docs/content/docs/architecture.mdx>
- LangChain 集成：<https://github.com/headroomlabs-ai/headroom/blob/main/docs/content/docs/langchain.mdx>
- Proxy 文档：<https://github.com/headroomlabs-ai/headroom/blob/main/docs/content/docs/proxy.mdx>
- MCP 文档：<https://github.com/headroomlabs-ai/headroom/blob/main/docs/content/docs/mcp.mdx>
- Limitations：<https://github.com/headroomlabs-ai/headroom/blob/main/docs/content/docs/limitations.mdx>
- Benchmarks：<https://github.com/headroomlabs-ai/headroom/blob/main/docs/content/docs/benchmarks.mdx>
- Configuration：<https://github.com/headroomlabs-ai/headroom/blob/main/docs/content/docs/configuration.mdx>
- MCP server.json：<https://github.com/headroomlabs-ai/headroom/blob/main/server.json>
- PyPI：<https://pypi.org/project/headroom-ai/>
- npm：<https://www.npmjs.com/package/headroom-ai>
- HuggingFace 模型：<https://huggingface.co/chopratejas/kompress-v2-base>

本项目代码现状（用于适配判断）：

- 模型实例化入口：`api/internal/service/language_model_service.py`
- 模型类注册：`api/internal/core/language_model/model_class_registry.py`
- Agent 工具消息与 LLM 节点：`api/internal/core/agent/agents/function_call_agent.py`
- 深度思考 Agent：`api/internal/core/agent/agents/deep_thinking_agent.py`
- 直接回答原生流式链路：`api/internal/service/executors/direct_answer_executor.py`
- MCP stdio client：`api/internal/core/tools/mcp_tools/providers/mcp_stdio_client.py`
- 记忆/压缩服务：`api/internal/service/memory/`
- 依赖清单：`api/requirements.in`、`api/requirements.txt`
- Docker 编排：`docker/docker-compose.yaml`
