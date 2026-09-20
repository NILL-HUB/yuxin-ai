# ADMIN-P4 管理端 Agent 记忆治理与对话入口

**日期**：2026-09-20
**范围**：P3c-4 计划「与后续阶段的边界」表中 ADMIN-P4 四项——
1. `gdpr_delete` 路由入口
2. agent_id 通道预算闸门
3. 管理端前端对话页（含 admin 记忆读入口/图表）
4. 定时任务 agent_id 通道

**TDD**：每个 Task 先写失败测试 → 红 → 实现 → 绿 → 提交（显式 pathspec，避开并行 KB-P4.5 工作树）。

---

## 背景与现状（调研确认）

| 项 | 现状 | 断链点 |
| --- | --- | --- |
| `MemoryGovernor.gdpr_delete` | 已主体化（`api/internal/service/memory/memory_governor.py` L327，删 Neo4j + pgvector + Redis + 审计） | **无生产调用方**（全仓仅定义 + test） |
| `admin_agent.budget_config` | JSONB 列已建（`api/internal/model/admin_agent.py` L69，注释「§6.3，P4 落地」），create/update 已收参 | **零运行时读取**（无 check/budget gate） |
| 定时任务 | `ScheduleTask`（`api/internal/model/schedule_task.py`）用户端维度，已支持 `owner_type='admin'` 平台任务（绑定 `app_id`），`schedule_execution_service` 按 app 执行 | **无 admin_agent 维度**，管理端 Agent 无法周期性自主执行 |
| 管理端前端 | admin 路由无 agents 页；`POST /admin/agents/<id>/chat`（SSE）/ `conversations` / `messages` 后端已就绪；SSE 消费前端无样板 | 前端未落地 |
| admin 记忆读入口 | `admin_memory_recall.recall_admin_agent_memory_for_chat` 只服务 chat 链路 | 无独立记忆读/统计 API 给前端页面 |

**关键约束（继承 P3c-4）**：
- 用户态逐字节等价：admin 改造不得改变用户主体行为。
- 诚实披露：未接线项必须标注，不虚报。
- 前端 i18n 双侧镜像 + parity 测试通过。
- RBAC 权限点「只增不删」：新增权限点须带迁移清理；优先复用既有 `agent_pool:read/manage`。

---

## Task 1: `gdpr_delete` HTTP 路由入口（admin）

**现状**：`MemoryGovernor.gdpr_delete(owner_key)` 无 HTTP 入口。为控制信任面，路由**不接收裸 owner_key**，而是收主体分解字段、服务端构造 `MemoryOwnerKey`。

**改动**：
- `api/app/http/admin_routes_7.py`（或就近文件）新增：
  - `POST /admin/memory/gdpr-delete`，body `{subject_type: "user"|"admin"|"agent", subject_id: str, agent_id?: str}`。
  - 服务端 `MemoryOwnerKey.for_user / for_admin(admin_user_id, agent_id)` 构造；返回 `{stats}`。
  - 鉴权：`_resolve_admin_permission(...)`（复用 `agent_pool:manage`；若 PERMISSION_CATALOG 有更贴合的记忆权限点则用其，执行时核对 `api/internal/core/rbac.py`）。
  - 审计由 `MemoryGovernor._log_audit` 内部完成（已实现）。

**Tests**（`api/test/app/http/test_admin_routes_7_*` 追加）：
- 鉴权 403：无权限 admin 被拒
- 合法调用：mock `MemoryGovernor.gdpr_delete`，断言 body→owner_key 映射正确（user=裸 UUID、agent=`admin:{admin}:{agent}`）
- 非法 subject_type → 400

---

## Task 2: agent_id 通道预算闸门

**现状**：`budget_config` 零读取。施加点：`AdminAgentExecutionService.run`（`api/internal/service/admin_agent_execution_service.py` L50）入口 + `AdminAgentChatService.chat`（对话链路）入口。

