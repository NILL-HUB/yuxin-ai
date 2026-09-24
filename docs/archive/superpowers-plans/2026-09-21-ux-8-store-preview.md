# UX-8：商店预览模式

> **状态**：✅ 已完成
> **日期**：2026-09-21
> **归属**：管理端五板块 UX 治理（PRI3）
> **对应**：docs/prd/execution-roadmap.md「UX-8 商店预览模式」

## 1. 背景与目标

roadmap UX-8：「资源运营上架操作旁加'预览商店效果'按钮，让管理员看到用户视角」。

现状盘点（实测）：
- **用户视角商店路由仅 `/store/public-apps`**（公共应用商店，router L69）；`StoreAppsView` 已有「预览商店效果」按钮（`window.open('/store/public-apps')`，storeOps.ts 已有 previewStore/previewStoreTip 键）。
- **workflows/tools/skills/mcp 无用户端商店路由**：`store/{tools,skills,mcp}/ListView.vue` 均支持 `adminMode=false` 用户态渲染（调公共 API），但仅被 admin 页复用；用户侧商店入口只有 app studio 内的选择器模态框。workflows 连用户端商店列表页都没有（仅 `/admin/store/workflows/:id/preview` admin 预览）。
- `StoreMcpView`（去掉 Unsupported 后直接复用 ListView）、`StoreSkillsView`、`StoreToolsView`（后二者包 `StoreUnsupportedView`）均无预览按钮。

**落地决策**：新增用户端路由 `/store/tools`、`/store/skills`、`/store/mcp`（复用现成 ListView 用户态渲染，与 `/store/public-apps` 同级）；三个 admin 商店页加悬浮「预览商店效果」按钮跳转对应用户端页。**Workflows 无用户端商店页，本次不提供预览按钮**（标注待用户端工作流商店落地）。

## 2. 改动清单

### 2.1 路由（ui/src/router/index.ts，/store/public-apps 块邻近同级新增）

- `store/tools` → `store/tools/ListView.vue`
- `store/skills` → `store/skills/ListView.vue`
- `store/mcp` → `store/mcp/ListView.vue`

### 2.2 三个 admin 商店页加预览按钮（window.open 用户端路由）

- `StoreMcpView.vue`：外层加 `relative` 容器，右上角悬浮 `a-tooltip`+`a-button`（data-testid store-preview-mcp）→ `window.open('/store/mcp')`。
- `StoreSkillsView.vue` / `StoreToolsView.vue`：同上（保留 StoreUnsupportedView 语义），按钮 data-testid store-preview-skills / store-preview-tools。
- 复用 i18n `admin.storeOps.previewStore` / `previewStoreTip`（zh/en 已存在，无需增键）。

### 2.3 Workflows

- `StoreWorkflowsView` 不改（无用户端商店页）；roadmap 注明边界。

## 3. TDD

新建三个 wrapper spec（红 → 绿）：
- `StoreMcpView.spec.ts`：断言渲染「预览商店效果」按钮、点击调 `window.open('/store/mcp', '_blank')`。
- `StoreSkillsView.spec.ts` / `StoreToolsView.spec.ts`：同模式（/store/skills、/store/tools）。
- mock `window.open`、`vue-i18n`，shallowMount + stub 子组件。

## 4. 接线审查自检

| 新增符号 | 入口 |
|---|---|
| `/store/mcp`/`store/skills`/`store/tools` 路由 | 用户可直接访问商店浏览（公共 API adminMode=false） |
| 预览按钮 | StoreMcpView/StoreSkillsView/StoreToolsView 右上 → `window.open('/store/{type}')` |

## 5. 文档同步

- `docs/prd/execution-roadmap.md`：UX-8 标 ✅ + 已完成表登记（注明 workflows 无用户端页边界）。
- `python -m graphify update .`

## 6. 回归确认

- `npx vitest run src/views/admin/__tests__/StoreMcpView.spec.ts src/views/admin/__tests__/StoreSkillsView.spec.ts src/views/admin/__tests__/StoreToolsView.spec.ts src/i18n/__tests__/parity.spec.ts`