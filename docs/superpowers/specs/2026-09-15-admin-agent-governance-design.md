# 管理端 Agent 自动化治理设计

> **状态**：需求已逐项确认，设计待评审。地基缺陷已修复（见 §12）。
> **日期**：2026-09-15
> **主文档**：[architecture-design.md](../../prd/architecture-design.md) | [01-agent-tool-pool.md](../../prd/modules/01-agent-tool-pool.md) | [rbac.md](../../rbac.md)

## 1. 背景与目标

管理端与用户端账号已彻底解耦（`admin_user.account_id` 恒为 `NULL`，管理员 JWT 访问用户端接口 403）。在此基础上，产品需要让**管理端也能调用 Agent 能力**，用于后续把部分简单板块交给系统 Agent 自动治理。

**四条硬约束**（来自产品诉求）：

1. **账号隔离**：管理员账号绝不与用户端混用，管理员若要用用户侧功能须走用户端注册。
2. **边界强制**：admin Agent **不能碰到用户端的内容**，只能操作 admin 端**被授权**的板块与内容。
3. **权限不放大**：Agent 默认不继承管理员的全部权限；只有管理员**显式下放**给他的权限子集，Agent 才能在该范围干活。
4. **成本系统承担**：admin Agent 的模型调用成本统一由系统承担，不记入任何用户配额。

**目标**：建立一套可证明、可审计、可撤回的管理端 Agent 授权与执行体系。

## 2. 已确认的设计决策

| 议题 | 决策 |
| --- | --- |
| 边界强制层 | **分层**：Agent 执行层做安全底座，MCP 做工具化封装 |
| 执行身份模型 | **显式 `AdminAgentPrincipal`**，全链路传递，不用 Account 伪装 |
| 授权粒度 | **继承 ∩ 显式下放**：`admin.permissions ∩ agent.granted_permissions ∩ ASSIGNABLE` |
| 可分配列表展示 | **展示即受限**：API 只返回交集，UI 不展示管理员没有的权限点 |
| 权限回收 | **自动清理**：管理员失权时立即从 Agent 清单物理删除该项 |
| 写操作闸门 | **按板块分级自动化**（`supervised` / `autonomous` / `blocked`），核心板块需人工授权 |
| 删除类操作 | **全自动 + 必进回收站**（需扩展回收站语义以容纳 admin 专属资源的 Agent 代删，见 §7.1） |
| 变更草稿 | **泛化现有 `policy_change_draft` 为通用 admin 变更草稿**（该表是 admin 治理基础设施，非用户业务表；字段通用，仅 `suggestion_id`/`policy_type` 需放宽） |
| 用户域边界 | 由管理员**自己授予**权限决定，系统只封禁 RBAC 板块 |
| RBAC 封禁范围 | 封禁 `admin:access` / `admin_user:*` / `role:*` / `permission:read`；`user:*` 仅 `user:read` 可下放 |
| 工具粒度 | **板块级聚合**（一个板块一个工具，内部按 action 分支） |
| Agent 数量 | **管理员多 Agent**（一个管理员可创建多个不同职责的 Agent） |
| Agent 归属 | **仅创建者可用**（`owner_admin_user_id`，他人不可见不可调） |
| 调用入口 | **对话式（`/admin/agents`）+ 定时任务** 双入口 |
| 执行链路 | **新建管理端专用链路**，不复用用户端 `chat()` |
| 提示词存放 | **YAML seed + admin 可编辑**（遵循 AGENTS.md 强制规则） |
| 成本闸门 | **需要预算闸门**（单次 token 上限 + 周期累计额度） |
| 定时绑定 | `schedule_task` **新增 `agent_id`** 字段 |
| 记忆隔离 | **按 Agent 隔离**（`admin_user_id` + `agent_id` 两级） |
| 记忆主体抽象 | **统一主体抽象**（对齐知识库三字段模式） |
| 存量数据 | **新数据独立 + 清理存量**（无法归因的旧数据删除） |
| MCP 动态身份 | **方案 A**：进程内 MCP + 装配期动态签名 |

## 3. 整体架构

