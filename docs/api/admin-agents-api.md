# 管理端 Agent API

管理端 Agent 治理的对外契约（设计见 [admin-agent-governance-design.md](../superpowers/specs/2026-09-15-admin-agent-governance-design.md)，机制见 [RBAC 权限模型 §9](../rbac.md)）。

- 路由实现：`api/app/http/admin_routes_7.py`
- 权限映射：`api/app/http/support.py` 的 `_admin_route_permission`（`/admin/agents*`：`GET → agent_pool:read`，`POST/PATCH/PUT/DELETE → agent_pool:manage`，未登记方法 fail closed）
- 统一响应包：`{"code": "success"|"validate_error"|"forbidden"|"not_found"|"unauthorized", "message": "...", "data": ...}`

> **鉴权前提**：所有端点都要求管理员 Bearer token；`GET` 走 `agent_pool:read`，写操作走 `agent_pool:manage`。**Agent 定义仅创建者可见/可改**——非属主返回 403，不存在返回 404。
>
> **实现约定（易踩坑）**：`admin["id"]` 由序列化层产出为**字符串**，而 `admin_agent.owner_admin_user_id` 是 **UUID 列**。路由层必须先 `UUID(str(admin["id"]))` 再交给服务，否则服务内 `get_agent` 的纯 Python 属主比较会恒不相等，合法属主也被误判 403。

---

## 1. 可下放权限（展示即受限）

### `GET /admin/agents/assignable-permissions`

权限：`agent_pool:read`

返回**当前管理员实际可下放**的权限点交集（`admin.permissions ∩ ASSIGNABLE_PERMISSIONS`），而非全量权限目录。管理员看不到自己没有的权限点，无从选择。

**响应 `data`**

```json
{ "codes": ["model_pool:read", "builtin_tool:read"] }
```

> 包一层 `codes` 便于日后追加 `total` / 分组字段而不破坏契约。封禁项（身份与权限体系，如 `role:*` / `permission:read` / `admin_user:*`）与未登记 resource 一律不出现在结果中（fail closed，见 `ASSIGNABLE_RESOURCES`）。

---

## 2. 板块与动作清单

### `GET /admin/agents/boards`

权限：`agent_pool:read`

返回已登记的治理板块与动作明细，供前端渲染"这个 Agent 能做什么"。

**响应 `data`**

```json
{
  "boards": ["builtin_tool"],
  "actions": [
    {
      "board": "builtin_tool",
      "action": "list",
      "kind": "read",
      "permission_code": "builtin_tool:read",
      "description": "..."
    }
  ]
}
```

数据源为板块动作注册表 `api/internal/core/admin_agent_boards.py` 的 `BOARD_ACTIONS`（**未登记即拒绝**，fail closed）。

---

## 3. Agent 定义 CRUD

Agent 响应体（`AgentResp`）字段：

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `id` | string(UUID) | Agent ID |
| `name` | string | 名称 |
| `description` | string | 描述 |
| `prompt_key` | string \| null | 绑定的提示词 key（`prompt_template.key`），为空时用内置默认 |
| `granted_permissions` | string[] | 显式下放给该 Agent 的权限子集 |
| `automation_policy` | object | 板块 → `supervised` / `autonomous` / `blocked` |
| `enabled` | bool | 是否启用 |
| `created_at` / `updated_at` | int | 秒级时间戳 |

### `GET /admin/agents`

权限：`agent_pool:read` — 列出**当前管理员自己创建**的 Agent。

**响应 `data`**：`{ "items": [AgentResp, ...] }`

### `POST /admin/agents`

权限：`agent_pool:manage`

**请求体**

| 字段 | 必填 | 说明 |
| --- | --- | --- |
| `name` | 是 | 名称 |
| `description` | 否 | 描述，默认 `""` |
| `prompt_key` | 否 | 提示词 key |
| `granted_permissions` | 否 | 权限子集，默认 `[]` |
| `automation_policy` | 否 | 板块自动化级别，默认 `{}` |

**响应 `data`**：`AgentResp`

**错误**：`400 validate_error` —— 越界下放（管理员自己不具备 / 系统不允许下放的权限点，由 `assert_grantable` 拒绝）或非法自动化级别（由 `_validate_policy` 拒绝）。

