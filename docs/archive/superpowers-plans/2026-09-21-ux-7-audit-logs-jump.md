# UX-7：审计日志加跳转

> **状态**：✅ 已完成
> **日期**：2026-09-21
> **归属**：管理端五板块 UX 治理（PRI3）
> **对应**：docs/prd/execution-roadmap.md「UX-7 审计日志加跳转」

## 1. 背景与目标

roadmap UX-7：「AuditLogsView 的 resourceType/resourceId 可点击跳转到对应资源管理页」。

现状（实测）：
- `AuditLogsView.vue` 表格「资源」列目前展示 `resource_name` + 截断 `resource_id`（tooltip 显示完整值），`resource_type` 为纯展示 a-tag，均**不可点击**；无 `useRouter`。
- 各资源类型多数有对应 admin 列表页路由（已核实 router/index.ts）：admin_user→/admin/admin-users、customer_user→/admin/users、role→/admin/roles、app→/admin/apps、workflow→/admin/workflows、tool/api_tool→/admin/tools、mcp/mcp_provider→/admin/mcp、skill/skill_package→/admin/skills、plan→/admin/plans、redeem_code/batch→/admin/billing、system_knowledge/system_prompt→/admin/system-knowledge、agent_pool_config→/admin/agent-pool、tool_governance_policy→/admin/tool-governance、model→/admin/models、orchestration_flag→/admin/orchestration-flags、sub_pool_definition→/admin/sub-pool-definition、policy_change_draft→/admin/routing-quality/suggestions、storage/storage_file/upload_file/os_file→/admin/storage、schedule_task→/admin/schedules、purchase_order→/admin/orders。
- 无 admin 管理页的类型（conversation/memory/dataset/knowledge_base/knowledge_document/external_data_source/distribution_relation/billing_config 等）**不渲染跳转**。

## 2. 改动清单

文件：`ui/src/views/admin/AuditLogsView.vue`、`ui/src/views/admin/__tests__/AuditLogsView.spec.ts`

- 引入 `useRouter`；新增 `RESOURCE_TARGETS`（类型→路由路径，仅登记有明确管理页的类型）与 `resourceTarget()` / `openResourcePage()`。
- 表格「资源类型」单元格：命中 target 时渲染可点击（`data-testid="audit-resource-jump-${log.id}"`，sky 色/下划线），点击 `router.push(target)`；未命中保持只读 a-tag。
- 表格「资源」列 resource_id：命中 target 时截断 id 可点击（`data-testid="audit-resource-id-jump-${log.id}"`），tooltip 仍显示完整值；未命中保持原样。

## 3. TDD

`AuditLogsView.spec.ts` 新增用例（先红）：
- mock `vue-router` 的 `useRouter` → push 断言被调用。
- 「resourceType 带 target 时点击跳转到对应管理页」（workflow → /admin/workflows）。
- 「resourceId 可点击跳转」（同路径）。
- 现有 6 用例回归（resource 姓名/截断 id/详情弹窗等不变）。

## 4. 接线审查自检

| 新增符号 | 入口 |
|---|---|
| `RESOURCE_TARGETS`/`openResourcePage` | 审计日志表格 resource_type/resource_id 单元格点击 → `router.push(target)` → 目标 admin 路由（已核实存在） |
| 无 target 类型 | 保持只读，不渲染点击 |

## 5. 文档同步

- `docs/prd/execution-roadmap.md`：UX-7 标 ✅ + 「已完成（UX 快速修复）」表登记。
- `python -m graphify update .`

## 6. 回归确认

- `npx vitest run src/views/admin/__tests__/AuditLogsView.spec.ts src/i18n/__tests__/parity.spec.ts`