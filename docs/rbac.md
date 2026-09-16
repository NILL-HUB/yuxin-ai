# 管理端 RBAC 设计与运维

## 1. 模型

管理端 RBAC 使用经典四表模型：

- `admin_user`：管理员账号，UUID 主键。
- `role`：角色，UUID 主键，`code` 唯一且作为外部稳定标识。
- `permission`：权限点，UUID 主键，`code` 唯一且作为外部稳定标识。
- `admin_user_role` / `role_permission`：管理员-角色、角色-权限绑定。

权限 code 是系统唯一可读标识，例如 `app:read`、`workflow:update`、`recycle_bin:write`。
UUID 只存在于数据库内部；角色与权限的 API 响应、角色标签、权限下拉框均只返回/展示
`code`、`name`、`description` 等可读字段，不再暴露 `id`。

## 2. 权限目录与默认角色

权限目录和默认角色模板的单一事实源位于：

`api/internal/core/rbac.py`

- `PERMISSION_CATALOG`：全部权限点。
- `DEFAULT_ROLES`：内置角色及其默认授权模板。
- `super_admin`：系统保留角色，自动获得全部权限（含未来新增权限）。

默认角色：

| 角色 | 用途 |
| --- | --- |
| `super_admin` | 拥有全部权限，不可修改、不可删除 |
| `operator` | 运营管理员，管理应用、工作流、知识库、工具、用户和日常运营 |
| `finance` | 财务管理员，管理套餐、卡密和收入数据 |
| `support` | 客服人员，查询用户和基础资料 |
| `auditor` | 审核人员，审核资源内容，查看审计日志 |
| `viewer` | 只读观察员 |

## 3. 鉴权门禁

所有 `/admin/*` 请求在 Quart `before_request` 统一经过 RBAC 门禁：

1. `/admin/auth/login` 放行。
2. `/admin/auth/me`、`/admin/auth/logout`、`/admin/auth/password` 只要求有效管理员会话，不要求业务权限。
3. 其余管理端路由按“HTTP 方法 + 路径”解析所需权限 code，权限映射位于 `app/http/support.py` 的 `_admin_route_permission`。
4. 未登记的管理端路径默认拒绝（fail closed），返回 403。
5. 权限校验每次实时读取管理员会话、角色和权限，不依赖 JWT 中的静态权限快照；角色调整即时生效。

路由内不再信任 `X-Admin-Id` 等客户端头作为操作者身份，操作者统一从管理员 token 解析。

## 4. API 契约

角色管理：

- `GET /admin/roles`
- `POST /admin/roles`，入参 `code`、`name`、`description`、`permission_codes`
- `GET /admin/roles/<role_code>`
- `PATCH /admin/roles/<role_code>`，入参 `permission_codes`
- `DELETE /admin/roles/<role_code>`
- `GET /admin/permissions`

管理员管理：

- 创建/更新管理员使用 `role_codes`，响应中的 `roles` 返回角色 code。
- 系统角色不可修改、不可删除；已分配给管理员的自定义角色不可删除。
- 系统始终保留至少一个有效超级管理员。

客户用户管理（`account` 表，admin 对普通用户的完整 CRUD）：

- 端点：`GET/POST /admin/users`（列表/创建）、`GET/PATCH /admin/users/<id>`（详情/更新）、
  `POST /admin/users/<id>/disable|enable|delete`（禁用/启用/删除）、
  `POST /admin/users/<id>/sessions/revoke`（踢下线）。
- 权限：`user:read` / `user:create` / `user:update` / `user:disable` / `user:delete`。
- 状态机：`active`（正常）→ `disabled`（停用，可逆，保留数据，可 `enable` 恢复）；
  `active|disabled` → `deleted`（删除/注销，不可逆，禁止登录）。
- 删除（`deleted`）与停用（`disabled`）的区别：停用可随时恢复且保留全部数据；
  删除是注销语义——吊销全部会话、清理记忆数据（PG `user_memory` + Neo4j 记忆节点）、
  停用名下定时任务、账号不可再登录。`account` 行本身保留（被多表外键引用，
  物理删除不可行且需留存审计），通过 `status='deleted'` + `deleted_at/deleted_by/deleted_reason`
  标记。删除为管理员操作（`user:delete`），操作写入审计日志。
- 管理员绑定的账号不允许在客户用户管理中操作（防误禁管理员）。

## 5. 安全约束

