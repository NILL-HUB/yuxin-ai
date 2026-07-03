# Admin 后台职责分离重构计划（v2 — 基于共创分身架构调整）

> **目标：** 消除 admin 端与 space 端的双轨混乱，明确五板块职责边界，为用户共创分身与创作者经济铺路。

**架构原则：**
- 同一份数据只能在一个板块编辑，其他板块只读展示。
- 资源编排 = 系统级资源 CRUD（管理员创建的系统 App/Tool/Workflow/MCP）。
- 资源运营 = 当前做系统资源上下架（过渡）；未来演进为用户创作分身审核 + 创作者经济管理 + 商店运营（详见架构文档第 19 节）。
- 两个板块发展方向完全不同，不合并、不弱化，但当前阶段的列表重叠需通过操作边界明确来解决。
- space 端配置中心降级为已发布资源的浏览/调试入口，创建功能统一到 admin 资源编排。

**技术栈：** Vue 3 + Arco Design + Vite（前端），Flask + SQLAlchemy（后端）

---

## 设计决策（基于共创分身架构的新理解）

### 为什么资源运营板块保留且不弱化

资源运营板块的未来定位是"用户创作内容审核 + 创作者经济管理 + 商店运营"（架构文档 19.7 节）。当前它做系统资源上下架只是过渡阶段——未来分身体系上线后：
- 系统资源不需要"上下架"（管理员创建即生效）
- 分身才需要审核、上下架、质量监控
- 资源运营会自然分离出自己独立的管理对象（用户分身）

因此当前阶段不删除资源运营的商店页面，而是：
1. 明确操作边界：编排=CRUD，运营=上下架，消除重复的创建入口
2. 资源运营列表保留只读展示 + 上下架操作，移除创建/编辑入口
3. 为未来分身审核功能预留扩展空间

### 列表重叠的当前处理策略

当前工作流/应用的列表在编排和运营两个板块都存在（同一接口）。处理策略：
- 编排页：完整 CRUD（创建/编辑/删除）+ 池治理字段只读展示
- 运营页：只读列表 + 上下架/强制下架/预览商店
- 两边列表重复是可接受的过渡状态（数据源相同但操作不同）
- 未来分身体系上线后，运营页会转向分身审核，自然与编排页分离

---

## Phase 1：admin 端自包含 — 消除 space 组件复用（最紧急）

**问题：** 9 条 admin 路由的 component 指向 `@/views/space/...`，导致点击创建时跳回 `/space/...`。

| admin 路由 | 复用的 space 组件 |
|---|---|
| `/admin/apps/:id/edit` | `space/apps/DetailView.vue` |
| `/admin/apps/:id/published` | `space/apps/PublishedView.vue` |
| `/admin/apps/:id/analysis` | `space/apps/AnalysisView.vue` |
| `/admin/apps/:id/versions` | `space/apps/VersionComparisonView.vue` |
| `/admin/apps/:id/prompt-compare` | `space/apps/PromptCompareView.vue` |
| `/admin/workflows/:id/edit` | `space/workflows/DetailView.vue` |
| `/admin/datasets/list` | `space/datasets/ListView.vue` |
| `/admin/tools/list` | `space/tools/ListView.vue` |
| `/admin/mcp/list` | `space/mcp/ListView.vue` |

### Task 1.1：创建 admin 版 App 编辑器（含 5 个子页面）

**Files:**
- Create: `ui/src/views/admin/apps/AdminAppDetailView.vue`（复制自 `space/apps/DetailView.vue`）
- Create: `ui/src/views/admin/apps/AdminAppPublishedView.vue`（复制自 `space/apps/PublishedView.vue`）
- Create: `ui/src/views/admin/apps/AdminAppAnalysisView.vue`（复制自 `space/apps/AnalysisView.vue`）
- Create: `ui/src/views/admin/apps/AdminAppVersionComparisonView.vue`（复制自 `space/apps/VersionComparisonView.vue`）
- Create: `ui/src/views/admin/apps/AdminAppPromptCompareView.vue`（复制自 `space/apps/PromptCompareView.vue`）
- Modify: `ui/src/router/index.ts`

**核心改动：**
1. 复制 5 个 space apps 组件到 admin/apps/ 下
2. 替换所有 `router.push({ name: 'space-apps-*' })` 为 `admin-app-*`
3. 替换 `ToolsAbilityItem.vue` 中 `space-tools-list` 链接为 `admin-tools`
4. 修改 router 中 5 条 admin-app-* 路由指向新组件

### Task 1.2：创建 admin 版 Workflow 编辑器

**Files:**
- Create: `ui/src/views/admin/workflows/AdminWorkflowDetailView.vue`（复制自 `space/workflows/DetailView.vue`）
- Modify: `ui/src/router/index.ts`

**核心改动：**
1. 复制 space/workflows/DetailView.vue 到 admin/workflows/
2. 替换所有 `space-workflows-*` 路由名为 `admin-workflow-*`
3. 替换 `ToolNodeInfo.vue` 中 `space-tools-list` 链接为 `admin-tools`
4. 修改 router 中 `admin-workflow-edit` 指向新组件

### Task 1.3：移除 admin 端对 space ListView 的复用

