# Scrapling 集成设计（网页抓取能力接入）

> 状态：已落地（2026-09-27 实现并归档；本文档为历史设计快照）
> 背景：GitHub 项目 [D4Vinci/Scrapling](https://github.com/D4Vinci/Scrapling)（83k star，自适应 Web 抓取框架）需接入本平台。它不是框架级改造项，而是一类可被 Agent 调用的**抓取能力**。

## 1. 结论先行

**Scrapling 以「API 容器内 MCP stdio 子进程」形态接入，零新增容器、零新增代码链路。**

- 入口：admin 后台 `/admin/mcp` 配一个 MCP Provider（`transport=stdio`、`command=scrapling-mcp`）。
- 运行时：既有 [McpStdioClient](file:///d:/DEMO/openagent-main/api/internal/core/tools/mcp_tools/providers/mcp_stdio_client.py#L77-L112) 在 **API 容器内 spawn `scrapling-mcp` 子进程**（短连接、用完即关）。
- 依据：[extensibility-design.md §3.2](file:///d:/DEMO/openagent-main/docs/prd/extensibility-design.md#L61-L68) 的**首选路径**（应用暴露 MCP → 现有 MCP 工厂，配置即用）。

**为什么不拉独立容器**：生产环境要接入几十上百个 MCP，每个都独立容器会导致内存爆炸、运维不可行。既有 stdio 机制本就是为「同一容器内按需 spawn、用完回收」设计的（Dockerfile 特意装 Node 24 即为此）。

## 2. 与现有 browser_action 的互补（优缺点实测）

平台已有 [browser_action](file:///d:/DEMO/openagent-main/api/internal/core/tools/builtin_tools/providers/browser_automation/browser_action.py)（Playwright + `llmops-browser-worker` 容器，9 个交互动作）。两者**互补而非平行机制**：

| 维度 | `browser_action`（现有） | Scrapling（本次接入） |
|---|---|---|
| 定位 | **交互式操作**（点击/输入/按键/滚动） | **数据抓取/采集** |
| 过 Cloudflare Turnstile | ❌ | ✅ StealthyFetcher |
| TLS/浏览器指纹伪装 | ❌ | ✅ `impersonate`（curl_cffi + browserforge） |
| 自适应选择器（改版自动重定位） | ❌ | ✅ `adaptive=True` |
| 批量并发抓取 | ❌ | ✅ `bulk_*` |
| 代理轮换 | ❌ | ✅ 内置 |
| 会话持久 | ❌（每次新建 context） | ✅ `open_session` |
| 内容→LLM-ready Markdown | ❌ | ✅ 内置（含提示注入防护） |
| **交互操作** | ✅ **强**（9 动作 + 桌面端 bridge） | ❌ 不做 |
| 桌面端本机浏览器 | ✅ 经 bridge 用用户本机 | ❌ 仅服务端 |

**分工**：Scrapling 负责「**抓取**」（反爬/自适应/批量/代理），`browser_action` 负责「**交互**」（点/填/键/本机浏览器）。二者不冲突、不重叠。**不替换 browser_action**（它独有的交互与本机 bridge 能力 Scrapling 没有）。

## 3. 依赖冲突评估与处置（已实测）

| 依赖 | Scrapling 要求 | 项目现状 | 处置 |
|---|---|---|---|
| `mcp` | >=2.0.0 | 1.30.0 | **升级至 `>=2.0.0,<3`**（已实测兼容，见 §3.1） |
| `playwright` | >=1.62.0 | 1.55.0（worker 镜像） | API 容器新装；worker 镜像不装 scrapling，不受影响 |
| `lxml` | >=6.1.1 | 6.0.2 | 升级至 6.1.3（minor，**必须**，否则 pip 冲突） |
| `orjson` | >=3.11.8 | 3.11.7 | 升级至 3.12.0（patch，**必须**，否则 pip 冲突） |
| `idna` | >=3.18（间接：mcp 2.x → httpx2） | 3.11 | 升级至 3.20（**必须**，否则 pip 冲突） |
| `anyio` | >=4.14.0（间接：scrapling[fetchers]） | 4.12.1 | 升级至 4.14.2（**必须**，否则 pip 冲突） |
| 新增 | curl_cffi / patchright / browserforge / apify-fingerprint-datapoints / msgspec / anyio / protego / cssselect / tld / w3lib / markdownify | — | 新增 |

### 3.1 mcp 1.30 → 2.x 兼容性（决定性验证）

实测 `mcp 2.2.0` wheel，确认项目在用的三个导出**完整保留**：

```python
from .client.session import ClientSession            # 保留
from .client.stdio import StdioServerParameters, stdio_client   # 保留
```

项目对 `mcp` 的 Python 依赖**仅 2 处 import**，均在 [mcp_stdio_client.py](file:///d:/DEMO/openagent-main/api/internal/core/tools/mcp_tools/providers/mcp_stdio_client.py#L277-L331)（`_list_tools_async` / `_call_tool_async`），且只用协议最稳定的 API（`initialize` / `list_tools` / `call_tool`）。**升级后现有代码无需改一行**，但仍须全量回归验证。

**端到端实测（隔离 `/tmp/mcp2` 加载 mcp 2.2.0 真实运行）**：

```
EXPORTS_OK                     # ClientSession / StdioServerParameters / stdio_client 均可导入
IMPORT_CLIENT_OK               # 项目 McpStdioClient 成功 import
LIST_TOOLS_OK 13               # 真实 spawn npx @modelcontextprotocol/server-everything → initialize → tools/list
CALL_TOOL_OK {'content': [{'text': 'Echo: hello-mcp2'}], 'isError': False}
```

即 mcp 2.2.0 下导出 / import / 真实 spawn / `list_tools` / `call_tool` 全部可用，**无需迁移既有 client 代码**。为防未来 mcp 3.x 静默漂移，依赖收敛为 `mcp>=2.0.0,<3`。

## 4. 部署设计

### 4.1 镜像改造（`api/Dockerfile`）

在既有 `api` 镜像上叠加 Scrapling 及其浏览器依赖：

1. `requirements.txt` 增加 `scrapling[ai]==0.4.15`（并收敛冲突 pin：`lxml`/`orjson`/`idna`/`anyio`，见 §3）。
2. 系统依赖：在 Dockerfile 的 apt 段追加 Chromium 运行库，并执行 `python -m playwright install chromium`。
   - **不使用 `scrapling install`**（它会连带安装 Camoufox）。
   - **必须让浏览器脱离 `/root/.cache`**：Playwright 默认将浏览器装到 `/root/.cache/ms-playwright`，会被 pip 段的 `rm -rf /root/.cache` 误删，导致运行时 `DynamicFetcher` 报 "Executable doesn't exist"（此坑已在实施中实测踩到）。**最终方案**为设置镜像级 `ENV PLAYWRIGHT_BROWSERS_PATH=/opt/ms-playwright`（并同时 `TIKTOKEN_CACHE_DIR=/opt/tiktoken`），把运行时必需资产移出 `/root/.cache`，使 pip 缓存清理得以安全保留。
3. **StealthyFetcher 的 Camoufox 依赖**：需在构建期单独安装（`scrapling` 的 stealth 引擎）。若构建期安装体积/网络不可接受，可退化为「仅 `Fetcher`/`DynamicFetcher` 可用，`stealthy_fetch` 构建期不装浏览器、运行时按需报错」——见 §7 风险。

### 4.2 admin 配置（零代码）

在 `/admin/mcp` 新建 Provider：

| 字段 | 值 |
|---|---|
| name | `scrapling` |
| transport | `stdio` |
| command | `scrapling-mcp` |
| args | `[]`（默认 stdio 模式） |
| timeout_seconds | 建议 `120`（浏览器抓取较慢） |
| tool_names | **默认仅开轻量类**（见 §5） |

无需 HTTP/端口/鉴权（stdio 只对父进程可见，天然隔离）。

### 4.3 运行时链路

```
Agent 对话 → 工具池装配（McpToolFactory.get_tools）
  → McpStdioClient.list_tools_sync（spawn scrapling-mcp → initialize → tools/list → 关闭）
  → Agent 调用某工具 → McpStdioClient.call_tool_sync（重新 spawn → initialize → tools/call → 关闭）
  → 返回抓取结果（文本/Markdown/图片块）
```

短连接模式：每次调用独立子进程，**用完即回收，无常驻内存**（与"每 MCP 一容器"的资源模型相反）。

## 5. 工具开放范围（全部接入 + 默认只开轻量）

Scrapling MCP 提供 **13 个工具**（已从 `scrapling/core/ai.py` 源码逐个核实，与官方文档一致）。按「全部接入、默认只开轻量」：

| 类别 | 工具 | 默认 | 理由 |
|---|---|---|---|
| 轻量 HTTP | `make_request`、`bulk_get` | ✅ 开 | 纯 HTTP + 指纹伪装，无浏览器、低内存 |
| 动态渲染 | `fetch` | ✅ 开 | 启 Chromium，成本可控 |
| 批量渲染 | `bulk_fetch` | ⚪ 关 | 多标签并发，内存高 |
| 隐身/过盾 | `stealthy_fetch`、`bulk_stealthy_fetch` | ⚪ 关 | 过盾有合规风险、Camoufox 重 |
| 会话 | `open_session`、`open_request_session`、`close_session`、`list_sessions`、`session_fetch`、`session_make_request` | ⚪ 关 | 长连接持浏览器，占内存 |
| 截图 | `screenshot` | ⚪ 关 | 依赖已开会话 |

### 5.1 `tool_names` 字段的确切语义（已核实源码）

- **字段类型**：`mcp_provider.tool_names` 为 `list[str]`（见 [McpProviderEntity](file:///d:/DEMO/openagent-main/api/internal/core/tools/mcp_tools/entities/mcp_provider_entity.py#L19)）；admin 前端为**逗号分隔列表**输入。
- **匹配的是 MCP 原始工具名**：`McpToolFactory` 用 `tool_names` 与 `tool_definition["name"]` 比对（[mcp_tool_factory.py:374-384](file:///d:/DEMO/openagent-main/api/internal/core/tools/mcp_tools/providers/mcp_tool_factory.py#L374-L384)），即填 `make_request`，**不填**装配后的命名空间名。
- **装配后工具名前缀**：最终暴露给 LLM 的工具名是 `mcp__{binding_name}__{raw_tool_name}`（[mcp_tool_factory.py:582](file:///d:/DEMO/openagent-main/api/internal/core/tools/mcp_tools/providers/mcp_tool_factory.py#L582)）。若 Provider 的 `name` 配为 `scrapling`，则工具在 LLM 侧为 `mcp__scrapling__make_request` 等——**与内置工具 `browser_action` 天然不重名**，无冲突。
- **默认轻量集**：`tool_names = ["make_request", "bulk_get", "fetch"]`；其余由 admin 在后台编辑该字段按需追加。
- **机制复用**：全部 13 个接入（`tools/list` 全量暴露），启停复用既有 `tool_names` 白名单，**不新建开关机制**。

## 6. 接线面与验证

| 产物 | 入口 / 验证 |
|---|---|
| `requirements.txt` 加 `scrapling[ai]` | 镜像重建 → `docker exec llmops-api scrapling-mcp --help` |
| MCP Provider（一次配置） | `/admin/mcp` 新建 → tools/list 应返回 13 个工具 |
| 工具可用性 | Agent 对话调用 `make_request` 抓一个公开页面，返回非空内容 |
| mcp 2.x 兼容 | `pytest test/internal/core/tools/` 全量 + MCP 相关路由测试 |
| 与 browser_action 不冲突 | 两者同场装配，工具名不重叠（`browser_action` vs `make_request` 等） |

## 7. 风险与回退

| 风险 | 严重度 | 缓解 |
|---|---|---|
| `mcp 1.30→2.x` 破坏既有 MCP 集成 | 中 | **已端到端实测通过**（真实 spawn + `list_tools` + `call_tool`，见 §3.1）；全量回归 MCP 相关测试；若失败则隔离到独立容器（回退方案 A） |
| `scrapling install` 需 root/apt，构建失败 | 中 | Dockerfile 显式装 Chromium 运行库；构建期日志校验 |
| Camoufox 体积大 / 构建期网络受限 | 中 | 可不装 Camoufox → `stealthy_fetch` 运行时明确报错，其余工具不受影响 |
| 浏览器抓取超时（默认 30s） | 中 | Provider `timeout_seconds` 设 120 |
| 过盾能力被滥用（合规） | 中 | 默认关闭 stealthy 类；仅 admin 显式开启 |
| 每次调用 spawn 子进程的开销 | 低 | 短连接是有意设计（无常驻内存）；高频调用可后续评估会话复用 |
| lxml/orjson/idna/anyio 升级副作用 | 低 | 全量后端回归（Task 5） |
| MCP 工具参数名与 pydantic 保留属性冲突（如 `json`） | 低 | 实施中发现 `make_request` 的 `json` 参数触发 `Field name "json" shadows an attribute in parent "BaseModel"` 告警；当前不影响工具构建与调用，若后续需要可让 `McpSchemaCompiler` 对冲突字段名做别名映射 |

**回退**：移除 Provider 配置即停用（工具不再装配）；`requirements.txt` 回退即恢复镜像。

## 8. 收尾自检（按仓库规则）

1. **判定**：不构成平行机制。Scrapling（抓取）与 `browser_action`（交互）职责不重叠，各自补充对方缺口。
2. **处置**：**配置接入**（首选路径），非新建链路——复用既有 `McpToolFactory → McpStdioClient` 唯一通道。
3. **单一权威入口**：MCP 工具仍唯一走 `McpToolFactory`；工具启停仍唯一走 `tool_names` 白名单；无新建工厂或开关。
4. **不新建容器**：用既有 stdio spawn 机制，避免"每 MCP 一容器"的生产不可行问题。
5. **诚实披露**：`stealthy_fetch` 若构建期不装 Camoufox，则属「已接入但运行时不可用」，须在文档与 admin 配置说明中标注，不得写成"全能力可用"。