- 超级管理员角色拥有通配权限，不需要随新权限逐个补绑。
- 自定义角色编码禁止使用内置角色 code。
- 角色删除前校验占用，避免悬空授权。
- 管理员不能移除自己的全部角色。
- RBAC 写操作（角色创建/更新/删除、管理员角色变更）写入审计日志，字段使用可读 code。

## 6. 数据同步

- 服务启动初始化与 Alembic 迁移 `c1d2e3f4a5b6_sync_rbac_catalog` 都会幂等同步权限目录、默认角色和默认授权。
- 新增权限只需在 `api/internal/core/rbac.py` 的 `PERMISSION_CATALOG` 增加一项即可，无需手工写 SQL。
- 若需要为默认角色调整模板，修改 `DEFAULT_ROLES` 后执行一次 `AdminRbacService.initialize_defaults()` 或运行数据库迁移。

### 6.1 同步机制的已知边界（重要）

`AdminRbacService.initialize_defaults()` 的三步（`_ensure_permissions` / `_ensure_roles` / `_ensure_default_role_permissions`）是**只增不删**的幂等补齐：

- **权限点只增不减**：`PERMISSION_CATALOG` 中删除某项后，DB 的 `permission` 行**不会**被自动清理，对应 `role_permission` 绑定也会残留，形成孤儿权限。**删除权限/下线功能时必须同步写一条迁移手动清理**（参见 `n8c9d0e1f2a3_drop_app_assignment` 的教训——该迁移删了 `app_assignment` 表却漏删 `app_assignment:read` / `app_assignment:update` 两个权限点，导致 DB 残留 2 个孤儿权限与 4 处角色绑定）。
- **默认角色授权只增不减**：`DEFAULT_ROLES` 中移除某权限后，DB 既有绑定不会被解绑。收缩默认角色权限同样需要迁移处理。
- **`super_admin` 不做权限行级绑定校验**：运行时 `AdminUserService._get_permission_codes()` 对持有 `super_admin` 角色的管理员直接返回 `all_permission_codes()`（代码目录全量），天然覆盖未来新增权限；因此 super_admin 在 `role_permission` 中固化的行数与代码目录数不一致属正常现象，不影响鉴权结果。

**排查用只读语句**（确认是否出现权限漂移）：

```sql
-- 代码目录中有、DB 中缺失（启动同步未生效）
-- 将 PERMISSION_CATALOG 的 code 列表与下句结果对比
SELECT code FROM permission ORDER BY code;

-- DB 中有、代码目录中已无（孤儿权限，需迁移清理）
SELECT p.code FROM permission p
LEFT JOIN role_permission rp ON rp.permission_id = p.id
WHERE p.resource NOT IN (/* 当前 PERMISSION_CATALOG 的 resource 集合 */);
```

## 7. 用户端访问控制（与 RBAC 的分工）

管理端 RBAC 只管 `/admin/*`。普通用户侧另有一套**收敛式封锁**机制，二者互不替代：

- 门禁实现：`api/app/http/support.py` 的 `_is_user_api_blocked()` 与三个前缀集合（`_USER_API_BLOCKED_PREFIXES` / `_USER_API_BLOCKED_WRITE_PREFIXES` / `_USER_API_BLOCKED_READ_PREFIXES`）。
- 语义：用户端已无 UI 消费的接口（`/apps`、`/workflows`、`/api-tools`、`/mcp-providers`、`/skills`、`/builtin-tools` 等资源管理接口，以及 `/memory/write`、`/analysis/`、`/ai/chat` 等）对普通用户 JWT 一律拒绝（写操作全拒、部分只读 GET 也拒）。
- 白名单性质：这是**显式前缀黑名单**，新增用户端接口默认放行，与 admin 侧「未登记即拒绝（fail closed）」相反。新增需封锁的用户端路径时必须同时补进上述集合。
- `/admin` 前缀本身也在 `_USER_API_BLOCKED_PREFIXES` 中，防止用户 token 越权访问管理端。

## 8. 历史缺陷与修复记录

