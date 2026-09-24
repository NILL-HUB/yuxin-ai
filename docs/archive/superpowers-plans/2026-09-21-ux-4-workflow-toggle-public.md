# UX-4：AdminWorkflowsView toggle-public 移到资源运营

> **状态**：✅ 已完成
> **日期**：2026-09-21
> **归属**：管理端五板块 UX 治理（PRI2）
> **对应**：docs/prd/execution-roadmap.md「UX-4 AdminWorkflowsView toggle-public 移到资源运营」

## 1. 背景与目标

roadmap UX-4：「上架是运营动作，不应在编排页面。移到资源运营的工作流商店页」。

现状盘点（实测）：
- **共享卡片** `ui/src/components/admin/AdminWorkflowCard.vue`：`canUpdate` 为真时渲染「visibility 切换按钮」（`data-testid="workflow-visibility-*"`，文案 `makePublic`/`makePrivate`）+ offline 按钮；visibility 标签（公开/私有）为只读展示。
- **编排页** `AdminWorkflowsView.vue`：绑 `@toggle-public="handleTogglePublic"`（调 `updateAdminWorkflow(id, { is_public })`）＋ `:can-update="true"`。
- **资源运营商店页** `StoreWorkflowsView.vue`：已绑 `@toggle-public="handleTogglePublic"` + `@offline="handleOffline"`，`can-update` 来自权限 `workflow:update` → **上架/下架入口已存在**。

**结论**：编排页的「公开切换（上架/下架）」与资源运营商店页重复，按 roadmap 移除编排页的 toggle-public；商店页为唯一操作入口。offline 按钮、批量上架/下架、导出/编辑/预览等编排操作保留（roadmap 仅点名 toggle-public）。

## 2. 改动清单

### 2.1 AdminWorkflowCard.vue（共享卡片新增 prop）

- 新增 `showVisibilityToggle?: boolean`（默认 `true`），visibility 切换按钮渲染条件改为 `canUpdate && showVisibilityToggle`。默认 `true` → 商店页零变化。

### 2.2 AdminWorkflowsView.vue（编排页移除 toggle-public）

- `AdminWorkflowCard` 传入 `:show-visibility-toggle="false"`，移除 `@toggle-public="handleTogglePublic"` 绑定。
- 删除 `handleTogglePublic` 函数与不再使用的 `updateAdminWorkflow` import。

### 2.3 i18n

- 无需改动：`admin.workflowsAdmin.actions.makePublic/makePrivate` 等键仍被卡片（商店页渲染路径）使用；zh/en 无增删。

## 3. TDD

`AdminWorkflowsView.spec.ts`：
- 现有用例「shows visibility label, store hint and workflow actions」断言 `workflow-visibility-wf-1` 存在 → 改为断言**不存在**；`workflow-offline-wf-1`、`workflow-export-wf-1` 仍存在；visibility 标签「公开」仍展示（只读）。
- 红 → 实现 → 绿。

## 4. 接线审查自检

- 移除后编排页无「上架/下架」入口；入口收敛到 `StoreWorkflowsView`（router `admin-store-workflows` 或等价路径）→ `updateAdminWorkflow(id,{is_public})` / `offlineAdminWorkflow(id)`。全仓搜索 `@toggle-public` 确认仅剩商店页绑定。

## 5. 文档同步

- `docs/prd/execution-roadmap.md`：UX-4 标 ✅ + 「已完成（UX 快速修复）」表登记。
- `python -m graphify update .`

## 6. 回归确认

- `npx vitest run src/views/admin/__tests__/AdminWorkflowsView.spec.ts src/i18n/__tests__/parity.spec.ts`