### `PATCH /admin/agents/<agent_id>`

权限：`agent_pool:manage` — 未提供的字段保持原值。

**请求体**：以下字段均可选——`name` / `description` / `prompt_key` / `granted_permissions` / `automation_policy` / `enabled`。

**响应 `data`**：`AgentResp`

**错误**：`403 forbidden`（非属主）、`404 not_found`（不存在）、`400 validate_error`（越界下放 / 非法自动化级别）。

### `DELETE /admin/agents/<agent_id>`

权限：`agent_pool:manage` — 仅创建者可删除。物理删除。

**响应**：`data` 为 `null`，`message` 为 `删除 Agent 成功`

**错误**：`403 forbidden`（非属主）、`404 not_found`（不存在）。

---

## 4. 执行板块动作

### `POST /admin/agents/<agent_id>/invoke`

权限：`agent_pool:manage`（执行入口代表"让 Agent 在后台动手"，不接受只读权限触发）

**请求体**

| 字段 | 必填 | 说明 |
| --- | --- | --- |
| `board` | 是 | 板块标识 |
| `action` | 是 | 动作标识 |
| `payload` | 否 | 动作入参，默认 `{}` |

**响应 `data`**

```json
{ "outcome": "executed", "result": { "...": "..." }, "draft_id": null }
```

`outcome` 取值：

| 值 | 含义 |
| --- | --- |
| `executed` | 已真实执行（只读动作，或 `autonomous` 档写动作） |
| `drafted` | **未执行**，已产出变更草稿等待人工批准（`supervised` 档） |

执行链路：校验 `effective_permissions` 含该 action 所需权限点且判 `blocked` 熔断 → 按 `automation_policy` 分流 → 调板块实现体 → 写审计（`actor_type=agent` + `agent_id` + `admin_user_id`）。

**错误**：`403 forbidden`（权限不足 / Agent 已停用 / 非属主；被拒动作以 `admin_agent.<board>.<action>.denied` 记审计）、`404 not_found`（Agent 不存在）、`400 validate_error`（`board` / `action` 未登记等）。

---

## 5. 待应用变更草稿

### `GET /admin/agents/<agent_id>/drafts`

权限：`agent_pool:read`

列出该 Agent 产出的**待应用**变更草稿（按 `impact.agent_id` 做归属隔离），供后台「待批准变更」消费。

**响应 `data`**

```json
{
  "items": [
    {
      "id": "…",
      "policy_type": "builtin_tool",
      "target_id": "…",
      "before_config": {},
      "after_config": {},
      "diff": {},
      "impact": { "agent_id": "…" },
      "status": "pending",
      "created_at": 1789200000
    }
  ]
}
```

**错误**：`403 forbidden`（非属主）、`404 not_found`（Agent 不存在）。

> **未接入项（明确标注）**：草稿的 `apply` / `rollback`（`AdminChangeDraftService.apply_draft` / `rollback_draft`）已提供能力，但「待批准变更」前端页与对应路由属后续阶段，当前只有测试调用。

---

## 6. 对话与会话

### `POST /admin/agents/<agent_id>/chat`

权限：`agent_pool:manage`（发起对话 = 让 Agent 动起来，不接受只读权限触发）

**请求体**：`{"query": "看看内置工具现状", "conversation_id": "<可选，续聊时传 UUID>"}`

**响应**：`text/event-stream`，逐帧格式 `event: <name>\ndata:<json>\n\n`：

| `event` | `data` | 说明 |
| --- | --- | --- |
| `message` | `{"conversation_id": "..."}` | 会话已建立/复用 |
| `tool` | `{"call": {"name","args","id"}, "result": "<JSON 字符串>"}` | 一次板块工具调用及结果 |
| `answer` | `{"answer": "..."}` | 最终答复 |
| `error` | `{"error": "..."}` | 可读错误 |
| `end` | `{}` | 流结束 |

链路：解析 `AdminAgentPrincipal`（三重交集实时重算）→ 取/建会话 → 系统提示词
（Agent 的 `prompt_key`，缺省 `admin_agent_board_agent`）→ 装配板块工具（每板块一个）
→ 工具循环（上限 6 轮）→ 落库 → SSE。写动作仍按 `automation_policy` 分流
（`supervised` 产待批准草稿）。