**Files:**
- Modify: `ui/src/router/index.ts`（移除 `admin-dataset-list`、`admin-tool-list`、`admin-mcp-list` 三条路由）
- Modify: `ui/src/views/admin/AdminMcpView.vue`（移除跳转 `admin-mcp-list` 的"管理"按钮，改为直接在 AdminMcpView 内完成管理）

**说明：** admin 端已有 `ToolsView.vue`、`AdminMcpView.vue`、`AdminDatasetsView.vue` 独立列表页，不需要复用 space ListView。移除这三条冗余路由。

---

## Phase 2：资源编排 vs 资源运营操作边界明确

### Task 2.1：资源编排页面 — 只保留 CRUD

**Files:**
- Modify: `ui/src/views/admin/AdminWorkflowsView.vue`（移除 `toggle-public` 相关 UI）
- Modify: `ui/src/views/admin/AppsView.vue`（确认无上架下架按钮）

**原则：** 资源编排页面只做 创建/编辑/删除，不做上架/下架。上架下架是资源运营的职责。

### Task 2.2：资源运营商店页面 — 只做上下架，移除创建入口

**Files:**
- Modify: `ui/src/views/admin/StoreWorkflowsView.vue`（移除跳转编辑器入口，保留上架/下架/强制下架/预览）
- Modify: `ui/src/views/admin/StoreAppsView.vue`（移除详情跳转，保留上下架操作）
- Modify: `ui/src/views/admin/StoreMcpView.vue`（移除 `CreateOrUpdateMcpModal` 创建入口）
- Modify: `ui/src/views/admin/StoreToolsView.vue`（移除创建 API Tool 入口）

**原则：** 资源运营页面只做 上架/下架/强制下架/预览商店，不做创建/编辑/删除。列表只读展示。

### Task 2.3：资源运营页面增加"来源"标识

**Files:**
- Modify: `ui/src/views/admin/StoreWorkflowsView.vue`（顶部增加 alert：资源创建请前往资源编排板块）
- Modify: `ui/src/views/admin/StoreAppsView.vue`（同上）

**说明：** 明确告知用户资源运营板块只管上下架，创建去资源编排。未来分身体系上线后，这里会变为分身审核入口。

---

## Phase 3：清理 space 端创建功能

### Task 3.1：移除 SpaceLayoutView 的创建按钮

**Files:**
- Modify: `ui/src/views/space/SpaceLayoutView.vue`

移除顶部 5 个创建按钮（App/Tool/Workflow/MCP/Dataset）和 `handleCreate` 方法。

### Task 3.2：移除 space 端各 ListView 的创建模态窗

**Files:**
- Modify: `ui/src/views/space/apps/ListView.vue`
- Modify: `ui/src/views/space/tools/ListView.vue`
- Modify: `ui/src/views/space/workflows/ListView.vue`
- Modify: `ui/src/views/space/mcp/ListView.vue`
- Modify: `ui/src/views/space/datasets/ListView.vue`

移除创建模态窗、`create_type` 监听、创建相关 import。保留列表展示和搜索。

**注意：** `/my-knowledge` 路由复用 `datasets/ListView.vue`，需确认此入口不受影响。

### Task 3.3：space 端编辑入口重定向到 admin 端

**Files:**
- Modify: `ui/src/views/space/apps/ListView.vue`（编辑按钮跳转 `admin-app-edit`）
- Modify: `ui/src/views/space/workflows/ListView.vue`（编辑按钮跳转 `admin-workflow-edit`）

space 端保留浏览，但点击"编辑"时跳转到 admin 端编辑器。

---

## Phase 4：验证与收尾

### Task 4.1：端到端验证

- admin 端创建 API Tool → 工作流编辑器中选择该工具 → 保存工作流（不跳回 space）
- admin 端创建 App → 打开 App 编辑器（不跳回 space）→ 绑定工作流
- 资源运营商店页面：只看到上下架操作，无创建入口
- space 端：无创建按钮，浏览正常，编辑跳转 admin

### Task 4.2：更新架构文档与执行路线图

- 更新 `docs/prd/execution-roadmap.md` 记录重构完成状态

---

## 与共创分身架构的关系

本次重构是共创分身体系的前置条件：
1. **admin 端自包含**：未来分身审核功能在 admin 资源运营板块实现，不能依赖 space 组件
2. **操作边界明确**：资源编排管系统资源 CRUD，资源运营未来管分身审核，现在先明确边界
3. **space 端清理**：为未来用户创作工作室 `/studio` 腾出职责空间，space 只做浏览/调试

共创分身体系本身（L0 创作、质量分、积分计费等）是后续独立阶段，不在本次重构范围内。

---

## 风险与注意事项

1. **`/my-knowledge` 路由**：复用 `space/datasets/ListView.vue`，清理创建功能时需确认此入口不受影响
2. **admin 端编辑器内嵌链接**：`ToolNodeInfo.vue` 和 `ToolsAbilityItem.vue` 中的"创建工具"链接必须改为 admin 端路由
3. **后端无需改动**：admin CRUD API 已完成，本计划只涉及前端路由和组件重构
4. **渐进式部署**：每个 Phase 完成后构建验证