```text
┌──────────────────────────────────────────────────────────────────┐
│ L5  入口层                                                        │
│   · 对话式：/admin/agents（选 Agent → 对话 → 它调已授权板块工具）    │
│   · 定时：schedule_task.agent_id（owner_type='admin'）            │
├──────────────────────────────────────────────────────────────────┤
│ L4  身份层                                                        │
│   AdminAgentPrincipal{admin_user_id, agent_id, effective_perms}   │
│   —— 显式入参，全链路携带，不用 Account 伪装                        │
├──────────────────────────────────────────────────────────────────┤
│ L3  授权层                                                        │
│   effective = admin.permissions ∩ agent.granted_permissions       │
│               ∩ ASSIGNABLE_PERMISSIONS                            │
├──────────────────────────────────────────────────────────────────┤
│ L2  能力层                                                        │
│   · 板块级聚合工具（admin_<board>(action=...))                     │
│   · 每请求身份的 MCP 通道（动态签名 header）                       │
├──────────────────────────────────────────────────────────────────┤
│ L1  执行层  AdminAgentService（独立链路）                          │
│   · 记忆：按 admin_user_id + agent_id 隔离                        │
│   · 计费：billable=false → 系统承担（含预算闸门）                   │
│   · 审计：actor_type=agent + agent_id + admin_user_id             │
└──────────────────────────────────────────────────────────────────┘
```

## 4. L3 授权层（核心安全模型）

### 4.1 三重交集

```python
effective = (
    set(admin.permissions)              # 发起管理员的实时权限
    & set(agent.granted_permissions)    # 管理员显式下放给该 Agent 的子集
    & ASSIGNABLE_PERMISSIONS            # 系统允许下放的白名单
)
```

三者缺一不可。任一维度收紧，Agent 能力立即随之收紧。

### 4.2 ASSIGNABLE_PERMISSIONS：可下放白名单

基于 `api/internal/core/rbac.py` 的 `PERMISSION_CATALOG`（实测 **99** 个权限点）：

| 处置 | 权限点 | 数量 | 理由 |
| --- | --- | --- | --- |
| **完全封禁** | `admin:access`、`admin_user:read/create/update/disable`、`role:read/create/update/delete`、`permission:read` | 10 | 身份与权限体系。下放等于 Agent 能自我提权、改角色、改他人账号，安全模型自我解体 |
| **仅只读** | `user:read`（可下放）；`user:create/update/disable/delete` **不可下放** | 1 / 4 | 用户管理只读；写操作影响真实用户，归为禁区 |
| **可下放** | 其余全部 | 85 | 模型池、公共 AI、提示词、工具治理、子池、编排开关、路由、成本、存储、套餐、卡密、订单、售后、提现、支付、回收站、MCP、应用、工作流、知识库、定时任务等 |

**约束**：白名单以 `resource` 前缀判定，新增权限点默认**不可下放**（fail closed），需显式登记才进入白名单——避免未来新增权限点被静默暴露给 Agent。

### 4.3 展示即受限（关键）

管理员的可分配列表**本身就是交集结果**，不是全量目录：

```python
# GET /admin/agents/assignable-permissions
return sorted(set(admin.permissions) & ASSIGNABLE_PERMISSIONS)
```

**三层强制**，任何一层都不能省：

| 层 | 行为 | 目的 |
| --- | --- | --- |
| **展示** | API 返回交集，UI 只渲染该列表 | 管理员看不到自己没有的权限点，无从选择 |
| **保存** | 后端独立校验 `granted ⊆ (admin.permissions ∩ ASSIGNABLE)` | UI 过滤是体验，**不是安全边界**；直连 API 绕过 UI 必须被拒 |
| **运行** | 每次请求实时重算 `effective` | 与 `docs/rbac.md` §3.5 的既有原则一致（不依赖静态快照，角色调整即时生效） |

**举例**（A 管理员只有模型池/工具池/Agent 池）：

```text
A 的权限：model_pool:read/manage、agent_pool:read/manage、
          tool_governance:read/manage

GET /admin/agents/assignable-permissions
  → 只有这 6 项
  ├─ 不含 user:*、order:*、plan:*……（A 没有）
  └─ 不含 role:*、permission:read、admin_user:*（系统封禁，即使 A 有也剔除）

A 创建 Agent X，勾选其中 4 项 → X.granted = 那 4 项
X 执行时 effective = A的6项 ∩ X的4项 ∩ ASSIGNABLE = 那 4 项
```

### 4.4 权限回收：自动清理

管理员失去某权限时，系统**立即从该管理员名下所有 Agent 的 `granted_permissions` 中物理删除该项**。

- 理由：不留"显示有、实际无效"的混乱状态（否则管理员会困惑"为什么 Agent 不干活了"，排查成本高）。
- 代价：管理员重新获得权限后需**手动重新下放**——这是可接受且更安全的取舍。
- 触发点：`AdminRbacService` 的角色/权限变更路径，以及管理员账号禁用/删除路径。

## 5. L4 身份层

```python
@dataclass(frozen=True)
class AdminAgentPrincipal:
    """管理端 Agent 的显式执行身份。"""
    admin_user_id: UUID          # 发起管理员（人类责任人）
    agent_id: UUID               # 执行该操作的 Agent
    agent_name: str              # 审计展示用
    effective_permissions: frozenset[str]   # 已算好的三重交集
    automation_policy: Mapping[str, str]    # 板块 → supervised / autonomous / blocked（§5.1）
```

