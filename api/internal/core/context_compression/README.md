# 上下文压缩模块

该模块是 Headroom 核心设计在钰心AI 内的精简落地：在工具输出进入 LLM 之前做结构化压缩，减少 token 成本，同时不改变 Agent 的调用链。

## 为什么不自带整个 Headroom

- Headroom 的重型压缩器（SmartCrusher、LogCompressor）是 Rust 扩展，Python 层只是薄 shim，无法只拷几个纯 Python 文件。
- 引入 `headroom-ai` 会带进 litellm、aiohttp 等依赖，和当前 `requirements.txt` 的锁定版本冲突。
- 我们真正需要的是“内容路由 + JSON 数组压缩 + 日志折叠 + 保护消息 + 失败放行”这一小部分。

所以这里用纯 Python 实现了同样的核心设计，零额外依赖。

## 支持的内容

| 内容 | 行为 |
|---|---|
| JSON 数组（工具输出、检索结果） | 保留 schema、首尾样本、错误/异常项和统计摘要 |
| 日志/构建输出 | 保留错误与上下文、首尾样本，其余按模板折叠 |
| 普通文本/中文 | 透传，不做有损压缩 |
| 源码/短消息 | 透传 |

## 环境变量

| 变量 | 默认值 | 说明 |
|---|---|---|
| `CONTEXT_COMPRESSION_ENABLED` | `0` | 总开关，默认关闭 |
| `CONTEXT_COMPRESSION_MIN_CHARS` | `1000` | 小于该长度不压缩 |
| `CONTEXT_COMPRESSION_MIN_TOKENS` | `250` | 预估 token 小于该值不压缩 |
| `CONTEXT_COMPRESSION_MAX_ITEMS` | `15` | JSON 数组保留样本上限 |
| `CONTEXT_COMPRESSION_MAX_LOG_LINES` | `60` | 日志模板行上限 |
| `CONTEXT_COMPRESSION_PROTECT_RECENT` | `2` | 保留最近 N 条消息不压缩 |

## 接入点

- `FunctionCallAgent._tools_node`：新生成的 `ToolMessage` 在返回给 LLM 前压缩。
- `DeepThinkingAgent`：继承 `FunctionCallAgent`，自动生效。
- `DirectAnswerExecutor.stream`：工具调用多轮消息追加前压缩。
- 其它调用方可直接使用 `compress_content()` / `compress_dict_messages()` / `compress_langchain_tool_messages()`。

所有压缩失败都会原样返回内容，不阻塞请求；压缩统计可通过 `get_compression_stats()` 查看。
