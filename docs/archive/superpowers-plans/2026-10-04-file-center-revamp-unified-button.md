# 文件中心前端翻新 + 统一按钮组件（实施计划）

- 状态：**已完成（2026-10-04）**，已归档至 `docs/archive/superpowers-plans/`
- 关联 spec：`docs/superpowers/specs/2026-09-30-user-file-center-design.md`
- 触发：用户反馈「文件中心页面太丑、按钮不统一，一个蓝色按钮改半天，要和主题统一」

## 1. 后端落地检查结论（2026-10-04 实测）

| 项 | 状态 | 证据 |
|---|---|---|
| 表 `file_center_entry` + 迁移 | ✅ | 迁移 `o9f0a1b2c3d4`，全仓 169 个迁移收敛单 head `d5f6a7b8c9e0` |
| 服务 `FileCenterService` | ✅ | 树操作 + 读存 + `list_all_files` |
| HTTP 路由 6 端点 | ✅ | `api/app/http/file_center_routes.py`，`asgi_app.py:268` 已注册；`GET /api/space/files` 未登录实测返回 401 JSON（路由真实存在） |
| Agent 工具 7 op + 挂载 | ✅ | `providers/file_center/file_center.py`（list/mkdir/move/rename/delete/read/save_artifact），`assistant_agent_service.py:1046` 挂载 |
| 真实数据 | ✅ | 生产库 `file_center_entry` 5 条（3 upload + 2 artifact），写入/读取链路真实工作过 |
| ⚠️ `GET /space/files/all` | 有路由无调用方 | 前端未接、工具未用 → 本次翻新由「全部文件」视图接上（补断链） |

**结论：后端完全落地，无阻断问题。** 阶段 2/3（桌面端 UI、云盘连接器）为 spec 中已标注的「愿景设计、未实现」，不属本次范围。

## 2. 按钮补丁密度量化（动手前测量）

| 测量项 | 实测 | 判读 |
|---|---|---|
| 统一按钮组件 | **不存在**（`src/components/` 无封装） | 无权威入口 |
| `a-button` 直接使用 | **130 个 .vue 文件**，约 172+ 处带 type | 补丁散落 |
| 原生 `<button>` | 多组件（ChatComposer 单文件 5 处等） | 第二套并行写法 |
| 硬编码颜色 | `#165dff`(Arco 默认蓝) 6 处、`#1d4ed8` 11 处、`#2563eb` 4 处；rgb/blue 关键词 163 处命中 | 绕过 token |
| 主题机制 | `theme.css` 三层 token（`--tw-*` 52 项 / `--arcoblue-*` / `--aicss-*`），`--arcoblue-6` 已联动 Arco 主色链 | **轮胎存在** |

**判定：轮胎 + 补丁**（主题 token 体系是成型轮胎；按钮直接使用与硬编码颜色是可收纳的补丁）。
**处置：补洞口** —— 新建统一按钮组件（单一权威入口，只消费 token），文件中心先行全面采用；其余 130 个文件渐进迁移（本计划登记迁移路径，不在本次全量替换以控制风险）。

## 3. 交付物

1. `ui/src/components/AppButton.vue`：统一按钮组件
   - 语义 variant：`primary / secondary / outline / text / ghost / danger`（映射 Arco type/status，颜色全部来自主题 token）
   - `size`、`iconOnly`（圆形）、`loading`、`disabled`、icon 插槽
   - 禁止调用方写颜色样式；圆角跟随主题
2. `ui/src/components/__tests__/AppButton.spec.ts`：单测（TDD 先行）
3. `ui/src/views/space/files/ListView.vue` 翻新：
   - 网格卡片视图（文件夹/文件卡片、图片缩略图、来源标签、hover 操作菜单）
   - 工具栏（面包屑 + 新建文件夹 + 刷新），全部按钮走 `AppButton`
   - 空状态美化（图标 + 引导文案 + 主操作）
   - 「我的文件 / 全部文件」双视图，接上 `/space/files/all`（补断链）
4. 前端 `models/file-center.ts` + `services/file-center.ts`：新增全部文件类型与接口
5. 后端 `list_all_files` 补 `url` 字段（复用 `storage.get_file_url`，与 `list_children_view` 一致）
6. i18n `fileCenter.ts`（zh/en 同步）+ parity 测试通过

## 4. 不做的事（范围边界）

- 不替换其余 130 个文件的既有按钮（渐进迁移，后续任务按页推进）
- 不给表加字段（大小/时间展示留待后续；schema 无该字段）
- 不做搜索、右键菜单、拖拽移动（后续迭代）

## 5. 验收

- `npx vitest run src/components/__tests__/AppButton.spec.ts` 通过
- `npx vitest run src/i18n/__tests__/parity.spec.ts` 通过
- `npm run build` 通过
- 页面实测：目录浏览、全部文件、新建/重命名/移动/删除、空状态、图片缩略图
- 浅色/暗色两套主题下按钮与页面均正常（颜色全部来自 token）

## 6. 实施结果（2026-10-04）

**交付全部完成**，并在检查过程中发现并修复 3 处额外缺陷（均已实测验证）：

| 缺陷 | 根因 | 修复 |
|---|---|---|
| 文件中心页面长期空白（「看着太丑」的直接原因） | `ui/src/services/file-center.ts` 未解包 `BaseResponse.data`，`result.items` 恒为 undefined；前端自落地起从未显示过数据 | service 统一 `BaseResponse<T>` + `response.data`，补契约测试 |
| 全站 Arco 按钮显示默认蓝（「一个蓝色按钮改半天」的根因） | 主题的 `--arcoblue-*` 覆盖写在 html 层，被 arco.css 的 **body 层**同名定义盖掉 | 主色链下沉 body 层（`html[data-theme=...] body`），修复后浅色 233,30,99 / 暗色 255,0,127 |
| 文件列表文件夹图标不渲染 | `<icon-folder>` 等图标未在 `plugins/arco.ts` 注册 | 注册 IconFolder/IconFolderAdd/IconFileImage/Pdf/Video/Audio |

另有后端健壮性修复：有效 JWT 但账号已注销时 `_resolve_account` 返回 `(None, None)` 致 500 → 两处调用点改为返回 404 `account_not_found`（孤儿测试数据实测触发）。`list_all_files` 补 `url` 字段，URL 生成收敛为 `_file_url_map` 单一入口。

**验证**：前端 vitest 24 项（AppButton 8 / ListView 5 / service 4 / i18n parity 7）全过；后端 file_center + 认证相关测试 114 项全过；`vite build` 通过；浏览器实测（浅色/暗色截图）：根目录 → 子目录 → 全部文件视图、空状态、Agent 产物文件卡片均正常渲染，按钮全部为主题色。
