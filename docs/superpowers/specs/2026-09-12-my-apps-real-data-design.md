# 我的应用（my-apps）真实接口接线设计

> 更新日期：2026-09-12
> 定位：设计规格（已评审确认）。与「外部数据源前后端加固」设计（`2026-09-12-external-data-source-design.md`）相互独立，可分别实施。
> 背景：`product-vision.md` §三-12 判定「我的应用列表 = 壳子：整页 mock 假数据，真实接口已存在未接」。本设计将其接线为真实数据，并清理死代码。

## 0. 目标

让「我的应用」列表展示当前账号真实可用的应用（管理员分配 + 商店分叉），替换本地 mock；同时清理因接线而失效的死代码与 i18n 违规残留。

**不在本设计范围**：合伙人分身（审核/自定价/版本分发）、应用编辑能力、应用商店本身。

## 1. 已确认决策

| 项 | 决策 | 理由 |
| --- | --- | --- |
| 后端状态语义 | **维持现状**（forked 分支继续返回 `published`） | 现有 backend 注释明确「对用户呈现为可直接使用、不可编辑」，符合产品预期 |
| 前端草稿徽标 | **移除** | 后端 `/my/apps` 恒返回 `published`，草稿分支为永不触发的死代码 |
| `can_edit` | **后端补 schema 声明**（返回但不驱动 UI） | service 已返回、前端类型已声明，仅 schema 丢弃导致契约残缺；本轮先补齐契约，不开发编辑能力 |
| `is_public` | 不补 | 前端 `AssignedApp` 有该可选字段，但列表页不使用，无实际需求 |
| 分页 | 不引入 | 一次性网格展示，当前数据量可接受 |

## 2. 现状（代码验证）

| 层 | 现状 | 证据 |
| --- | --- | --- |
| 后端路由 | ✅ 已实现并注册 | `GET /my/apps`、`POST /my/apps/<uuid>/chat`（`api/app/http/apps_routes.py`；注册于 `asgi_app.py`） |
| 后端服务 | ✅ 完整（assigned + forked 双来源） | `api/internal/service/my_app_service.py` `list_my_apps` |
| 权限 | ✅ 普通用户 JWT 可访问 | `api/app/http/support.py` 用户端放行注释；`/my/apps` 不在封锁前缀内 |
| 前端 service | ⚠️ 存在但**无任何调用点** | `ui/src/services/my-apps.ts` `listMyApps` |
| 前端页面 | ❌ 列表用 9 条本地 mock | `ui/src/views/space/my-apps/ListView.vue` `mockApps` / `loadApps` |
| 对话 | ✅ 真实流式 | 同文件 `chatWithMyApp` + `applyChatStreamEvent` |

### 2.1 需要修正的既有缺陷

1. **`can_edit` 被 schema 丢弃**：`my_app_service._serialize_my_app` 返回 `can_edit`，但 `MyAppResp` 未声明 → marshmallow `dump` 默认丢弃未声明字段。
2. **前端 service 泛型与运行时语义不符**：`listMyApps` 声明 `get<MyAppListResponse['data']>`（即 `{ list }`），但 `request.ts` 的 `get<T>` 实际 `return json as T`，`json` 是完整信封 `{ code, message, data }`。按 `res.list` 取值会得 `undefined`，必须按 `res.data.list`。参照 `ui/src/services/admin-app-assignments.ts` 的正确写法（泛型传完整信封响应类型）。
3. **`getErrorMessage` 未导入**：`ListView.vue` 的 `catch` 分支调用 `getErrorMessage`，但文件未 import（当前即 TS 报错）。
4. **i18n 违规残留**：模板内多处硬编码中文（`全部应用`、`共 N 个`、`点击进入对话`、`打开`、`已发布`、页脚版权），违反仓库 i18n 强制规范。

## 3. 后端改动

### 3.1 `api/internal/schema/my_app_schema.py`

`MyAppResp` 增加 `can_edit`：

```python
class MyAppResp(Schema):
    id = fields.String()
    assignment_id = fields.String()
    name = fields.String()
    icon = fields.String()
    description = fields.String()
    assigned_at = fields.Integer(allow_none=True)
    source = fields.String(dump_default="assigned")
    status = fields.String(dump_default="")
    can_edit = fields.Boolean(dump_default=False)
```

**不改** `my_app_service.py`（状态语义与派生的 `source` 逻辑均维持现状）。

## 4. 前端改动

### 4.1 `ui/src/services/my-apps.ts`

修正泛型，使类型与运行时一致（返回完整信封，由调用方取 `.data`）：

```ts
import { get, ssePost } from '@/utils/request'
import { type MyAppChatRequest, type MyAppListResponse } from '@/models/app-assignment'

export const listMyApps = () => {
  return get<MyAppListResponse>('/my/apps')
}

export const chatWithMyApp = (...) => { /* 不变 */ }
```

