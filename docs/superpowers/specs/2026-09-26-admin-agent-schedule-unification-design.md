# 管理员 Agent 定时任务统一与无人值守自治设计

> 状态：待评审
> 背景：管理端存在「平台级定时任务」与「管理员 Agent 专属定时任务」两个入口，前端各写一套交互（三步向导 vs 手填弹窗）。本次目标不是合并两个系统（后端本就是单一实现），而是：**收敛入口、补齐能力、修复两条真实断链，并在安全可控前提下让 Agent 具备无人值守自治能力**。

## 1. 问题与判定

### 1.1 实测现状：不是两套实现，而是「一个轮胎 + 三个阀门」

全仓追调用方确认，定时任务的落库、执行、调度**均只有一份实现**：

| 共享层 | 位置 | 复用方 |
|---|---|---|
| 数据表 | `schedule_task` / `schedule_task_run` | 三个入口共用 |
| 创建/更新 | `ScheduleTaskService.create_task` / `update_task` | 三个入口共用 |
| 执行 | `ScheduleExecutionService.execute_task`（按 `task_type` 分三支） | 两个入口共用 |
| 调度 | Celery beat `run-scheduled-tasks`（`crontab(minute="*")`） | 全局唯一 |

三个入口的差异**只在路由层能力面与权限点**：

| 入口 | 路由 | 能力面 | 权限 |
|---|---|---|---|
| A 平台级 | `/admin/schedule-tasks`（`admin_routes_5.py` L44-343） | create/list/get/update/enable/run-now/runs | `schedule_task:*` |
| B Agent 专属 | `/admin/agents/<id>/schedules`（`admin_routes_7.py` L580-708） | 仅 create/list/delete | `agent_pool:read/manage` |
| C 用户级 | `/schedule-tasks`（`schedule_assistant_routes.py`） | 与 A 同构 | 用户身份 |

**结论：后端无重复逻辑；重复只发生在前端交互与路由能力面。**

### 1.2 两条真实断链（本次必须修复）

**断链 1：token 预算记账失效（`daily_tokens` / `monthly_tokens` 配置形同虚设）**

`AdminAgentBudgetGate`（`internal/core/admin_agent_budget.py`）的 token 类限额依赖调用方传入 `tokens`：

```python
# assert_allowed L98：daily_tokens/monthly_tokens 的 fixed_delta 为 None
delta = tokens if fixed_delta is None else fixed_delta
```

而 `check_and_record` 的 **3 个调用点全部未传 `tokens`**：

| 调用点 | 现状 | 是否有真实 token 消耗 |
|---|---|---|
| `admin_agent_chat_service.py` L113（对话入口） | 循环**之前**调用，`tokens=0` | **有**（LLM + 工具循环） |
| `admin_routes_7.py` L476（invoke） | `tokens=0` | 无（单动作直调 service） |
| `schedule_execution_service.py` L239（定时执行） | `tokens=0` | 无（单动作直调 service） |

后果：
- `assert_allowed`：`used + 0 > limit` 永不成立 → **token 限额永不触发**；
- `record_usage`：`if tokens and tokens > 0` 永不成立 → **token 计数永不累加**；
- `GET /admin/agents/<id>/budget/usage` 的 token 项**恒为 0**（只读不写的镜像断链）。

唯一真实产生 token 的链路是 `AdminAgentChatService.chat` 的 `_run_tool_loop`，
其 `ai = bound.invoke(messages)` 的返回值带 `usage_metadata`，但**被直接丢弃**。

**断链 2：定时唤醒走无记忆的单动作链**

`_run_admin_agent`（`schedule_execution_service.py` L209-249）只调用
`AdminAgentExecutionService.run`，该链**无 LLM、无工具循环、无记忆召回/写入**：

- 它执行的是**一个预设的 `(board, action, payload)`**，等价于「替管理员按一次按钮」；
- 每次唤醒**完全无状态**：不召回记忆（不知上次做到哪）、不写记忆（本次做了什么不留痕）；
- 带记忆、能多步骤干活的是 `AdminAgentChatService.chat`（L113 召回 / L191 写入 / `_run_tool_loop` 多轮），但它**没有定时唤醒入口**。

即：**用户设想的「多步骤无人值守」当前不可达**——不是「唤醒后丢上下文」，而是唤醒链没有上下文。

