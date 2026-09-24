# ADMIN-P5：MCP 动态身份注入（独立内部字段 + hash 剥离）

> **Date:** 2026-09-21
> **Status:** 待执行（计划先行）
> **依据规格：** [2026-09-15-admin-agent-governance-design.md](../../superpowers/specs/2026-09-15-admin-agent-governance-design.md) §7.2（MCP 动态身份注入）、§6.1（独立链路）、§4.1（三重交集实时重算）
> **前置依赖：** ADMIN-P1a（授权内核）、ADMIN-P1b（板块工具与执行）、ADMIN-P2（对话式入口）

---

## 1. Goal

让管理端 Agent 对话链路（`AdminAgentChatService`）装配 MCP 工具时，为每个 runtime binding 注入**动态 principal 签名**（`X-Admin-Agent-Principal` header），使 MCP 通道能够识别「哪个管理员 + 哪个 Agent」发起的调用；同时保证动态签名**不破坏既有 MCP 快照机制**（hash 剥离）、**不落库**、**不触发 `decrypt_headers` 抛错路径**。

## 2. 现状与问题

| 事实 | 代码位置 | 影响 |
| --- | --- | --- |
| MCP 工具由 `McpToolFactory.get_tools(bindings, snapshots)` 构建，`_build_langchain_tool` 用**实时入参 binding** 构造工具（快照内 binding 仅用于身份匹配与 hash 比对，不参与构造） | `mcp_tool_factory.py` | 动态 header 无需进快照即可生效 |
| `_jsonrpc_request` 仅注入 `decrypt_headers(binding.get("headers"))` 解出的**静态加密凭证** | `mcp_tool_factory.py:689-735` | 无调用者身份；admin Agent 调用与用户调用在 MCP 侧无法区分 |
| `_binding_hash` 对 binding 整体 JSON 序列化算 SHA-256 | `mcp_tool_factory.py:154-160` | 若动态签名进 binding，hash 每次不同 → 快照频繁失效 |
| `_build_snapshot_payload` 会把 `normalized_binding` 整体持久化进 `app_config.mcp_tool_snapshots`（DB JSONB） | `mcp_tool_factory.py:181-242` | 动态签名若进 binding 会**明文落库** |
| `decrypt_headers` 对每个非空 value 强制 `_decrypt_value`，解密失败直接抛 `ValueError` | `tool_credential_encryptor.py` | 明文签名 header 会被运行时拒绝（除非先加密，但 Fernet 随机 IV 又导致 hash 不稳） |
| admin 对话链路 `_build_tools` 只装配板块工具（`build_board_tools`），**不装配 MCP** | `admin_agent_chat_service.py:287-303` | admin Agent 无法经对话链路使用 MCP 通道；动态身份注入无装配入口 |

## 3. 方案（设计 §7.2 落地）

### 3.1 新增：`api/internal/core/admin_agent_mcp_identity.py`

principal 签名的生成/验证与运行时 binding 构造，独立成模块（可独立测试）。

```python
PRINCIPAL_TOKEN_FIELD = "_principal_token"      # binding 内部字段名（下划线开头，hash 剥离依据）
PRINCIPAL_HEADER = "X-Admin-Agent-Principal"    # 注入 MCP 请求的 header 名
PRINCIPAL_TOKEN_TTL_SECONDS = 300               # 短时有效：单轮对话工具循环 ≤6 次迭代，5 分钟足够

def sign_principal_token(principal: AdminAgentPrincipal) -> str:
    # JWT HS256（复用 JwtService.generate_token，secret = JWT_SECRET_KEY）
    # payload 只放身份标识：admin_user_id / agent_id / agent_name / iat / exp
    # **不放权限快照**：权限是三重交集实时重算（设计 §4.1），快照会过期；
    # MCP server 侧凭 admin_user_id+agent_id 从 DB 重算（与 L1 同一入口）。

def build_runtime_bindings_with_identity(
    mcp_bindings: list[dict], principal: AdminAgentPrincipal,
) -> list[dict]:
    # 为每个 binding 构造 **副本** 并注入 _principal_token；不修改原 binding
    # （原 binding 可能来自 app_config，副本避免污染 DB 序列化）。

def verify_principal_token(token: str) -> dict:
    # JwtService.parse_token 还原 payload（供未来进程内 MCP server 侧使用；
    # 本系统当前无进程内 MCP server，此函数提供能力、标注未接入）。
```

**token 载荷**：`{"admin_user_id": str, "agent_id": str, "agent_name": str, "iat": int, "exp": int}`。权限/自动化级别**不在 token 内**——保持「运行时实时重算」约束（设计 §4.1 三层强制之一），token 只承载归属标识。

### 3.2 改动：`McpToolFactory`

- **`_binding_hash`**：计算前剥离 `_` 开头的内部字段（`payload = {k: v for k, v in binding.items() if not k.startswith("_")}`）。`_principal_token` 不参与 hash → 快照复用不受影响。
- **`_jsonrpc_request`**：`binding.get("_principal_token")` 非空时加 `X-Admin-Agent-Principal` header。