**改动**：
- 新 `api/internal/core/admin_agent_budget.py`：`AdminAgentBudgetGate`。
  - `budget_config` schema：`{ "daily_executions": int?, "monthly_executions": int?, "daily_tokens": int?, "monthly_tokens": int? }`（空/缺省=不限制）。
  - 计数存储：Redis 周期键 `budget:{agent_id}:{metric}:{YYYYMMDD|YYYYMM}`；执行/对话消耗时 `incr`；超限抛 `CustomException`（可读文案），**记审计**（`BUDGET_REJECTED`）。
  - Redis 不可用 → fail-open（放行 + 记日志），不阻断既有行为。
  - `budget_usage(agent_id)` → 当前周期用量。
- `AdminAgentExecutionService.run` 入口插入 `gate.assert_allowed(agent_id)`；`AdminAgentChatService.chat` 入口同样。
- 路由：`GET /admin/agents/<id>/budget/usage`（复用 `agent_pool:read`）。
- 审计写路径遵循 `_write_audit` 提交语义（避免 ADMIN-P1b 顺带修复的静默丢失类回归）。

**Tests**（`api/test/internal/core/test_admin_agent_budget.py` 新建 + `test_admin_agent_execution_service.py`/`test_admin_agent_chat_service.py` 追加）：
- 未配置 budget_config → 恒放行
- daily/monthly 超限 → 拒绝 + 审计
- Redis 不可用 → fail-open
- 用法统计正确累计

---

## Task 3: 定时任务 agent_id 通道

**现状**：`ScheduleTask` 无 admin_agent 绑定；`schedule_execution_service` 只处理用户 app 执行。

**改动**：
- 迁移：`schedule_task` + `schedule_task_run` 加 `admin_agent_id`（UUID NULL，FK `admin_agent.id`），`down_revision` 指向已 git 跟踪的迁移。
- `schedule_task_service`：`create_task` 支持 `task_type='admin_agent_execution'` + `admin_agent_id`（仅 `owner_type='admin'` 可绑，校验 admin_agent 存在且归属当前 admin_user）；`get_task`/`list` 过滤透传。
- `schedule_execution_service`：新分支——`admin_agent_execution` 任务执行时：查 `admin_agent` → 构造 `AdminAgentPrincipal`（归属 admin_user + 权限重算）→ 按 `input_params` 的 `{board, action, payload}` 调 `AdminAgentExecutionService.run`（自动按 `automation_policy` 分流）。审计 `actor_type=agent` 沿用既有链路。
- admin 路由：`POST /admin/agents/<id>/schedules`、`GET /admin/agents/<id>/schedules`、`DELETE /admin/agents/<id>/schedules/<task_id>`（复用 `agent_pool:manage/read`）。
- Celery 派发：admin 定时任务复用既有 schedule 轮询/派发点（执行时核对现有 scheduler 如何触达 `schedule_task_run`）。

**Tests**：
- 迁移可逆 + FK 约束（`test_schedule_task_admin_agent_migration.py`）
- service：admin_agent 校验、task_type 分流（`test_schedule_task_service.py` 追加）
- execution：mock `AdminAgentExecutionService.run`，断言 principal 构造与结果落 `schedule_task_run`（`test_schedule_execution_service.py` 追加）
- 路由：CRUD + 权限 403

---

## Task 4: admin 记忆读 API（管理端记忆读入口）

**现状**：无独立记忆读 API。按 `MemoryOwnerKey.for_admin(admin_user_id, agent_id)` 主体查询。

**改动**：
- 新 `api/internal/service/memory/admin_memory_read.py`：
  - `memory_stats(admin_user_id, agent_id)` → 节点数 / Episode 数 / 技能数 / 最近记忆片段（Neo4j count + 抽样）。
  - `list_memories(admin_user_id, agent_id, page, page_size)` → 分页记忆节点（title/content/updated_at）。
- 路由：`GET /admin/agents/<id>/memory/stats`、`GET /admin/agents/<id>/memory/list`（复用 `agent_pool:read`）。

**Tests**（`api/test/internal/service/memory/test_admin_memory_read.py` 新建，mock driver）：
- stats 的 Cypher 绑定 `admin_user_id` + `agent_id`
- list 分页 + 主体过滤
- 路由鉴权 403

---

## Task 5: 管理端前端对话页 + 记忆面板（含 i18n）

**现状**：无 agents 页；SSE 消费无样板（`ui/src` 无 EventSource/getReader 用例）。