### 1.3 轮胎 vs 补丁判定

**判定为「轮胎 + 补丁」，处置为补洞口 / 收编，禁止推倒重建。**

- **轮胎（核心能力层，多模块复用且有校验）**：
  `ScheduleTaskService`（被 3 个入口复用）、`ScheduleExecutionService`（唯一执行入口）、
  `RecycleBinService`（`schedule_task` 快照/恢复已实现）、`AdminAgentBudgetGate`（周期键 + fail-open + usage 查询齐备）、
  `AdminAgentChatService`（记忆召回 + 写入 + 工具循环齐备）。
- **补丁**：B 通道那套能力残缺的前端弹窗；token 记账漏传断链；唤醒链与 chat 链分叉。
- **无平行机制**：`BOARD_ACTIONS` 是唯一 Agent 能力登记表；`check_and_record` 是唯一预算闸门入口。

**处置**：扩展既有权威入口，不新建第二套预算/调度/记忆机制。仅新增 1 个 `task_type` 枚举值（L2）与 1 个 `budget_config` 键（L3）。

## 2. 目标与非目标

**目标**

1. **修复 token 记账**：`daily_tokens` / `monthly_tokens` 真实生效，usage 不再恒为 0。
2. **升级唤醒链**：定时唤醒走带记忆的多步骤对话，Agent 可无人值守推进任务。
3. **单次唤醒预算**：一次唤醒内累计 token，达硬顶主动中断；Agent 可读剩余额度并据此安排下次唤醒。
4. **Agent 自治能力**：Agent 可自建/删除定时任务（`list`/`create`/`delete`），实现自拉起。
5. **入口统一**：Agent 定时任务收敛到 `/admin/schedules`，前端只剩一套向导。
6. **零新增安全阀门**：安全全靠既有回收站（可恢复）+ 预算闸门（成本刹车）。

**非目标（本次不做）**

- 不删除 `schedule_task` 表、不新建 ScheduleTask service（后端已是单一实现）。
- 不给 Agent 开 `update` 权限（「改任务」= 删旧的 + 建新的，两步都在回收站覆盖内）。
- 不改造既有 `admin_agent_execution` 单动作任务语义（L2 新增类型，旧任务原样保留）。
- 不引入 supervised/autonomous 之外的新自动化档位或新的审批阀门。

## 3. 总体方案：五个阶段

严格执行顺序，**L1 不做则 L3/L4 全是空谈**（预算配了不生效）。

| 阶段 | 内容 | 性质 | 前置 |
|---|---|---|---|
| **L1** | 修 token 记账断链 | 补洞口 | — |
| **L2** | 唤醒链升级（新增 `task_type=admin_agent_chat`） | 扩展轮胎 | L1 |
| **L3** | 单次唤醒预算（`budget_config.per_run_tokens`） | 新增维度 | L2 |
| **L4** | Agent 自建定时任务（`schedule_task` 板块） | 扩展轮胎 | L1 |
| **L5** | 入口统一（收编 B 通道） | 收编 | L2 |

## 4. L1 — 修复 token 记账断链

**唯一改动点**：`AdminAgentChatService.chat` 的 token 记账闭环。其余两处调用点无真实 LLM 消耗，`tokens=0` 语义正确，仅补注释说明（不改行为）。

**改动**

1. `_run_tool_loop`（`admin_agent_chat_service.py` L207-270）在每轮 `bound.invoke(messages)` 后，
   复用既有提取器 `internal/core/agent/usage_utils.py::extract_token_usage` 提取本轮 token，累计到局部计数器。
2. 循环收敛（或中断）后，调用 `AdminAgentBudgetGate.record_usage` 写回实际累计 token：

```python
# 概念示意（非最终签名，签名以实现为准）
self._budget_gate().record_usage(agent_id, budget_config, tokens=accumulated_tokens)
```

3. 入口 `check_and_record`（L113）保留（负责 executions 计数与周期额度预检），token 由第 2 步事后累加。

**验收**：管理员配 `daily_tokens=1000`，跑一轮真实对话后 `GET /admin/agents/<id>/budget/usage` 的 `daily_tokens` 不为 0；再跑使累计超限时，下一轮入口被 `AdminAgentBudgetExceeded` 拒绝。