**逐帧推送**：`tool` 帧在工具循环**进行中**即时产出（每完成一次工具调用即推一帧），
不等循环结束一次性补帧——循环最长 6 轮、单轮可能是分钟级，集中补帧会让前端在此期间
只见 keep-alive。落库顺序仍为 `user → tool → assistant`。

**工具失败不中断对话**：工具入参非法（`action` 缺失 / `payload` 非 dict 等，由
`args_schema` 在进入工具 `_run` 之前校验并抛 `ValidationError`）与业务拒绝（无权限 /
未登记动作 / 板块未实现）一样，都以**可读 JSON** 作为该次 `tool` 帧的 `result` 回给
模型（形如 `{"ok": false, "board": ..., "error": "入参不合法: ..."}`），模型可据实改正
后重试，不产生 error 帧、不中断整轮。

**失败语义（重要）**：本端点**一旦通过 HTTP 鉴权就恒返回 `200` + `text/event-stream`**，
业务失败在 **SSE 帧内**表达为 `event: error`。即「非属主 / Agent 已停用 / 提示词缺失 /
feature 未启用 / 会话不属于该 Agent（续聊传了别个 Agent 的 `conversation_id`）/
工具循环超轮次不收敛」都不会产生 HTTP 403/404/500，而是 error 帧——
这是刻意的：`support._sse_response` 会把逃出生成器的异常改写成**另一套** payload 结构
（`event: <failure_event>` + `observation`），破坏本链路契约，故服务层把可预期异常
统一转为本链路的 error 帧。

唯一的 HTTP 层 `400 validate_error`：**请求体结构非法**——body 里**缺失 `query` key**
（或为 `null`，schema `required=True` 校验失败），或 `conversation_id` 不是合法 UUID。
两者都发生在体参数校验阶段，尚未进入服务层。

> **注意区分 `query` 的两种「空」**：缺 key → 400；`query` 为空字符串（或纯空白）是
> **合法请求**，走 200 + SSE，服务层在帧内以 `event: error`（内容「消息不能为空」）
> 收尾。原因：HTTP 400 只留给「请求体结构非法」，而「用户确实发了空消息」是业务结论，
> 与其余业务失败保持同一套帧解析逻辑。

### `GET /admin/agents/<agent_id>/conversations`

权限：`agent_pool:read` — 列出该 Agent 的会话（先经 `get_agent` 校验归属）。

**响应 `data`**：`{"items": [{"id","admin_agent_id","title","created_at","updated_at"}]}`

**错误**：`403 forbidden`（非属主 —— `AdminAgentService.get_agent` 抛 `PermissionError`）、
`404 not_found`（Agent 不存在 —— `get_agent` 对不存在**返回 `None` 而非抛错**，
路由显式判空后抛 `NotFoundException`）。

### `GET /admin/agents/conversations/<conversation_id>/messages`

权限：`agent_pool:read` — 列出会话内消息（先经 `get_conversation` 校验会话归属）。

**响应 `data`**：`{"items": [{"id","role","content","tool_calls","created_at"}]}`，
`role ∈ {user, assistant, tool}`；`tool` 角色消息的 `tool_calls` 承载
`{"call": {...}, "result": "..."}`。

**错误**：`403 forbidden`（非会话归属管理员）、`404 not_found`（会话不存在）。

> **多轮上下文说明**：续聊时服务按 LLM 协议还原历史——每个 `tool` 行还原为
> 「携 `tool_calls` 的 assistant 消息 + 对应 `tool` 结果」成对结构；assistant 行
> 只还原文本。若还原成孤立 `tool` 消息，OpenAI 兼容接口会以 4xx 拒收。

---

## 7. 尚未落地

| 能力 | 阶段 |
| --- | --- |
| 管理端前端对话页（后端入口已就绪，见 §6） | 前端任务 |
| 记忆主体统一抽象 + 按 Agent 隔离 | P3 |
| 预算闸门实际执行 + 定时任务 `agent_id` 通道 | P4 |
| MCP 动态身份注入 | P5 |