- **已修复（2026-09-14）：`PUT /admin/users/<user_id>/superior` 权限判定被绕过**。
  `_admin_route_permission` 中通用的 `admin/users` 分支先于分销分支返回，导致该端点被判为 `user:update`，拥有 `user:update` 但无分销权限的管理员也能绑定/解绑分销上下级。
  **最终处置：随「管理端与用户端彻底解耦」一并移除该能力，而非收窄权限。** 管理端不提供任何分销能力——分销上下级绑定是**用户端独有**功能，管理员账号不得与用户端混用（管理员若需使用分销，应完全走用户端注册账号）。因此：
  - `api/app/http/admin_commerce_routes.py` 删除 `GET /admin/distribution/overview|relations|commissions` 与 `PUT /admin/users/<user_id>/superior` 四个端点，不再注册任何 `distribution/*` 管理端路由。
  - `api/internal/core/rbac.py` 的 `PERMISSION_CATALOG` 删除 `distribution:view` / `distribution:manage` 两个权限点；因 `initialize_defaults()` 只增不删，另由迁移 `q2c3d4e5f6a7_remove_admin_distribution_permissions.py` 清理 DB 中残留的权限行与 `role_permission` 绑定。
  - 删除 `AdminDistributionService` 与 `AdminCustomerUserService` 的 superior 展示字段；前端移除 `AdminDistributionView.vue`、相关路由/菜单/服务/i18n。
  - `api/app/http/support.py` 对历史路径 `/admin/distribution/*` 与 `/admin/users/<id>/superior` 一律 fail closed（返回 `None` 被拒绝），且该判定先于 `admin/users` 通用分支，避免被重新挂载后静默落到 `user:update` 而获得越权。
  - 分销开关的启停仍由管理端的「编排控制」功能开关（`ENABLE_DISTRIBUTION`）管理——这正是管理员在分销议题上应有的能力边界：**管后端配置，不做用户侧业务关系**。
  - 回归防护见 `api/test/app/http/test_admin_rbac_guard.py::test_admin_distribution_capability_is_removed`。

- **管理员账号与用户端账号彻底解耦（2026-09-14）**。
  管理端只负责后端 admin 管理，不属于用户侧。此前 `support._resolve_account()` 存在「用户 token 解析失败时回落到管理员 JWT」的分支，会让管理员 token 被当作某个用户账号使用，违背账号隔离原则。现已删除该回落分支：**管理员 realm 的 token 访问用户端接口直接 403**（`管理员账号不可访问用户端接口`）。
  管理端确有 4 个 AI 辅助端点（`/ai/optimize-prompt`、`/ai/chat`、`/ai/openapi-schema-chat`、`/ai/mcp-schema-chat`）此前依赖该回落获取身份，现改用 `support._resolve_admin_ai_account()`：仅接受有效管理员 JWT，返回系统身份占位（`id=None`），成本由系统承担、不计入任何用户配额，**绝不回落到用户账号**。

- **补齐管理员删除能力 + 修复 `admin-users` 权限兜底越权（2026-09-16）**。

  管理员管理此前是「CRU + 状态管理」的半成品：有 read/create/update/disable/enable/reset-password/revoke-sessions，**没有删除**——缺权限点、缺服务方法、缺端点、缺软删除列、缺前端入口。同时 `_admin_route_permission` 的 `admin-users` 分支以 `return "admin_user:update"` 兜底，**任何新增方法都会静默继承 update 权限**。

  处置：

  - `api/internal/core/rbac.py` 新增权限点 `admin_user:delete`。`admin_user:*` 此前仅 `super_admin` 实质持有（运行时走 `all_permission_codes()` 短路，`DEFAULT_ROLES` 未授予其它角色），故无需为其它角色补绑。
  - `admin_user` 新增软删除三列 `deleted_at` / `deleted_by` / `deleted_reason`（对齐 `account` 表范式）。**用软删除而非物理删除**：`admin_user.id` 被 `admin_session`、`admin_user_role`、`audit_log`、`knowledge_base.owner_admin_user_id`、`app/workflow/api_tool_provider.created_by_admin` 等多处外键引用，物理删除会触发 FK 约束失败并丢失审计追溯能力。
  - `AdminUserService.delete_admin_user`：置 `status='deleted'` + 记录删除轨迹 + 吊销全部会话 + 写审计（`action=delete`）。业务约束：**不允许删除超管**、**不允许删除自己**、**重复删除被拒**。删除后 `is_active` 为 False，既有的登录与鉴权路径（`password_login` / `_resolve_admin_user_and_session` 均校验 `is_active`）天然拒绝其登录，无需额外改动。
  - `DELETE /admin/admin-users/<id>` 端点（`api/app/http/admin_routes_6.py`），请求体 `{reason?}` 可选。
  - `api/app/http/support.py` 的 `admin-users` 分支：新增 `DELETE → admin_user:delete`，并把兜底 `return "admin_user:update"` 改为 **`return None`（fail closed）**——避免未来新增方法再次静默继承 update 权限。
  - 列表默认过滤 `status='deleted'`（可显式按 `status=deleted` 查询），与 `customer_user` 列表语义一致。
  - 前端 `AdminUsersView.vue` 新增删除按钮（带二次确认 + 删除原因输入），门控 `admin_user:delete`；i18n 中英双端同步。
  - 回归防护见 `api/test/app/http/test_admin_rbac_guard.py::test_delete_admin_user_requires_dedicated_permission` 与 `::test_unregistered_admin_users_method_fails_closed`（二者均已做反向验证：回退到旧的 update 兜底时会失败）、`api/test/internal/service/test_admin_user_service.py` 的 4 个删除用例、`api/test/app/http/test_admin_routes_6.py` 的 2 个端点用例。