## 5. L2 — 唤醒链升级（新增 `task_type`，旧的分支不动）

**新增枚举值** `TASK_TYPE_ADMIN_AGENT_CHAT = "admin_agent_chat"`（`schedule_task_service.py` L41-44），加入 `TASK_TYPES`。

**改动**

1. `create_task` 的 `admin_agent_id` 分支（L365-373）当前**强制** `normalized_task_type = TASK_TYPE_ADMIN_AGENT_EXECUTION`。
   调整为：`admin_agent_id` 存在时，依据入参选择 `admin_agent_chat`（默认，带记忆多步骤）或
   `admin_agent_execution`（显式指定，保留单动作语义）。
   **既有任务因存量 `task_type` 已是 `admin_agent_execution`，行为不变。**
2. `execute_task` 分支（`schedule_execution_service.py` L142-152）新增一支：

```python
if schedule_task.task_type == "admin_agent_chat" and schedule_task.admin_agent_id:
    answer = self._run_admin_agent_chat(schedule_task)
```

3. 新增 `_run_admin_agent_chat(schedule_task)`：
   - 复用 `_build_admin_agent_principal(agent)`（`schedule_execution_service.py` L42-60）重算执行身份
     （`owner_admin_user_id` → 实时权限 → 三重交集），**无需 HTTP token**；
   - 调用 `AdminAgentChatService.chat(agent_id=..., admin_user_id=..., admin_permissions=..., query=task.prompt, conversation_id=...)`，
     迭代其 SSE 生成器至自然结束，取最终 `answer` 帧（或按 `_run_assistant_chat` L327-334 的方式从会话最新消息读取）；
   - **记忆隔离**：`chat` 内部经 `MemoryOwnerKey.for_admin(admin_user_id, agent_id=...)` 构造主体键
     （`admin_memory_recall.py` L57），为「每 Agent 一份记忆」，**不与管理员自身记忆混用**；
   - 会话归属：`_run_admin_agent_chat` 传 `conversation_id=None`，`chat` 内部 `_resolve_conversation` 为**每次唤醒新建一个会话**（不跨唤醒共享）。连续性由**记忆召回/写入**承担：每次唤醒经 `MemoryOwnerKey.for_admin(admin_user_id, agent_id=...)` 召回该 Agent 的历史记忆，执行后再写入新记忆。**不共享会话是刻意的实现取舍**——同一长生命周期会话会被多次唤醒的历史不断撑大，最终超上下文窗口；每次新建会话 + 记忆延续，既保持连续认知又避免上下文膨胀。

**验收**：新建 `admin_agent_chat` 任务并 run-now，确认 ① 执行后 `admin_agent_conversation` 有消息落库；
② 第二次唤醒能召回第一次写入的记忆（`recall_admin_agent_memory_for_chat` 返回非空）；
③ 既有 `admin_agent_execution` 任务行为与执行结果不变。

## 6. L3 — 单次唤醒预算

**语义**：边界 = **一次唤醒**（一次 `ScheduleTaskRun` / 一次 `chat` 调用），内部可能含 100+ 次 LLM 请求。

**配置**：扩展 `admin_agent.budget_config`（不新建表）新增键 `per_run_tokens`：

```json
{
  "daily_executions": 10,
  "monthly_executions": 100,
  "daily_tokens": 5000000,
  "monthly_tokens": 100000000,
  "per_run_tokens": 10000000
}
```

- `AdminAgentService._validate_budget_config`（L283-312）加入 `per_run_tokens` 校验（非负整数）；
- 前端 `admin/agents/ListView.vue` 的 `budgetFields`（L90-95）加入该字段 + i18n 键（zh-CN/en-US 同步）。

**执行**：`per_run_tokens` **不能用 Redis 周期键**（它不跨唤起聚合，而是单次调用内累计），故在
`_run_tool_loop` 内维护**本次调用**的累计 token：

1. 每轮 `invoke` 后累计并比对 `per_run_tokens`；
2. 超过硬顶 → 中断循环，产出终态说明（如「本次唤醒已达单次 token 上限，已中断」），
   由 `execute_task` 记为 `success=False` 或带说明的失败，**不静默**；