**设计要点**：

- **不复用 `Account`**：管理员与用户端账号彻底解耦，用 Account 伪装会让下游所有"按 account 隔离"的逻辑误判主体。
- **不沿用 `_SystemBorneAccount` 的做法**：现有 4 个管理端 AI 辅助端点用 `_SystemBorneAccount(id=None)` 丢弃了管理员身份。新链路必须保留身份，否则无法做板块授权，也无法回答"谁让 AI 改了什么"。
- **显式入参**：沿 `AdminAgentService → 工具构造 → 工具执行 → 审计` 全链路传递，不做隐式上下文读取（易漏、难测）。

### 5.1 自动化级别（与权限正交的第二维度）

> 放在身份层，是因为该策略由 `AdminAgentPrincipal` 承载并随请求下传；语义上它介于授权（L3）与能力（L2）之间。

**权限**与**自动化级别**是两个正交维度，必须分开建模：

| 维度 | 回答的问题 | 载体 |
| --- | --- | --- |
| 权限 | Agent **能不能碰**这个板块 | `agent.granted_permissions`（§4） |
| **自动化级别** | 碰的时候**要不要等人** | `agent.automation_policy`（本节） |

只做权限会导致一个两难：给核心板块授权则 Agent 可直写生产配置（风险高），不给则 Agent 无法自动化（价值低）。引入自动化级别后，**"可授权"与"可直接执行"解耦**——核心板块可以被授权，但执行前需人工放行。

```python
# admin_agent 表新增
automation_policy = Column(JSONB, nullable=False, server_default="{}")
# 形如 {"model_pool": "supervised", "prompt_template": "autonomous"}
```

**三档级别**：

| 级别 | 行为 | 适用板块 |
| --- | --- | --- |
| `supervised`（需授权） | Agent 产出**变更草稿**（before/after/diff/impact → 人工点「应用」才落库） | 核心板块：模型池、模型供应商、支付配置、套餐、密钥类 |
| `autonomous`（全自动） | Agent 直接执行，靠**审计 + 回收站 + 快照**兜底 | 非核心板块：提示词、子池定义、编排开关、路由调优、工具治理 |
| `blocked`（禁用） | 即使有权限也不执行（临时熔断某板块） | 任意板块的应急开关 |

**fail closed**：`automation_policy` 未配置某板块时，默认为 `supervised`；未配置预算的 Agent 不可执行（§6.3）。避免"忘记配置 = 全自动"。

**复用的两个既有机制**：

1. **回收站**：删除类必须可恢复。注意既有 `deleted_by_type="agent"` **不能直接用于 admin 板块资源**（取值域限制，详见 §7.1），需扩展。
2. **快照**：写前自动快照、可回滚。

> **命名说明**：本机文件操作三件套（`os_file_task` / `os_recycle_bin` / `os_snapshot`）位于 `api/internal/core/tools/builtin_tools/providers/host_os/`，provider name 为 `host_os`（展示名"本机文件操作"）。该 provider 原名 `codex_os`，已随目录一并更正（迁移 `q3d4e5f6a7b8`）——原 Codex CLI 链路（`run_os_task` + worker `/run` 端点 + `delete_guard`）已于 2026-09-08 **整体移除**，原因是 Codex 强依赖 OpenAI（ChatGPT 登录/API key + 地区限制），ToC 不可行；现存三件套是**纯 Python 自研**，与 Codex 无任何关系。
>
> 供参考的实现依据：`assistant_agent_service.py` 的注释写明"*删除类操作（`os_recycle_bin` / 纯删除补丁）已全部走本机回收站，可随时恢复；写操作（`os_file_task`）写前自动快照，改错可用 `os_snapshot` 回滚。因此 agent 可全自动执行而无需用户逐次确认*"。本设计把该思路从 OS 自动化**推广到 admin 板块治理**——即"用可恢复性替代逐次人工确认"。

### 5.2 通用变更草稿（supervised 档的载体）

`supervised` 档需要"产出草稿 → 人工应用 → 可回滚"的能力。仓库已有现成实现 `PolicyChangeDraftModel`（`policy_change_draft` 表），其字段结构**天然是通用的**：

| 字段 | 用途 |
| --- | --- |
| `before_config` / `after_config` | 变更前后配置（JSONB） |
| `diff` / `impact` | 差异与影响面 |
| `status` | `pending` / `applied` / `rolled_back` |
| `applied_by` / `applied_at` | 人类批准者与时间 |
| `rolled_back_at` / `rollback_reason` | 回滚轨迹 |