## 9. 管理端 Agent 授权模型

管理员可以创建「管理端 Agent」并**显式下放**自己权限的一个子集给它，由 Agent 在管理后台代为执行部分治理动作。本节只描述**授权与身份**机制（P1a 落地范围）；Agent 真正执行板块动作的能力装配属后续阶段，不在本节。

### 9.1 三重交集（生效权限的唯一来源）

Agent 的最终生效权限由三者求交集，**缺一不可**：

```text
effective = admin.permissions ∩ agent.granted_permissions ∩ ASSIGNABLE_PERMISSIONS
```

- `admin.permissions`：发起管理员**当前**持有的权限（人类责任人的权限上限）。
- `agent.granted_permissions`：管理员为该 Agent 显式下放的子集（存于 `admin_agent.granted_permissions`）。
- `ASSIGNABLE_PERMISSIONS`：系统允许下放的权限集合（见 9.2）。

任一维度收紧，Agent 能力立即随之收紧。计算入口为 `api/internal/core/admin_agent_authorization.py` 的 `compute_effective_permissions()`。**每次请求实时重算**，不依赖任何静态快照——与第 3 节鉴权门禁的既有原则一致。

### 9.2 可下放白名单（显式登记制，fail closed）

`ASSIGNABLE_PERMISSIONS` 的**唯一事实源**是 `api/internal/core/admin_agent_authorization.py`（不是 `rbac.py`）：`rbac.py` 是权限点**目录**（纯声明、零逻辑），授权计算是**有行为的安全边界**，二者分开以免"目录"承担两种职责。

本模块采用**显式登记制**（fail closed）：权限点必须满足「resource 在 `ASSIGNABLE_RESOURCES` 中登记」才可下放。**新增权限点若其 resource 是全新前缀，默认不可下放**，必须显式登记才放开。这是针对 `initialize_defaults()`「只增不删」（见 6.1）的防护——新权限点会自动进目录，若白名单是黑名单式实现，它会**静默暴露**给 Agent。

不可下放的类别（机制性说明，具体清单以代码为准）：

| 类别 | 理由 |
|---|---|
| 身份（`admin:access`） | 下放等于 Agent 可进入管理后台体系 |
| 管理员账号（`admin_user:*`） | Agent 可改他人类号 → 安全模型自我解体 |
| 角色（`role:*`） | Agent 可自行造权/提权 |
| 权限点（`permission:read`） | 暴露权限体系全貌 |
| 用户写操作（`user:create/update/disable/delete`） | 影响真实用户；**仅 `user:read` 可下放** |

### 9.3 三层强制（展示 / 保存 / 运行）

UI 过滤只是体验，**不是安全边界**。三层各自独立成立：

1. **展示即受限**：`GET /admin/agents/assignable-permissions` 返回的是**后端算好的交集**，不是"把全量目录交给前端过滤"。
2. **保存校验**：`assert_grantable()` 在落库前拒绝「管理员自己没有」或「系统不允许下放」的权限点——直连 API 绕不过去。
3. **运行时**：每次请求实时重算 effective（9.1）。

三者分别由 `AdminAgentService.list_assignable_permissions` / `assert_grantable` / `compute_effective_permissions` 承担，回归防护见 `api/test/internal/core/test_admin_agent_authorization.py`、`api/test/internal/service/test_admin_agent_service.py`、`api/test/app/http/test_admin_agent_routes.py`（均含反向验证）。