3. **Agent 自主提前规划**：在 system prompt 注入「本次唤醒剩余 token 额度」，
   使 Agent 能判断「即将到顶」并主动调用 `schedule_task.create` 安排下次唤醒；
4. **卡死保护**：若 Agent 陷入空烧循环，不主动安排下次 —— 撞硬顶被中断，损失被限定在 `per_run_tokens` 内。

**验收**：① 设 `per_run_tokens` 为极小值，跑一次唤醒，确认在轮内被中断且 `ScheduleTaskRun` 有失败记录；
② 剩余额度注入后，Agent 在接近上限时能产出「安排下次唤醒」的工具调用；③ 未设 `per_run_tokens` 时行为与现状一致（不限制）。

## 7. L4 — Agent 自建定时任务

**能力登记**：在 `internal/core/admin_agent_boards.py::BOARD_ACTIONS`（L65-82）新增 `schedule_task` 板块：

| action | kind | permission_code | 语义 |
|---|---|---|---|
| `list` | read | `schedule_task:read` | 列出平台级定时任务 |
| `create` | write | `schedule_task:create` | 创建定时任务 |
| `delete` | delete | `schedule_task:delete` | 删除定时任务（进回收站） |

**接线**：`build_board_tools`（`admin_agent_chat_tools.py` L112-121）按 `BOARD_ACTIONS` 白名单自动生成工具，
Agent 无需额外挂载点即获得 `admin_schedule_task` 工具；执行体在 `BoardToolExecutor` 新增 `_do_schedule_task`，
内部复用 `ScheduleTaskService`（create/delete + `_validate_admin_agent_binding` 归属校验）。

**权限映射**：`app/http/support.py` 的 `_admin_route_permission`（L614-630 已有 `admin/schedule-tasks` 分支）。
板块动作走 `assert_allowed` → `principal.has_permission(permission_code)`，无需新增路由映射。

**安全模型（零新增阀门）**

| 风险 | 既有兜底 | 状态 |
|---|---|---|
| 建错 / 删错 | 回收站 `schedule_task` 快照 + 恢复 | ✅ 已实现（`recycle_bin_handlers.py` L819/L844，`delete_task` L566 已调用） |
| 改错 | **不开放 update**；「改」= 删旧的 + 建新的 | 设计约束 |
| 成本 / 递归自增殖 | `AdminAgentBudgetGate`（L1/L3 修复后含 per-run 硬顶） | ✅ L1/L3 后生效 |
| 越权 | `assert_allowed` fail-closed + `_validate_admin_agent_binding` | ✅ 已实现 |

**为何不开 update**：回收站只覆盖「删除那一刻」的快照，改错无回滚路径。以 `create`+`delete` 表达修改，
两步均落在回收站覆盖内，安全模型自洽，且不引入草稿审批。

**自增殖闭环**：`per_run_tokens` 剩余额度注入（L3）+ `schedule_task.create` 能力（L4）二者结合，
即 Agent 可「判断将到顶 → 安排下次唤醒 → 下次唤醒带记忆继续」，构成无人值守自治闭环。

## 8. L5 — 入口统一（收编 B 通道）

**前端**

- `ui/src/views/admin/agents/ListView.vue` 的手填定时任务弹窗（L269-353）**删除**，
  改为「查看定时任务」按钮 → 跳转 `/admin/schedules?agent_id=<id>`；
- `ListView.vue`（`space/schedules/`，admin/user 共用）读取 `route.query.agent_id` 做列表过滤；
- `CreateScheduleWizard.vue` 增加「绑定管理端 Agent」选项（admin 上下文可见），选中即创建 `admin_agent_chat` 任务。

**后端**

- 平台级 create/update 路由补 `admin_agent_id` 透传（`admin_routes_5.py` L61-109 / L229-267）；
- `update_task` 增加 `admin_agent_id` 入参（当前不支持，导致 B 通道任务无法编辑）；
- B 通道 3 路由（`admin_routes_7.py` L580-708）**保留为薄转发**（内部仍调 `ScheduleTaskService`），
  按仓库规则标注 `PATCH(schedule): 兼容别名 + 收编计划`，供旧客户端过渡；
- 清理 `admin_routes_7.py` L596、L682 残留的裸 `# ` 行。