**抽象方向（已定：泛化现有表，不新建）**：把它提升为**通用 admin 变更草稿**，各板块的 `supervised` 操作统一走这条通道。

**定性依据**（实测）：

| 判定项 | 结果 |
| --- | --- |
| 是否用户侧表 | **否**——全仓仅 admin 侧消费（端点全在 `/admin/routing-quality/policy-changes*`，`support.py` 要求 `routing_quality:*`） |
| 是否有用户维度字段 | **无**——全表只有 `applied_by`（admin_user_id），无 `account_id` / `user_id` |
| 字段是否通用 | **是**——`before_config` / `after_config` / `diff` / `impact` / `status` / `applied_by` / `rolled_back_at` 与路由业务无关 |
| 耦合点 | `suggestion_id`（**NOT NULL**，FK 指向 `routing_optimization_suggestion`）+ `policy_type` 取值（`model_routing` / `tool_policy` / `agent_policy`） |

由于它是 **admin 治理基础设施**（非用户业务表，不存在污染用户域的问题），且字段天然通用，故**选择泛化而非新建**——避免在 admin 侧并存两套草稿表造成基础设施重复。

**泛化内容**：

- `suggestion_id` 改为**可空**（通用草稿可不来自路由建议）。
- `policy_type` 语义扩展为**板块标识**（承载任意 admin 板块，如 `model_pool` / `prompt_template`），路由三个既有取值保持兼容。
- 类名/表名可择机改为 `AdminChangeDraftModel` / `admin_change_draft`（若改名，需同步 `routing_policy_change_service.py`、`internal/model/__init__.py` 与相关测试）。
- 事务边界与回滚语义不变（已有 `rollback_draft` 可复用）。

**收益**：

- 一套机制服务所有核心板块，避免逐板块自造审批流。
- 单一审核入口（管理员在一个页面处理所有待应用的 Agent 变更）。
- 统一审计：`applied_by` 记录人类批准者，与 `audit_log.actor_type=agent` 配合，可完整还原"Agent 提议 → 人类批准"链路。
- 存量路由草稿数据天然延续，无需数据搬迁。

## 6. L1 执行层

### 6.1 为什么新建独立链路

`AssistantAgentService._build_assistant_runtime_tools()` 是**用户域固有工具的唯一总装点**，它按用户身份装配 `create_app`、本机文件操作三件套（`os_file_task` / `os_recycle_bin` / `os_snapshot`，见 §5.1 命名澄清）、`computer_control`、浏览器自动化、`audio`、`code_execution`、`vision`、`todo`、用户知识库检索、`skill_detail`、Agent 主动记忆策展（`agent_memory`）等工具，以及经 `ASSISTANT_MCP_BINDINGS` 注入的全局 MCP。

关键点：这些工具是**条件装配**的（逐个包在 `try` 块内、部分受功能开关与运行上下文 `has_app_context()` 约束），**实际数量随配置动态变化**，不存在固定条数。复用它做 admin 链路只能靠**黑名单排除用户域工具**，而黑名单对"随配置动态增减"的工具集是不完备的——**漏一个就是越权**。

新建 `AdminAgentService` 只装配 admin 板块工具（白名单式，未登记即不装配），边界可自证。代价是编排/SSE/计费部分逻辑需与用户端共享或复制，接受该成本。

### 6.2 计费

- `billable=False` → `CreditService.consume_for_feature` 走 `system_borne` 短路，不扣用户额度。
- 复用既有 feature 注册机制：在 `PublicAIFeatureService._BUILTIN_FEATURES` 注册 admin Agent 的 `feature_key`，管理员在 `/admin/public-ai-features` 为其绑定模型与档位。

### 6.3 预算闸门

系统承担成本**不等于无上限**。每个 admin Agent 配置：

| 维度 | 说明 |
| --- | --- |
| 单次调用 token 上限 | 防单轮失控 |
| 周期累计额度（日/周） | 防定时任务陷入循环无上限烧钱 |
| 超限行为 | 拒绝执行（fail closed）或降档，二者可配 |

未配置预算的 Agent 默认**不可执行**（fail closed），避免"忘记配置 = 无限额度"。

## 7. L2 能力层

### 7.1 板块级聚合工具

一个板块一个工具，内部按 `action` 分支：

```python
admin_sub_pool_definitions(action="list" | "create" | "update" | "delete", payload={...})
admin_public_ai_features(action="list" | "update", ...)
admin_model_pool(...)
admin_prompt_templates(...)
admin_tool_governance(...)
admin_orchestration_flags(...)
admin_routing_logs(...)
admin_cost_policies(...)
admin_storage(...)
admin_plans(...)
...
```

