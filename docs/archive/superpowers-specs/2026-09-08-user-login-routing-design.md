# 用户端登录页路由化改造设计

> 更新日期：2026-09-08
> 定位：把用户端登录从"弹窗（LoginModal）"改为"独立登录页 + 路由守卫统一拦截"，为桌面客户端内嵌复用 LoginView 铺路。

## 0. 背景与目标

现状：用户端登录以 `LoginModal` 弹窗形式存在（DefaultLayout/HomeView 等内嵌），未登录用户仍可进入 `/home`（新建会话页）与多数页面，点操作时才弹窗登录。完整登录页 `LoginView`（`/auth/login`）已存在且功能完整（密码/邮箱/手机登录 + 注册 + 异地挑战 + 找回密码），但页面入口未作为默认登录途径。

目标：
1. 未登录访问"需登录页面" → 重定向 `/auth/login?redirect=<原路径>`，登录成功后回跳原路径。
2. 移除内部 `LoginModal` 弹窗登录体系，所有"未登录需登录"场景统一跳登录页。
3. 登录态被清（401 / token 过期）→ 自动跳登录页（带回跳）。
4. 对外分享页保持公开（店铺公开列表、应用分享预览），游客可浏览，但其中的"需登录操作"跳登录页。
5. `/home`（新建会话页）从公开改为需登录。
6. WebApp（`/web-apps/:token`）改需登录（任务 B 已于 2026-09-08 随改造完成：后端 `/web-apps` 全部强制 `_resolve_account`、visitor_id 机制移除、存量 visitor 会话清理迁移 903f7e9）。

## 1. 公开路由白名单（保留游客可见）

| 路由 | 说明 |
| --- | --- |
| `/auth/login` | 登录页 |
| `/auth/authorize/:provider` | OAuth 回调 |
| `/errors/404` `/errors/403` | 错误页 |
| `/store/public-apps` | 店铺公开列表（游客浏览） |
| `/store/public-apps/:app_id/*` | 应用分享预览（游客浏览） |

其余全部路由（含 `/home`、`/web-apps/:token`、`/admin` 除外用户路由）未登录 → 跳登录页。

## 2. 核心改动

### 2.1 路由守卫（`ui/src/router/index.ts`）

- `PUBLIC_ROUTE_NAMES` 收缩为上述白名单。
- `getAuthGuardRedirect` 未登录时改为返回 `{ path: '/auth/login', query: { redirect: path } }`（不再回 `/home`）。
- 需要登录的页面若 `meta.requiresAuth` 缺失，靠白名单之外一律拦截兜底。
- admin 端路由保持现有 `/admin/login` 语义不变。

### 2.2 登录成功回跳（`LoginForm.vue`）

- 登录成功后（`redirectAfterLogin` 且非 embedded）：
  - 若 `route.query.redirect` 存在且合法（站内路径，非 `/auth/login` 自身）→ `router.replace(redirect)`。
  - 否则维持现有 `/home` 逻辑。
- 新增 `redirect` 参数的合法性校验（防开放重定向：仅允许站内以 `/` 开头且不以 `//` 开头的路径）。

### 2.3 移除弹窗登录体系

- `LoginModal.vue`：删除组件文件（或保留但不再被引用——倾向直接删除）。
- 各调用点改跳登录页（`router.push({ path: '/auth/login', query: { redirect: currentPath } })`，或复用统一 helper）：

| 文件 | 现状 | 改为 |
| --- | --- | --- |
| `DefaultLayout.vue` | `openLoginModal` / `goHomeAndOpenLogin` / `handleAuthRequired`(弹窗) / 侧栏登录按钮 | 统一 helper：未登录点"登录"→ 跳登录页带 redirect |
| `HomeView.vue` | `handleShowLoginModal`/`ensureLogin`/watch 弹窗/`<login-modal>` | `/home` 需登录后这些守卫多数不再触发；`ensureLogin` 改为跳登录页（保留 token 页内过期的兜底）；移除组件引用 |
| `store/public-apps/ListView.vue` | 点 fork 未登录派发 AUTH_REQUIRED_EVENT | 直接跳登录页带 redirect（保留游客浏览） |
| `store/public-apps/AppPreviewLayoutView.vue` | 同上 | 同上 |
| `external-data-sources/ListView.vue` | 点操作未登录 | 跳登录页 |
| `openapi/api-keys/ListView.vue` | 同上 | 跳登录页 |
| `space/datasets/components/ExternalDataSourceModal.vue` | 同上 | 跳登录页 |

- 统一 helper：`ui/src/utils/login-redirect.ts` 导出 `redirectToLogin()`：`router.push({ path: '/auth/login', query: { redirect: router.currentRoute.value.fullPath } })`（若已在登录页则不动作）。

### 2.4 401 踢出（`request.ts` + 监听方）

现状：401 → `handleUnauthorized` 派发 `AUTH_REQUIRED_EVENT`（`llmops:auth-required`）→ `DefaultLayout` 监听弹窗。

改为：
- `request.ts` 的 `handleUnauthorized` 保持派发事件（语义改为"登录态已失效"），或直接跳转。倾向：保留事件派发，但监听方（DefaultLayout 移除后）改为**全局监听**——在 `main.ts` 或 router 层统一监听 `AUTH_REQUIRED_EVENT` → `redirectToLogin()`。
- 需防重复跳转：已在 `/auth/login` 则不重复 push。
- `NO_PROMPT_PUBLIC_GET_ROUTE_NAMES`（web-apps 等）语义复核：已完成——WebApp 改需登录后，这些页 GET 401 现会触发登录跳转（不再"静默清凭证"）。

### 2.5 顶层布局承载

`/auth/login` 挂在 BlankLayout（无侧栏）。未登录被拦时跳转登录页——此时**不渲染 DefaultLayout**（因为 DefaultLayout 是受保护布局）。路由结构上 `/auth/login` 已在 BlankLayout 下，天然满足。

### 2.6 根路径 `/` 语义

`/` redirect `/home`，`/home` 需登录 → 未登录访问 `/` 最终跳登录页。可接受。

## 3. 关键边界与风险

| 风险 | 对策 |
| --- | --- |
| 开放重定向 | redirect 参数校验站内路径 |
| 登录页自身 401 循环 | 已在登录页不触发跳转 |
| 游客分享页点登录跳转后回跳 | 回跳原分享页路径，游客继续浏览 |
| store 公开页 API 未登录是否 401 | 需确认公开接口无鉴权（getPublicApps 等），否则游客浏览也会 401 踢出（破坏"游客可看"）——**实施前需核验 store 公开接口鉴权** |
| DefaultLayout 移除弹窗后 AUTH_REQUIRED_EVENT 无人监听 | 改在 main.ts/router 全局监听 |
| 移除弹窗影响 HomeView 大量 ensureLogin 逻辑 | `/home` 需登录后多数逻辑成死代码，精简保留 token 过期兜底 |

## 4. 验证

- 前端单测（受影响组件的 spec：HomeView/DefaultLayout/chat-stream/LoginForm 相关）。
- `npm run type-check`、`npm run test:unit`。
- 浏览器手动验证：未登录访问 `/home`→跳登录页；登录→回跳；游客访问 store 公开页可浏览、点 fork→跳登录页；伪造过期 token 触发 401→跳登录页。

## 5. 相关文档
- 桌面端复用登录页：见 desktop 设计（后续）。
- WebApp 后端强制登录（任务 B，已完成：见"0. 背景与目标"第 6 条）。
