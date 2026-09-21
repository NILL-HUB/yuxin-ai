# UX-2：AppsView 数据所有权统一 —— 路由字段编辑权迁移到池治理

> **状态**：已完成
> **日期**：2026-09-21
> **归属**：管理端五板块 UX 治理（PRI1）
> **对应**：docs/prd/execution-roadmap.md「UX-2 AppsView 重写 + 数据所有权统一」

## 1. 背景与目标

roadmap UX-2：「裸 HTML 重写为 Arco Design 风格；primary_pool / risk_level / routing_priority 只在 AgentPoolView 编辑，AppsView 只读展示」。

**现状核验**：

- `AppsView.vue` 已完成 Arco Design 重写（搜索/筛选/分页/批量下架删除/创建/回收站删除/只读卡片），**但**仍保留「编辑池治理字段」按钮 + `AgentMetadataEditor` 弹窗，可编辑 `primary_pool / secondary_pools / risk_level / model_tier / model_id / routing_priority` 等路由字段——违背「AppsView 只读展示」的职责定义。
- `AgentPoolView.vue` 管理 `AgentPoolConfig`（app_id + enabled + cost_level + capabilities + task_types），**不编辑** primary_pool / risk_level / routing_priority——所有权尚未迁移。
- 后端数据模型已定论：`agent_pool_entity.py` docstring 明确指出路由字段「已统一由 App.agent_metadata 承载」。`PATCH /admin/apps/<id>` 已支持 `agent_metadata`（admin_routes_1.py L57-77），AppsView 的 `updateAdminAppMetadata` 即走此端点；AgentPoolView 已 `listAdminApps`（带 agent_metadata），可据此预填。

**结论**：UX-2 是跨视图数据所有权迁移，非单纯删除。

## 2. 板块职责对齐

| 板块 | 职责 | UX-2 落地 |
|---|---|---|
| 资源编排（AppsView） | 资源实体 CRUD | 只读展示路由字段 + 归属提示，编辑权移交 |
| 池治理（AgentPoolView） | 使用规则策略（风险等级/路由优先级/可见性/限流） | 承接 primary_pool / risk_level / routing_priority 编辑 |

## 3. 改动清单

### 3.1 AppsView：移除路由字段编辑能力（只读展示）

文件：`ui/src/views/admin/AppsView.vue`

- 删除「编辑池治理字段」按钮（`data-testid="app-edit-metadata-*"`）
- 删除 `AgentMetadataEditor` 弹窗及其相关脚本：`metadataModalVisible` / `metadataSaving` / `editingMetadataApp` / `metadataForm` / `openEditMetadata` / `submitEditMetadata` / `DEFAULT_AGENT_METADATA` / `updateAdminAppMetadata` 调用；移除 `AgentMetadataEditor` import
- 保留卡片上池治理字段的**只读**展示（primary_pool / risk_level / routing_priority / enabled）+ 归属提示 + 跳转 AgentPoolView 链接
- 保留基本信息编辑（name/description/icon）——这属资源实体编辑，仍归 AppsView

文件：`ui/src/views/admin/__tests__/AppsView.spec.ts`

- 删除/改写「opens edit metadata modal」用例；`renderView` 不再 stub `AgentMetadataEditor`
- 保留只读展示 + 跳转提示断言；新增「不渲染 metadata 编辑按钮」断言

### 3.2 AgentPoolView：新增路由字段编辑（所有权落位）

文件：`ui/src/views/admin/AgentPoolView.vue`

- 池配置编辑表单增加 `primary_pool` / `risk_level` / `routing_priority` 三个字段（下拉/滑块）
- form 以 app_id 从 `apps`（listAdminApps 已含 agent_metadata）预填这三个字段
- 提交时：除原有 AgentPoolConfig 保存外，追加 `updateAdminAppMetadata(app_id, { primary_pool, risk_level, routing_priority, ...(现 agent_metadata 其余字段) })`，通过 `PATCH /admin/apps/<id>` 持久化
- **字段透传防护**：合并时必须保留 agent_metadata 中其余字段（cost_level/model_tier/model_id/capabilities/task_types 等），避免覆盖清空

文件：`ui/src/views/admin/__tests__/AgentPoolView.spec.ts`（若存在）

- 新增「提交时同步路由字段到 app 元数据」用例

### 3.3 后端接线核验

- `PATCH /admin/apps/<id>` 已支持 `agent_metadata`（admin_routes_1.py L68-75）——**无需新增后端端点**，仅前端接线
- 核对 AdminAppService.update_app 对 agent_metadata 的合并语义（整体替换 or 字段级合并），确保 AgentPoolView 合并策略一致

## 4. 接线审查自检

| 新增/改动符号 | 入口 |
|---|---|
| AgentPoolView 路由字段编辑 | 池配置编辑弹窗 → 提交 → `PATCH /admin/apps/<id>`（agent_metadata） |
| AppsView 删除编辑能力 | 卡片只读展示 + 「前往池治理」跳转 |

## 5. 文档同步

- `docs/prd/execution-roadmap.md`：UX-2 标记 ✅ 已完成，登记「已完成（UX 快速修复）」表
- 若需说明数据所有权约定，同步 `docs/prd/architecture-design.md` 池治理/资源编排相关段落（核对现有表述后决定）

## 6. 回归确认

- `npx vitest run src/views/admin/__tests__/AppsView.spec.ts src/views/admin/__tests__/AgentPoolView.spec.ts`
- `npx vitest run src/i18n/__tests__/parity.spec.ts`（i18n 增改必须 zh/en 双侧一致）
- 后端涉及 resolver: `python -m pytest api/test/app/http/test_admin_routes_1.py -q`