**契约同步**：`docs/api/admin-agents-api.md`（L308-333）标注 B 通道为兼容别名；收尾自检见 §11。

## 9. 接线面清单（逐符号入口）

| 新增/修改符号 | 入口（调用方/触发路径） |
|---|---|
| `TASK_TYPE_ADMIN_AGENT_CHAT` | `create_task` 入参 → `execute_task` 分支 L142 |
| `_run_admin_agent_chat` | `execute_task` 新增分支 |
| `budget_config.per_run_tokens` | admin 前端表单 → `_validate_budget_config` → `_run_tool_loop` 累计比对 |
| `BOARD_ACTIONS` 的 `schedule_task` 板块 | `build_board_tools` → Agent 工具 `admin_schedule_task` |
| `BoardToolExecutor._do_schedule_task` | `execute` 的 `getattr(self, f"_do_{board}")` 分派 |
| `record_usage(tokens=...)` | `chat` 循环收敛后调用 |
| `GET /admin/schedules?agent_id=` | 前端 Agent 页跳转 |

## 10. 测试策略

遵循仓库 TDD：先写失败测试，再实现（RED → 验证 → GREEN）。

**L1**：`test_admin_agent_chat_service.py` 新增「循环后 token 被记账」用例（mock LLM 返回带 `usage_metadata` 的 AIMessage，断言 `record_usage` 收到非 0 tokens）。

**L2**：`test_schedule_execution_service_admin_agent.py` 新增「`admin_agent_chat` 走 chat 链并落会话消息」用例；断言既有 `admin_agent_execution` 用例不变（回归）。

**L3**：新增「单次累计超 `per_run_tokens` 中断」用例；「剩余额度注入 prompt」用例；「未配置则不限制」用例。

**L4**：`test_admin_agent_board_tools.py` 新增 `schedule_task` 板块的 action 登记与权限断言；新增「create 落回收站可恢复」端到端用例。

**L5**：`test_admin_routes_5.py` 补 `admin_agent_id` 透传用例；`test_admin_agent_schedule_routes.py` 保留（B 通道薄转发回归）。

**前端**：`ui/src/views/admin/agents/__tests__/ListView.spec.ts` 调整（弹窗删除 → 跳转）；
`CreateScheduleWizard.spec.ts` 补 agent 绑定；i18n parity 测试
（`npx vitest run src/i18n/__tests__/parity.spec.ts`）必须通过。

## 11. 风险与回滚

| 风险 | 缓解 |
|---|---|
| L2 改变 `create_task` 的 `task_type` 默认选择，影响新建任务语义 | 仅当 `admin_agent_id` 存在时改；存量任务 `task_type` 已固化，不受影响 |
| L3 硬顶中断正常长任务 | `per_run_tokens` 缺省不限制（与现状一致）；建议值远高于正常任务量级 |
| L4 开放自建后误建/误删 | 回收站 30 天可恢复；`_validate_admin_agent_binding` 限归属；L1/L3 控成本 |
| B 通道薄转发长期残留 | 注释标注 `PATCH(schedule)` + 收编计划；API 文档登记 |

**回滚**：各阶段独立可回滚。L2 回滚 = 新任务不再选用 `admin_agent_chat`（存量 chat 任务需人工改回）；
L3 回滚 = 清空 `per_run_tokens`；L4 回滚 = 从 `BOARD_ACTIONS` 移除 `schedule_task` 板块。

## 12. 收尾自检（按仓库规则）

1. **判定**：轮胎 + 补丁（五个权威入口复用：`ScheduleTaskService`/`ScheduleExecutionService`/`RecycleBinService`/`AdminAgentBudgetGate`/`AdminAgentChatService`；补丁 = B 通道前端弹窗 + token 记账断链 + 唤醒链分叉）。
2. **处置**：**补洞口 / 收编**，非重建——不删表、不新建 service、不新建第二套预算或记忆机制。
3. **单一权威入口**：落库 → `ScheduleTaskService`；回滚 → `RecycleBinService`；预算 → `AdminAgentBudgetGate`；记忆主体 → `MemoryOwnerKey.for_admin`；Agent 能力 → `BOARD_ACTIONS`。**无平行机制引入。**
4. **断链修复**：L1 修复「token 记账调用点漏传」；L2 修复「唤醒链无记忆」。
