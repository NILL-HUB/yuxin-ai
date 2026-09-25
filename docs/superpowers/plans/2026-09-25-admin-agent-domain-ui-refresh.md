# 管理端 Agent 治理域 UI 翻新 + 功能核查修复

- 状态：已完成
- 日期：2026-09-25
- 范围：`/admin/agents`（管理端 Agent 列表、对话）、`/admin/agent-pool`（Agent 池配置）、`/admin/sub-pool-definition`（子池定义）

## 一、背景与问题

用户反馈「管理 Agent 板块内部 UI 全是基础 HTML 骨架，丑得没眼看」。经代码核查确认属实，问题分两类：

| 页面 | 现状 | 问题 |
|---|---|---|
| [AgentPoolView.vue](file:///d:/DEMO/openagent-main/ui/src/views/admin/AgentPoolView.vue) | 手写原生 `<table>` + Tailwind | 裸表格、无卡片化、统计区朴素 |
| [sub-pool-definition/index.vue](file:///d:/DEMO/openagent-main/ui/src/views/admin/sub-pool-definition/index.vue) | 手写原生 `<table>`（10 列） | 字段挤成一团、可读性差 |
| [agents/ListView.vue](file:///d:/DEMO/openagent-main/ui/src/views/admin/agents/ListView.vue) | 朴素 `a-table` + Tailwind | 无卡片/统计区，权限点堆成 tag 墙 |
| [agents/ChatView.vue](file:///d:/DEMO/openagent-main/ui/src/views/admin/agents/ChatView.vue) | 三栏 Tailwind 拼装 | 聊天气泡、记忆面板均为裸样式 |

对照已翻新的 [ToolsView.vue](file:///d:/DEMO/openagent-main/ui/src/views/admin/ToolsView.vue)（UX-1，卡片网格 + 渐变头像 + tabs + 抽屉），差距明显。

## 二、功能核查结论（前端调用 ↔ 后端路由 ↔ 权限）

后端核查覆盖 30 条路由，结论：**全部真实注册，无缺失**。路由定义于 [admin_routes_7.py](file:///d:/DEMO/openagent-main/api/app/http/admin_routes_7.py) 的 `register_routes`，经 [asgi_app.py:247](file:///d:/DEMO/openagent-main/api/app/http/asgi_app.py#L247) 装配，由 [asgi_app.py:64-79](file:///d:/DEMO/openagent-main/api/app/http/asgi_app.py#L64-L79) 全局门禁强制权限。

### 2.1 可用（已确认接线）

- **Agent 池**：8 条 `/admin/agent-pool*` 全部注册，权限 `agent_pool:read`（GET）/ `agent_pool:manage`（写），对应 `AdminAgentPoolService`。
- **子池定义**：6 条 `/admin/sub-pool-definitions*` 全部注册，复用 `agent_pool:read`/`manage`（无 `sub_pool:*` 权限点，见 support.py:637-640 合并分支）。
- **管理端 Agent**：16 条 `/admin/agents*` + `/admin/memory/gdpr-delete` 全部注册，权限同上，对应 `AdminAgentService` / `AdminAgentChatService` / `AdminAgentConversationService` / `AdminMemoryReadService` / `MemoryGovernor.gdpr_delete` / `ScheduleTaskService`。

### 2.2 发现的缺陷（本次一并修复）

**缺陷 1（真实且可触发）：`FailException` 未导入导致 400 变 500**

- 位置：[admin_routes_7.py:630](file:///d:/DEMO/openagent-main/api/app/http/admin_routes_7.py#L630) 与 [L696](file:///d:/DEMO/openagent-main/api/app/http/admin_routes_7.py#L696) 使用了 `except FailException as exc:`
- 证据：文件 import 段（L16-19）无 `FailException`，全文件仅这 2 处出现；容器内 AST 校验 `FailException imported: False`
- 触发路径：[ScheduleTaskService.create_task](file:///d:/DEMO/openagent-main/api/internal/service/schedule_task_service.py#L99-L156) 在 cron 表达式非法时抛 `FailException`。用户在「Agent 定时任务」弹窗填错 cron，会走 except 子句求值 `FailException` → 抛 `NameError` → 本该 400 的校验错误变成 **500**
- 修复：文件顶部补 `from internal.exception import FailException`

### 2.3 前端未接入的后端能力（仅登记，不在本次范围）

- `getAgentPoolConfig` / `getSubPoolDefinition` 两个 service 函数已定义但无调用方（列表数据已含全字段，详情接口实际用不上）
- 后端存在 `POST /admin/agents/<id>/invoke`、`GET /admin/agents/<id>/drafts` 两条路由，前端未使用（属设计预留，非断链）

## 三、设计方向

对齐 ToolsView（UX-1）确立的语言，统一到「**卡片网格 + 统计条 + 抽屉详情**」：

- **色彩**：沿用 admin 现有 token（`text-slate-900/500`、`border-slate-200`、`bg-white`），不引入新色板
- **头像/图标**：复用 ToolsView 的渐变头像算法（`hashString` + 8 组 `avatarPalettes`），抽成共享工具而非复制
- **统计区**：统一为顶部 KPI 卡（数字 + 语义色 + 说明）
- **列表**：池配置/子池定义从裸 `<table>` 改为 `a-table`（保留列信息，但用 Arco 的样式与交互）或卡片网格
- **详情**：行内展开抽屉，避免弹窗嵌套
- **空态/加载**：复用 `CardGridSkeleton`、`a-empty`
- **动效**：`hoverable` 卡片 + 过渡，克制不夸张

## 四、实施任务（TDD，每任务独立提交）

### T0：修复 `FailException` 缺陷（先行，独立提交）

- 补 import + 补一条单测：向 `POST /admin/agents/<id>/schedules` 传非法 cron，断言返回 400 而非 500
- 提交：`fix(admin): import FailException to keep schedule validation at 400`

### T1：抽取共享展示工具

- `ui/src/utils/admin-agent-display.ts`：渐变头像（`hashString`/`extractAvatarText`/`getAgentAvatarStyle`）、时间格式化
- 单测：哈希稳定性、中英文取字、渐变确定性

### T2：翻新 Agent 池配置页（AgentPoolView）

- 统计区 → KPI 卡（总数/启用/健康，语义色）
- 列表 → `a-table` 化，健康/成本 tag 语义色，能力 chips，应用名 tooltip
- 保留既有 `data-testid`（`pool-edit-*`），**不破坏** 2 个现有测试
- 单测：现有 2 条必须继续通过 + 新增渲染断言

### T3：翻新子池定义页（sub-pool-definition）

- 10 列裸表 → 结构化列表（类型 tag、名称+系统标记、标签、可见性/默认启用、关键词数、状态）
- 筛选区统一为工具栏卡片
- 详情/编辑保留弹窗（字段多，弹窗比抽屉更合适）

### T4：翻新管理端 Agent 列表（agents/ListView）

- 裸 `a-table` → 顶部 KPI（总数/启用/停用）+ 卡片或精修表格
- 权限点 tag 墙 → 省略 + tooltip / 折叠
- 自动化策略、预算格式化展示
- 5 个操作按钮（对话/编辑/定时/用量/删除）保留，改为更清晰的按钮组

### T5：翻新 Agent 对话页（agents/ChatView）

- 三栏精修：会话列表（选中态、时间）、消息区（气泡/工具调用卡）、记忆面板（KPI + 列表）
- 流式状态、空态、加载态统一

### T6：i18n 双侧同步 + 验证

- 新增文案同时改 `zh-CN/admin/agents.ts` + `en-US/admin/agents.ts`（及 `agentPool.ts`）
- 跑 `npx vitest run src/i18n/__tests__/parity.spec.ts`

### T7：收尾

- 全量 `src/views/admin` + hooks 回归
- ESLint、`vue-tsc`（与基线 61 个既有错误对比，零新增）
- 文档同步：`docs/prd/execution-roadmap.md` 登记本次 UX 翻新
- `python -m graphify update .`

## 五、验收标准

1. 4 个页面无手写裸 `<table>` 骨架，视觉与 ToolsView 同语言
2. 现有全部前端测试通过（AgentPoolView 2 条 + 新增）
3. `FailException` 缺陷修复并有反向测试（填错 cron 返回 400）
4. i18n parity 通过，无硬编码文案
5. ESLint 零告警；`vue-tsc` 错误数不高于基线 61

## 六、范围外（明确不做）

- 不新增后端能力、不改路由契约
- 不做 `invoke`/`drafts` 前端接入（设计预留）
- 不清理 `getAgentPoolConfig`/`getSubPoolDefinition` 未用函数（避免过度改动，仅在报告中登记）