**选型理由**：板块级聚合使工具数量可控（admin 有上百个端点，端点级会让工具数远超 `selected_tools` 上限、拉低 LLM 选择准确率），且天然契合"板块被授权"的语义。

**执行四步**：

1. 校验 `principal.effective_permissions` 含该 action 所需权限点（不足 → 拒绝并记审计）。
2. 解析该板块的**自动化级别**（见 §5.1）：`blocked` → 拒绝；`supervised` → 转入变更草稿；`autonomous` → 继续第 3 步。
3. 调对应 service（service 层不感知 Agent，保持纯粹）。
4. 写审计（带 `actor_type` / `agent_id` / `admin_user_id`）。

删除类走回收站，但**不能简单复用 `deleted_by_type="agent"`**——核实后该取值有硬约束：

| 约束 | 代码位置 | 含义 |
| --- | --- | --- |
| `agent` 来源仅允许 `USER_VISIBLE_RESOURCE_TYPES`（`knowledge_base` / `knowledge_document` / `os_file` / `schedule_task` / `external_data_source` / `conversation` / `memory`） | `recycle_bin_service.py` 的 `delete_resource()` 会 `raise ValidateErrorException` | **admin 板块资源**（`app` / `workflow` / `skill` / `mcp` / `api_tool` / `system_prompt` / `upload_file`）**无法以 `agent` 来源入站** |
| `agent` 来源固定留存 7 天（`AGENT_RETENTION_DAYS = 7`，忽略传入的 `retention_days`） | 同上 | 留存策略不可配 |
| `ADMIN_ONLY_RESOURCE_TYPES` = `RESOURCE_TYPES` − `USER_VISIBLE_RESOURCE_TYPES` | 模块末尾派生 | admin 专属资源只走 `deleted_by_type="admin"` |

**因此本设计需要扩展回收站语义**（列为 P1 的一项改动）：

- 新增 `deleted_by_type="admin_agent"`（或在 `agent` 基础上放开 admin 专属资源类型），使 Agent 代删的 **admin 板块资源**同样可入站、可恢复、可区分来源。
- `agent_id` 已有写入机制（`snapshot["_agent_id"]`），可直接复用于审计"哪个 Agent 删的"。
- 留存期建议对 `admin_agent` 单独设值（admin 专属资源默认 30 天更合理，而非 7 天）。
- **前提**：需同步迁移 `recycle_bin.deleted_by_type` 的取值约束与 admin 端列表/恢复查询，并补测试覆盖"admin 专属资源 + Agent 来源"这一组合（当前该组合会抛错）。

### 7.2 MCP 动态身份注入

**机理核实（已推翻初版判断）**：

初版设计称"动态签名会导致快照永远失效"，经核实**该结论不成立**，真实机理如下：

| # | 事实 | 影响 |
| --- | --- | --- |
| 1 | `_build_langchain_tool(binding, tool_definition)` 传入的 `binding` 是 `get_tools()` 的**实时入参**；快照内的 `binding` 字段**仅用于身份匹配与 hash 比对**，不参与工具构造 | 动态 header **无需进快照即可生效** |
| 2 | 只有 `refresh_binding_snapshots`（`tools/list` 探测）比对 hash；工具**调用**（`tools/call`）不看 hash | hash 失配的代价仅为周期性多打一次 `tools/list`，**不在会话热路径**，非阻塞问题 |
| 3 | `_build_snapshot_payload` 会把 `normalized_binding` **整体持久化**进 `app_config.mcp_tool_snapshots`（DB JSONB） | **真风险**：动态签名若进 binding 会**明文落库** |
| 4 | `decrypt_headers` 对每个非空 value 调 `_decrypt_value`，**解密失败直接抛 `ValueError`**（不区分是否密文） | 明文签名 header 会被运行时拒绝——除非先 `encrypt_headers` |
| 5 | `encrypt_headers` 有幂等保护（`_ENCRYPTED_PREFIX = "gAAAAA"` 跳过），但 Fernet 含随机 IV，**同一明文每次密文不同** | 若走加密路线，hash 每次不同 → 快照频繁失效 |

**采用的方案：独立内部字段 + hash 剥离**

```python
# 装配期（AdminAgentService）：构造 binding 副本，签名放独立内部字段
runtime_binding = {**binding, "_principal_token": sign_principal_token(principal)}

# McpToolFactory._jsonrpc_request：读内部字段并加入请求头
if binding.get("_principal_token"):
    headers["X-Admin-Agent-Principal"] = binding["_principal_token"]

# McpToolFactory._binding_hash：计算前剥离下划线开头的内部字段
payload = {k: v for k, v in binding.items() if not k.startswith("_")}
```