**改动**：
- `ui/src/utils/sse.ts`：fetch + `ReadableStream` 解析 `event:`/`data:` 帧的轻量工具。
- `ui/src/views/admin/agents/ListView.vue`：Agent 列表 + 新建/编辑对话框（名称/描述/提示词/权限/自动化策略/预算）+「对话」入口。
- `ui/src/views/admin/agents/ChatView.vue`：SSE 对话（`POST /admin/agents/<id>/chat`）+ 会话历史（`GET .../conversations`、`GET .../conversations/<id>/messages`）+ 记忆面板（Task 4 stats/list）。
- `ui/src/views/admin/agents/` 下 API 封装（`api` 目录约定）对接 `POST /admin/agents`、`<id>/chat`、`<id>/invoke`、`<id>/drafts`、`<id>/budget/usage`、`<id>/memory/*`。
- 路由：`admin/agents`、`admin/agents/:id/chat` 注册（`ui/src/router/index.ts`）；`AdminLayout.vue` 侧边栏入口。
- i18n：`ui/src/i18n/messages/<locale>/admin/agents.ts` 双侧镜像 + `admin/index.ts` 注册 + `npx vitest run src/i18n/__tests__/parity.spec.ts` 通过。
- 记忆面板文案/图表走 i18n；图标/占位用既有体系。

**Tests**：
- `ui/src/i18n/__tests__/parity.spec.ts` 通过（强制）
- SSE 工具单测（`ui/src/utils/__tests__/sse.spec.ts`，mock fetch stream）
- 页面组件若加逻辑钩子（hooks）补单测；纯展示页以 parity + lint 兜底

---

## Task 6: 接线审查 + 全量回归 + 真图验证

- 逐个新符号点名入口：
  - `POST /admin/memory/gdpr-delete` → `MemoryGovernor.gdpr_delete`
  - `AdminAgentBudgetGate` → `AdminAgentExecutionService.run` / `AdminAgentChatService.chat` 入口
  - `schedule_task.admin_agent_id` → `schedule_execution_service` admin 分支 → `AdminAgentExecutionService.run`
  - `GET /admin/agents/<id>/memory/stats|list` → `admin_memory_read`
  - 前端对话页 → SSE 工具 → chat 端点
- 全仓搜引用（排除 `api/test/**` 与文档）：无「只有定义处 + 测试处」断链。
- 全量回归 `python -m pytest api/test -q`：统计 passed/skipped/failed，失败归因（环境性/并行 KB-P4.5 引入）。
- 真库验证（llmops-db/neo4j/api）：admin+agent 主体记忆写入 → 记忆读 API stats 非零；gdpr_delete 走路由后主体节点清零。

---

## Task 7: 文档同步 + graphify

- `docs/prd/execution-roadmap.md`：新增 ADMIN-P4 交付节（交付物表 + 关键决策 + 验证数据 + 诚实披露）。
- `docs/prd/architecture-design.md` / `docs/prd/memory-system/*`：gdpr_delete 入口、预算闸门、admin 记忆读 API、定时任务 admin_agent 通道。
- `docs/api/admin-agents-api.md`：新增端点登记。
- 运行 `python -m graphify update .`。

---

## 自检清单

- [ ] 用户态逐字节等价（不触碰用户主体行为）
- [ ] 每个新符号有真实生产调用方/入口（接线审查通过）
- [ ] 预算闸门 Redis 不可用 fail-open 不阻断既有行为
- [ ] 定时任务 admin_agent 通道执行落 `schedule_task_run` + 审计 actor_type=agent
- [ ] i18n 双侧镜像 + parity 通过
- [ ] 全量回归通过（失败已归因）
- [ ] 文档同步 + graphify 更新

---

## 与后续阶段的边界

| 项 | 状态 |
| --- | --- |
| MCP 动态身份注入 | ADMIN-P5（不在本计划） |
| EntityResolver 接线 | 待产品决策（不在本计划） |
| admin 记忆图表化可视化（图可视化/时间线） | 若 Task 4/5 已含记忆面板则为已交付；深度可视化留 P5 |
| 冷存储 list_user_archives 列举能力 | 端口无列举，恒空（不在本计划） |
