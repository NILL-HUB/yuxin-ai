# UX-3：资源运营补充上架/下架操作

> **状态**：✅ 已完成（MCP 补齐；Tools 判定非目标；Skills 待后端）
> **日期**：2026-09-21
> **归属**：管理端五板块 UX 治理（PRI2）
> **对应**：docs/prd/execution-roadmap.md「UX-3 资源运营补充上架/下架操作」

## 1. 背景与目标

roadmap UX-3：「每个商店页面加管理员视角的上架/下架按钮，而非仅复用公共商店组件」。

资源运营板块商店页现状盘点（后端按资源类型为“是否已有公开上下架字段/接口”）：

| 商店页 (router name) | Vue 文件 | 现状 | 后端上下架能力 |
|---|---|---|---|
| store/public-apps | StoreAppsView.vue | ✅ 已有上架/下架 | `PATCH /admin/apps/{id}`(is_public) + `POST /admin/apps/{id}/offline` |
| store/workflows | StoreWorkflowsView.vue | ✅ 已有上架/下架 | `PATCH /admin/workflows/{id}` + `POST /admin/workflows/{id}/offline` |
| store/mcp | StoreMcpView.vue | ⚠️ 仅复用公共 MCP 商店（adminMode），无上下架按钮 | ✅ `POST /admin/mcp/{id}/publish`、`POST /admin/mcp/{id}/unpublish`（mcp_service.publish_mcp_provider_for_admin，service 已封装 publishAdminMcp/unpublishAdminMcp） |
| store/tools | StoreToolsView.vue | ⚠️ 仅复用公共工具商店（内置工具，只读） | 工具商店=内置工具目录，**无用户可发布资源**，无上下架字段/接口 |
| store/skills | StoreSkillsView.vue | ⚠️ 仅复用公共技能商店 | ❌ 无上下架能力（实测确认）：`SkillPackage` 模型（api/internal/model/skill.py）**无 is_public 字段**，仅 `enabled`/`published_at`/`sync_status`；skill_service / skill_import_service 提供 enable/disable/sync/rollback，**无 publish/unpublish 接口**；admin-skills.ts 亦无 publish 调用 |

**结论**：
- Apps/Workflows 已满足 UX-3，无需改动。
- **MCP 为可交付项**：后端与 service 层已就绪，缺 UI——实现真实管理页/卡片上下架按钮。
- **Tools**：工具商店是内置工具公共目录，无“租户可上下架”对象，判定**非 UX-3 目标**（保持只读展示）。
- **Skills**：已实测确认后端无 is_public/发布接口（`SkillPackage` 模型无 is_public，skill_service 无 publish/unpublish），补上下架需后端先加能力，标记为**后端未接入**（不伪造调用不存在的端点）。

## 2. MCP 商店改动清单（本计划落地主体）

### 2.1 StoreMcpView 增加管理员上下架（去掉“不支持”提示）

文件：`ui/src/views/admin/StoreMcpView.vue`、`ui/src/views/store/mcp/ListView.vue`

- StoreMcpView 不再包 `StoreUnsupportedView`（MCP 已有上下架能力），保留 `:admin-mode="true"` 复用公共列表。
- mcp ListView 在 `adminMode` 下，卡片操作区显示「上架/下架」按钮（按 `provider.is_public` 判断）：
  - `is_public=false` → 按钮「上架」→ `publishAdminMcp(provider.id)` → `POST /admin/mcp/{id}/publish`
  - `is_public=true` → 按钮「下架」→ `unpublishAdminMcp(provider.id)` → `POST /admin/mcp/{id}/unpublish`
  - 成功后刷新列表 + Message 提示；按钮需权限 `mcp:manage` 才可点。
- 约束：公共用户态（adminMode=false）不渲染任何上下架按钮，纯展示不变。

### 2.2 i18n（zh/en 同步，走 admin.storeOps 命名空间）

- 新增 `admin.storeOps.actions.publish` / `unpublish` / `publishSuccess` / `unpublishSuccess` / `publishFailed` / `unpublishFailed`（若已有则复用）。
- 运行 `npx vitest run src/i18n/__tests__/parity.spec.ts`。

## 3. Skills / Tools 边界说明（明确“未接入”）

- Tools：内置工具公共目录，无上下架对象，保持只读（计划不改）。
- Skills：已实测确认后端无 is_public/发布端点（见上表），标注「已提供能力但未接入（需后端先行）」；不伪造前端调用。

## 4. 接线审查自检

| 新增/改动符号 | 入口 |
|---|---|
| mcp 商店页「上架」按钮 | StoreMcpView → mcp ListView(adminMode) 卡片 → `publishAdminMcp` → `POST /admin/mcp/{id}/publish` |
| mcp 商店页「下架」按钮 | 同上 → `unpublishAdminMcp` → `POST /admin/mcp/{id}/unpublish` |

## 5. 文档同步

- `docs/prd/execution-roadmap.md`：UX-3 标记 ✅ 已完成，登记「已完成（UX 快速修复）」表（若 Skills 未接入则在此注明范围：MCP 完成、Skills 待后端）。
- `python -m graphify update .`

## 6. 回归确认

- `npx vitest run src/views/admin/__tests__/StoreMcpView.spec.ts src/i18n/__tests__/parity.spec.ts`（MCP 用例若新建 spec）
- 涉及 mcp 后端：`python -m pytest api/test/...`（确认 publish/unpublish 路由测试）