**为什么这样最好**：

- 不污染既有 `headers` 语义（`headers` 在库中存的是**加密后的静态凭证**，混入动态值会破坏其不变量）。
- 不触发 `decrypt_headers` 的抛错路径（内部字段不在 `headers` 列表里）。
- 不落库（快照存的是原始 binding，内部字段只存在于装配期的运行时副本）。
- hash 稳定（内部字段在计算前被剥离），快照复用不受影响。
- 代价仅为 `_jsonrpc_request` 与 `_binding_hash` 各加数行。

**MCP server 侧**：验证签名还原 `principal`，再做与 L1 完全相同的权限与自动化级别校验，保证两条通道边界一致。

## 8. 记忆主体统一抽象

记忆系统当前把主体**硬编码为 `Account`**：`user_memory.owner_account_id` 是 `NOT NULL FK → account.id`，写入时强制 `UUID()` 解析；Neo4j 节点用 `user_id = str(account.id)`；`user_memory.scope` 被硬编码为 `"user_memory"` 字面量（**不是**主体作用域）。

**对齐知识库已有的三字段模式**（`knowledge_base` 用 `owner_account_id` + `owner_admin_user_id` + `knowledge_scope` 表达归属）：

| 层 | 现状 | 改后 |
| --- | --- | --- |
| PG `user_memory` | `owner_account_id` NOT NULL FK | `owner_type`(user/admin) + `owner_account_id`(可空) + `owner_admin_user_id`(可空) |
| pgvector 分表 | `owner_account_id` NOT NULL | 同上三字段 |
| Neo4j 节点 | `user_id = str(account.id)` | `owner_key` 复合键：`user:{uuid}` / `admin:{uuid}` |
| Redis | `memory:digest:{user_id}` | `memory:digest:{owner_key}` |
| 检索过滤 | `WHERE owner_account_id = :user_id` | `WHERE owner_key = :owner_key` |
| 冷存储键 | `cold-memories/{user_id}/...` | `cold-memories/{owner_key}/...` |

**隔离粒度**：`admin_user_id` + `agent_id` 两级——每个 admin Agent 一份独立记忆，同一管理员的多个 Agent 互不干扰。

**存量迁移**：全部标 `owner_type='user'`，`owner_account_id` 保持不变，**行为零变化**。

> 这决定了"按不同管理员账号区分记忆"不是加个参数就能做到，必须引入主体类型维度。

## 9. 审计身份（区分人工 vs Agent）

`audit_log` 新增两列：

```python
actor_type = Column(String(16), nullable=False, server_default="human")  # human | agent
agent_id   = Column(UUID, ForeignKey("admin_agent.id"), nullable=True)
```

`admin_user_id` 始终保持为**人类责任人**。于是能精确区分：

| 场景 | 记录 |
| --- | --- |
| A 管理员自己改了 XX | `actor_type=human`、`admin_user_id=A` |
| A 管理员让 AI 改了 XX | `actor_type=agent`、`agent_id=运维Agent`、`admin_user_id=A` |

前端审计页可据此加筛选"只看 AI 操作"。

## 10. 数据表设计

### 10.1 新建表

| 表 | 关键字段 | 说明 |
| --- | --- | --- |
| `admin_agent` | `id`、`owner_admin_user_id`(FK admin_user)、`name`、`description`、`prompt_key`(FK prompt_template)、`granted_permissions`(JSONB)、`automation_policy`(JSONB)、`budget_config`(JSONB)、`enabled`、时间戳 | Agent 定义、能力清单与自动化级别 |
| `admin_agent_conversation` | `id`、`admin_agent_id`、`admin_user_id`、`title`、时间戳 | 独立会话，不混用户表 |
| `admin_agent_message` | `id`、`conversation_id`、`role`、`content`、`tool_calls`(JSONB)、时间戳 | 独立消息 |

### 10.2 修改表

| 表 | 变更 |
| --- | --- |
| `audit_log` | 新增 `actor_type`、`agent_id` |
| `schedule_task` | 新增 `agent_id`（仅 `owner_type='admin'` 时有意义） |
| `user_memory` + `user_memory_embedding_{dim}` | 三字段主体抽象（见 §8） |
| `prompt_template` | 新增 admin Agent 提示词条目（`source=catalog`，YAML seed） |
| `policy_change_draft` | **泛化为通用 admin 变更草稿**（承载 `supervised` 档的待批准变更）：`suggestion_id` 改可空、`policy_type` 语义扩展为板块标识；路由既有取值保持兼容（§5.2） |

### 10.3 提示词（遵循 AGENTS.md 强制规则）