### 9.4 权限回收：自动清理，需手动重新下放

管理员失权后，其名下所有 Agent 中**已失效**的授权项会被**物理删除**（不留"显示有、实际无效"的混乱状态）：

- 「失效」＝ 不在管理员当前权限集中，**或**已不在可下放白名单中。
- 触发点两处（均在 `AdminUserService`）：角色变更 `update_admin_user(role_codes=...)` 后、禁用 `disable_admin_user`（传空权限集，即全部清空）。
- 清理在**同一次事务**中提交（复用同一 session），避免中间态被读到。
- 清理失败**静默降级**（记日志）：角色变更本身已成功，不应因清理失败而回滚主流程。

代价（有意为之的取舍）：管理员重新获得权限后需**手动重新下放**——比"自动恢复"更安全。回归防护见 `api/test/internal/service/test_admin_user_service.py::TestAgentPermissionPruningWiring`（已反向验证：清理退化为空实现时测试失败，可捕获"接好了但没接上"的断链）。

### 9.5 身份对象与自动化级别

- 执行身份用 `AdminAgentPrincipal`（`api/internal/entity/admin_agent_entity.py`），**不可变**且全链路显式传参：`admin_user_id`（人类责任人）+ `agent_id` + `effective_permissions` + `automation_policy`。**不复用 `Account`**（管理员与用户端账号已彻底解耦，见第 8 节）也不复用管理端 AI 辅助的 `_SystemBorneAccount(id=None)`（那会丢弃管理员身份，无法做板块授权、也回答不了"谁让 AI 改了什么"）。
- 自动化级别是与权限**正交**的第二维度（`automation_policy`，按板块配置）：`supervised`（产出草稿待人工点「应用」）/ `autonomous`（全自动，靠审计+回收站兜底）/ `blocked`（应急熔断）。**未配置的板块一律 `supervised`**（fail closed），避免"忘记配置 = 全自动"。

### 9.6 数据与路由

- 表 `admin_agent`（迁移 `s5f6a7b8c9d0_add_admin_agent_table`）：归属 `admin_user`（`ON DELETE CASCADE`），**不归属 `account`**；含 `granted_permissions` / `automation_policy` / `budget_config`（JSONB，均有空默认值）。
- 路由 `/admin/agents*` 登记在 `api/app/http/support.py` 的 `_admin_route_permission`：`GET → agent_pool:read`，`POST/PATCH/PUT/DELETE → agent_pool:manage`，**未登记方法 fail closed 返回 `None`**。新路由必须登记，否则 `test_admin_rbac_guard.py::test_every_registered_admin_route_has_a_permission` 失败。

### 9.7 板块工具与执行分流（P1b）

授权（9.1-9.4）解决「Agent 能不能碰」，执行层解决「碰的时候要不要等人」。

**板块动作注册表**：`api/internal/core/admin_agent_boards.py` 是「板块动作 → 所需权限点」的**唯一事实源**（`BOARD_ACTIONS` / `resolve_action()` / `board_ids_of()` / `boards()`）。采用**显式登记制**：未声明的 `(board, action)` 一律抛 `ValueError`——工具内部按 action 分支，漏声明必须表现为明确报错而非静默放行。`BOARD_IDS` 由 `BOARD_ACTIONS` 派生，禁止手工维护两个清单。`is_write` 区分只读/写/删：**只读动作不进变更草稿**（否则 `supervised` 档的 Agent 连列表都查不了）。

**执行四步**（`AdminAgentExecutionService.run`，`api/internal/service/admin_agent_execution_service.py`）：

| 步 | 行为 | 失败处置 |
|---|---|---|
| 1 | 校验 `principal.effective_permissions` 含该 action 所需权限点；判 `blocked` 熔断 | 拒绝**并记审计**（action 后缀 `.denied`，让"被挡住的动作"也可追溯） |
| 2 | 按 `automation_policy` 分流：`supervised` → 产变更草稿（**不执行**）/ `autonomous` → 继续 / `blocked` → 已在第 1 步拒绝 | 未配置板块一律 `supervised`（fail closed） |
| 3 | 调板块实现体（service 层不感知 Agent，保持纯粹） | 异常向上抛出 |
| 4 | 写审计：`actor_type=agent` + `agent_id` + `admin_user_id`（人类责任人） | 审计失败不阻断主流程，记日志 |