两处合计仅数行（设计 §7.2 原话：代价仅为 `_jsonrpc_request` 与 `_binding_hash` 各加数行）。

### 3.3 装配点：`AdminAgentChatService._build_tools`

在 `build_board_tools(execution, principal)` 之上合并 MCP 工具：

```python
def _build_tools(self, principal):
    tools = build_board_tools(execution, principal)
    # 与用户端同源全局配置（assistant_agent_service.py:909 同一来源）
    mcp_bindings = current_app.config.get("ASSISTANT_MCP_BINDINGS", [])
    if isinstance(mcp_bindings, list) and mcp_bindings:
        runtime_bindings = build_runtime_bindings_with_identity(mcp_bindings, principal)
        tools.extend(McpToolFactory().get_tools(runtime_bindings))
    return tools
```

**边界**：MCP 装配以运维配置的 `ASSISTANT_MCP_BINDINGS` 为唯一来源（与用户端同一白名单语义）；未配置时默认不装配（保持 admin 链路白名单 fail closed 默认）。调用侧授权由 MCP server 侧按签名还原 principal 后做与 L1 相同的校验（设计 §7.2）——本系统当前无进程内 MCP server，该防线依赖 MCP 通道接收方实现，**诚实标注**。

### 3.4 不做什么（明确排除）

- **不做** MCP server 侧实现（本系统无进程内 MCP server；`verify_principal_token` 仅提供能力，标注未接入）。
- **不做** admin 端的 MCP 绑定管理 UI/API（复用现有 `mcp_service` / `ASSISTANT_MCP_BINDINGS` 配置）。
- **不做** stdio transport 的 header 注入（stdio 无 HTTP header；注入仅对 HTTP 系 transport 生效，stdio binding 加 `_principal_token` 无副作用、不注入）。

## 4. 安全与不变式

| 不变式 | 保证 |
| --- | --- |
| 签名不落库 | `_principal_token` 只存在于装配期运行时副本；快照存的是原始 binding |
| 签名不进 `headers` 列表 | 独立内部字段，规避 `decrypt_headers` 抛错路径 |
| hash 稳定 | `_binding_hash` 计算前剥离下划线开头内部字段 |
| 权限实时重算不被绕过 | token 不含权限快照；server 侧凭 agent_id 走 `AdminAgentService.get_principal`（同 L1 入口） |
| 不污染原绑定 | `build_runtime_bindings_with_identity` 构造副本 |
| fail closed 默认 | 未配置 `ASSISTANT_MCP_BINDINGS` 时 admin 链路不装配 MCP |

## 5. 测试计划（TDD：先红后绿）

| 测试文件 | 断言 |
| --- | --- |
| `api/test/internal/core/test_admin_agent_mcp_identity.py`（新增） | `sign_principal_token` 可用 `JwtService.parse_token` 解析且含 admin_user_id/agent_id/agent_name/iat/exp；**不含**权限/自动化策略字段；`build_runtime_bindings_with_identity` 注入 `_principal_token` 且**不修改原 binding**（原 dict 无内部字段）；`verify_principal_token` 往返还原 payload |
| `api/test/internal/core/tools/mcp_tools/test_mcp_tool_factory_identity.py`（新增） | `_binding_hash` 对「含 `_principal_token` 的 binding」与「剥离后的同一 binding」产出**相同 hash**；`_jsonrpc_request` 带 `_principal_token` 时请求头含 `X-Admin-Agent-Principal`（mock `requests.Session.post` 断言 headers）；不带时不加 |
| `api/test/internal/service/test_admin_agent_chat_service.py`（扩展） | 配置 `ASSISTANT_MCP_BINDINGS` 时 `_build_tools` 返回板块工具 + MCP 工具；未配置时无 MCP 工具 |

## 6. 接线审查（完成时逐项点名入口）

- `sign_principal_token` 入口：`build_runtime_bindings_with_identity` → `_build_tools` → `AdminAgentChatService.chat` → `POST /admin/agents/<id>/chat`（SSE）。
- `_principal_token` 读取点：`McpToolFactory._jsonrpc_request`（工具调用热路径，`tools/call`）。
- hash 剥离点：`McpToolFactory._binding_hash`（快照刷新 `tools/list` 比对路径）。
- `verify_principal_token`：**无消费方** → 回复与文档标注「已提供能力但未接入」。

## 7. 文档同步清单

- `docs/prd/execution-roadmap.md`：ADMIN-P5 标记完成；ADMIN-P2 节「未落地：MCP 动态身份注入」更新为已落地。
- `docs/prd/extensibility-design.md`（或 `modules/01-agent-tool-pool.md`）：补「MCP 动态身份注入」机制一节。
- `docs/README.md`：无需新增顶层文档（无新导航项）。
- `python -m graphify update .`

## 8. 提交纪律

- TDD：先提交失败测试（红）→ 实现 → 绿。用**显式 pathspec** `git add <file>...`。
- commit message 带阶段标识：`（ADMIN-P5 Task N）`。