提示词写入 `api/internal/core/prompts/admin_agent/*.yaml` 并在 `index.yaml` 登记 `key`，启动经 `PromptSyncService` 同步到 `prompt_template` 表。运行时读取顺序：**DB（admin 编辑过的 `source=custom`）> YAML seed（兜底）**。预置若干开箱可用的内置 Agent（如运维 Agent、运营 Agent），管理员可编辑或基于内置新建。

## 11. 存量清理

调研盘点出 admin 数据与用户数据共存的表约 **19 张**（另有 Neo4j/pgvector/Redis 等记忆分层）。需区分两类：

- **设计预期**（无需处理）：`knowledge_base` / `knowledge_document` / `knowledge_segment` / `external_data_source` 已用 `owner_account_id` + `owner_admin_user_id` + `knowledge_scope` 三字段正确表达归属；`audit_log` 本就以 `admin_user_id` / `account_id` 分别承载两类主体；`recycle_bin` 有 `deleted_by_type` 区分。
- **真正的混入**（本次处理）：`conversation` / `message` / `message_agent_thought` **完全没有 admin 标识列**，admin 的调试与定时任务只能靠 `invoke_from ∈ {debugger, schedule}` 约定区分；`routing_log.account_id` 为 `NOT NULL`，admin 操作只能借用真实账号。

逐项核实引用关系后的处置：

### 11.1 删除

| # | 数据 | 依据 |
| --- | --- | --- |
| 1 | platform 账号名下记忆（`user_memory` + Neo4j + pgvector） | admin 定时任务间接混入的平台主体记忆，无产品价值 |
| 2 | `invoke_from='schedule'` 的会话/消息 | 用户确认删除 |
| 3 | `routing_log` 中无法归因的 admin 行 | `account_id` NOT NULL 导致原始管理员身份已丢失，无法重新归因 |

### 11.2 保留（不可删）

| # | 数据 | 理由 |
| --- | --- | --- |
| 4 | `invoke_from='debugger'` 的会话/消息 | **是产品功能**：`app.debug_conversation_id` 是 App 的持久调试会话，删除会破坏调试能力 |
| 5 | `upload_file` 中 `account_id IS NULL` 的行 | 是 admin 上传的**应用图标等资源**，被 `app` 引用，删除会导致图标挂掉 |
| 6 | `app` / `workflow` 的 `account_id IS NULL` | 平台级资源，属设计预期（迁移 `e0a1b2c3d4e5`） |
| 7 | `workflow` / `api_tool_provider` 的 `created_by_admin=NULL` | 仅归因字段缺失，非数据污染；可从 `audit_log` 回填 |

### 11.3 连带发现（已修）

- `AgentPolicyFilter` 失效、`workflow.created_by_admin` 恒 `None`、orchestrator 兜底绕过治理——见 §12。

## 12. 地基修复（已完成，本设计的前置条件）

这三处不修，上层边界建在沙子上。

| # | 缺陷 | 根因 | 处置 | 回归防护 |
| --- | --- | --- | --- | --- |
| 1 | `AgentPolicyFilter` 长期静默失效 | `agent_pool_service.py` 中 `collect_raw()` **重复定义**，第二个退化为 `collect()` 的序列化转发，覆盖了保留 `app` ORM 对象的正确实现；过滤器开头 `if app is None: accepted.append(...)` 导致**全部候选无条件放行**，`pool_not_visible` / `agent_disabled` / `risk_level_requires_confirmation` / `cost_level_exceeds_budget` 集体失效 | 删除重复定义 | `test_pool_governance_fixes.py::test_collect_raw_must_preserve_app_object`（**刻意用真实 collector 而非桩**）+ 端到端用例 |
| 2 | `workflow.created_by_admin` 恒为 `None` | `admin_routes_2.py` 引用了**全仓不存在**的 `a._ADMIN_USER_ID` | 改用既有惯例 `a._resolve_admin_operator()`，并补上缺失的 `account` 位置参数 | `test_admin_routes_2.py::test_create_workflow` 断言真实管理员 id |
| 3 | Agent 候选异常兜底绕过治理 | `orchestrator_service.py` 的 `except` 分支 fallback 到 `AgentPoolService.list_agents()`——直读子池清单、**不过滤、不按 account 隔离**，等于异常时静默放行全部 Agent | 改 **fail closed**（异常即空候选），与工具侧 `_build_tool_subset` 一致；同时移除已无消费者的 `agent_pool_service` 依赖注入 | `test_orchestrator_service.py::test_agent_candidate_collection_failure_fails_closed` |