### 4.2 `ui/src/views/space/my-apps/ListView.vue`

| 动作 | 说明 |
| --- | --- |
| 接真实接口 | `loadApps` 改为 `const res = await listMyApps(); apps.value = res.data?.list || []`，保留 loading 态与错误提示（`getErrorMessage`） |
| 删除 mock | 移除 `mockApps`（9 条）、`MockApp` 类型、`accent` 字段与相关注释 |
| 图标降级策略 | 原渐变配色来自 mock。改为：有 `app.icon` 用图片；无则用「应用名首字 + 主题色」渲染（`accentOf` 退化为主题变量，不再使用假配色数组） |
| 移除草稿徽标 | 删 `isDraft` 与草稿分支，保留「已发布」徽标 |
| 补 import | 引入 `getErrorMessage`（`@/utils/error`） |
| i18n 化 | 硬编码中文迁入 `myApps.*` 键（zh-CN 与 en-US 双侧同步） |

新增 i18n 键（两侧同名同结构；`myApps.*` 字典已存在，仅追加以下键）：

| 键 | zh-CN | en-US |
| --- | --- | --- |
| `myApps.sectionTitle` | 全部应用 | All apps |
| `myApps.countSuffix` | 共 {count} 个 | {count} total |
| `myApps.enterChatHint` | 点击进入对话 | Click to open chat |
| `myApps.open` | 打开 | Open |
| `myApps.published` | 已发布 | Published |
| `myApps.footer` | © 2026 钰见我 · 用心对话，随心创作 | © 2026 钰见我 · Talk with heart, create at will |

**删除已失效键**：`myApps.draft`（草稿徽标移除后不再使用）——须在 zh-CN 与 en-US 双侧同步删除，否则 parity 测试会因单侧残留而失败。

注：`myApps.loadFailed` 已存在，直接复用，无需新增。

### 4.3 不改动项

- 对话视图与流式逻辑（`chatWithMyApp` / `applyChatStreamEvent` / `withChatRenderId`）保持原样。
- 路由与侧边栏入口保持原样（`my-apps` 已有路由与导航）。

## 5. 数据流

```text
ListView.onMounted
  → listMyApps()                         GET /my/apps（Bearer JWT）
  → 后端 MyAppService.list_my_apps
      ├─ AppAssignment(status=active) → app(status=published)   → source="assigned"
      └─ App(account_id=me, original_app_id 非空)               → source="forked"
  → MyAppListResp.dump → { code, message, data: { list: [...] } }
  → 前端 res.data.list → apps 网格渲染
点击卡片 → openApp → chatWithMyApp → POST /my/apps/<id>/chat（SSE）
```

## 6. 错误处理

- 列表加载失败：`Message.error(getErrorMessage(error, t('myApps.loadFailed')))`，`apps` 保持空数组，页面展示空态（复用现有空态组件）。
- 未登录：路由 `meta.requiresAuth` 已拦截，页面内不额外处理。
- 对话失败：沿用现有 `catch` 分支（本轮仅补齐 `getErrorMessage` 导入使其生效）。

## 7. 测试

| 层 | 用例 |
| --- | --- |
| 后端 | `test/app/http/` 补断言：`GET /my/apps` 响应项含 `can_edit` 字段；`test/internal/service/test_my_app_service.py`（若存在）补 `can_edit` 序列化断言 |
| 前端 | `my-apps.spec.ts` 补：`listMyApps` 返回信封类型；`ListView` 以 mock service 渲染真实列表项（含空态与加载失败） |
| i18n | `npx vitest run src/i18n/__tests__/parity.spec.ts` 必须通过（zh/en 叶子键集合一致） |

## 8. 验收标准

1. 登录后「我的应用」展示账号真实应用（管理员分配的 + 商店分叉的），不再出现 9 条假数据。
2. 无应用时展示空态；加载失败有错误提示。
3. 点击卡片进入对话，流式回复正常。
4. `GET /my/apps` 响应包含 `can_edit`。
5. 页面无硬编码中英文展示文案；i18n parity 通过。
6. `npx vitest run`（前端）与后端相关测试全绿。

## 9. 风险与回滚

| 风险 | 缓解 |
| --- | --- |
| 真实账号下应用列表为空，视觉上"没东西" | 属真实状态；空态已有引导。验收时用已分配/已分叉的账号验证 |
| 图标字段为空导致视觉弱化 | 首字 + 主题色降级方案保证不空白 |
| 移除 mock 后若接口异常页面无数据 | 已补错误提示与空态，不会白屏 |

回滚：改动集中在 3 个文件（1 后端 schema + 2 前端），git revert 即可。