**为什么新建独立执行链路而不复用用户端 `chat()`**：`AssistantAgentService._build_assistant_runtime_tools()` 是**用户域固有工具的装配点**，且是**条件装配**（逐个 `try` + 功能开关 + 运行上下文），实际工具数随配置动态变化。复用它只能靠黑名单排除用户域工具，而黑名单对动态集合不完备——漏一个就是越权。新链路只装配 admin 板块工具（白名单式，未登记即不装配），边界可自证。

**已实现的板块动作（P1b 范围）**：仅 `builtin_tool`（`list` / `update_enabled` / `update_metadata`）——作为端到端样板；其余板块按同一模式增量登记 `BOARD_ACTIONS` 并补 `_do_<board>` 实现体即可。

**入口**：定义 CRUD `GET /admin/agents`（`agent_pool:read`，仅返回创建者自己的 Agent）+ `POST /admin/agents`（`agent_pool:manage`）+ `PATCH /admin/agents/<id>` / `DELETE /admin/agents/<id>`（均 `agent_pool:manage`；非属主 403、不存在 404）+ 执行入口 `POST /admin/agents/<id>/invoke`（权限 `agent_pool:manage`——执行入口代表"让 Agent 在后台动手"，不接受只读权限触发）+ `GET /admin/agents/<id>/drafts`（权限 `agent_pool:read`，按 `impact.agent_id` 做归属隔离）+ `GET /admin/agents/boards`（权限 `agent_pool:read`，返回已登记板块与动作明细含 `permission_code`，供前端渲染"这个 Agent 能做什么"并做「展示即受限」门控）。路由只做接线：把当前管理员的**实时权限**交给 `AdminAgentService.get_principal()` 重算三重交集（9.1 运行时层）。完整契约见 [管理端 Agent API](../api/admin-agents-api.md)。

> **实现注意（易踩坑）**：`admin["id"]` 经 `_serialize_admin_user` 序列化为**字符串**，而 `admin_agent.owner_admin_user_id` 是 **UUID 列**、服务内 `get_agent` 做纯 Python 属主比较——路由必须 `UUID(str(admin["id"]))` 后再交给服务，否则合法属主会被误判 403（历史缺陷，已在路由层修复并由路由测试锁定）。

**审计身份**（第 9 节）：`audit_log.actor_type`（`human`/`agent`，NOT NULL，默认 `human`）+ `agent_id`（可空，**刻意不加 FK**——Agent 可被物理删除，审计必须留住痕迹）。`admin_user_id` 始终保持为人类责任人，因此可精确区分「A 自己改的」与「A 让 AI 改的」；`agent_name` 由 `_build_agent_name_map` 批量回源展示。

**变更草稿**（9.5 的 `supervised` 载体）：`policy_change_draft` 已泛化为**通用 admin 变更草稿**（`suggestion_id` 可空 + `policy_type` 承载板块标识），通用台账由 `AdminChangeDraftService` 承担（创建/列出/应用/回滚 + 状态机守卫：仅 `pending` 可应用、仅 `applied` 可回滚）；路由板继续用 `RoutingPolicyChangeService`，二者共用同一张表。`agent_id` 写入 `impact` JSONB 以支持追溯。

**回收站 `admin_agent` 来源**：既有 `deleted_by_type="agent"` 被硬约束为仅 7 类用户可见资源，admin 专属资源（`app`/`workflow`/`skill`/`mcp`/`api_tool`/`system_prompt`/`upload_file`）以该来源入站会抛 `ValidateErrorException`。因此新增 `admin_agent` 来源：放行 admin 专属资源、留存按 admin 口径（默认 30 天、可配，区别于用户侧 agent 的固定 7 天）、`_agent_id` 写入快照供追溯。**admin 回收站列表与概览改为 `in_(('admin','admin_agent'))`**，否则 Agent 代删条目在后台不可见、无法恢复。

**回归防护**（均含反向验证）：`test_admin_agent_boards.py`、`test_admin_change_draft_service.py`、`test_admin_agent_board_tools.py`、`test_admin_agent_execution_service.py`、`test_admin_agent_invoke_routes.py`、`test_admin_agent_crud_routes.py`、`test_recycle_bin_admin_agent.py`、`test_builtin_tool_write_paths.py`、`test_audit_write_commit_guard.py`。

**未接入项（明确标注）**：`AdminChangeDraftService.apply_draft` / `rollback_draft` 已提供能力，但「待批准变更」前端页属后续阶段，当前只有测试调用。