**教训（写测试时需自检）**：第 3 项的回归测试**初版是假通过的**——断言写在 `build_subset_from_candidates` 内部，抛出的 `AssertionError` 被 `decide()` 外层 `except Exception` 吞掉并回退为 `_fallback_decision`，于是"注入不过滤的兜底"它依然通过。改为**记录入参、返回后再断言**才真正生效。这三个缺陷长期潜伏的**共同成因**都是"测试看起来绿、实则没测到真实路径"，因此本设计所有边界规则都要求配套**反向验证**（临时注入违规实现 → 测试必须失败 → 恢复）。

## 13. 风险与待验证

| 风险 | 说明 | 缓解 |
| --- | --- | --- |
| MCP hash 失配 | **核实后已降级**：hash 只在 `refresh_binding_snapshots`（`tools/list` 探测）比对，不在会话热路径；工具调用不看 hash | 签名走独立内部字段 `_principal_token`，`_binding_hash` 计算前剥离下划线开头的内部字段（§7.2） |
| MCP 签名落库 | `_build_snapshot_payload` 会把 binding 整体持久化到 `app_config.mcp_tool_snapshots` | 内部字段只存在于装配期的运行时副本，不进快照 |
| MCP 明文 header 被拒 | `decrypt_headers` 对非空 value 强制解密，失败抛 `ValueError` | 内部字段不在 `headers` 列表中，规避该路径 |
| 记忆主体迁移回归面 | 改 schema + 迁移存量 + 改服务签名（`user_id: str` 遍布检索/巩固/技能/冷存储） | 存量全标 `owner_type='user'`，行为零变化；分阶段：先加字段与双写，再切读路径 |
| `autonomous` 档误判 | 非核心板块全自动，模型误判会直接改坏配置 | 删必进回收站 + 写前快照可回滚；预算闸门；审计可追溯；管理员可随时把板块降为 `supervised`/`blocked` |
| 回收站语义不匹配 | 既有 `deleted_by_type="agent"` 仅允许 7 类用户可见资源，admin 专属资源（app/workflow/skill/mcp/api_tool/system_prompt/upload_file）以该来源入站会**直接抛 `ValidateErrorException`** | §7.1：扩展为 `admin_agent` 来源并放开 admin 专属类型；留存期单设；补该组合的测试 |
| 板块级工具的内部 action 越权 | 工具内部按 action 分支，若校验漏了某个 action 会越权 | 每个 action 显式声明所需权限点，且以"未声明即拒绝"（fail closed）实现 |
| 自动化级别配置遗漏 | 漏配某板块可能被误认为"无限制" | 未配置即 `supervised`（fail closed），并加启动校验/告警 |
| provider 改名后的 DB 残留 | `BuiltinToolSyncService` 以 provider `name` 为键 upsert（**只增不删**）；YAML 改名后启动同步会新建 `host_os` 而残留 `codex_os` 行，旧行 `python_module` 指向已删除目录，命中即 import 失败 | 已实测确认残留（新旧两套并存），由迁移 `q3d4e5f6a7b8` 清理旧行并兜底修正 `python_module` |

## 14. 实施分期建议

| 期 | 内容 | 依赖 |
| --- | --- | --- |
| **P0**（已完成） | 地基修复：`collect_raw`、`_ADMIN_USER_ID`、orchestrator fail closed | — |
| **P1** | `AdminAgentPrincipal` + 授权三重交集 + `admin_agent` 表（含 `automation_policy`）+ 板块级工具 + 审计 `actor_type` + 通用变更草稿（`supervised` 档）+ 回收站 `admin_agent` 来源扩展 | P0 |
| **P2** | 对话式入口（`/admin/agents`）+ 独立会话表 + 提示词 YAML seed | P1 |
| **P3** | 记忆主体统一抽象（含存量迁移）+ 按 Agent 隔离 | P1 |
| **P4** | 预算闸门 + 定时任务 `agent_id` 通道 | P1 |
| **P5** | MCP 动态身份注入（独立内部字段 + hash 剥离，§7.2） | P1、P2 |
| **P6** | 存量清理迁移（§11.1） | P3（记忆改造完成后） |

## 15. 文档同步清单（实施时需同步）

- `docs/rbac.md`：新增管理端 Agent 授权模型与 `ASSIGNABLE_PERMISSIONS` 机制
- `docs/prd/modules/01-agent-tool-pool.md`：`internal_admin` / `system_admin` 池的消费方（当前为"预留未接线"）
- `docs/prd/extensibility-design.md`：板块级工具与 MCP 封装机制
- `docs/prd/modules/02-knowledge-base.md`：记忆主体抽象（与知识库归属对齐）
- `docs/api/*.md`：新增 `/admin/agents/*` 接口契约
- `docs/prd/architecture-design.md`：新增管理端 Agent 治理层
- `docs/README.md`：若新增顶层文档需登记导航
