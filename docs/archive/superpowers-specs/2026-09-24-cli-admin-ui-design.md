# CLI 工具来源 admin 管理页 —— 设计规格

> **已归档（2026-10-03）**：该设计已全部落地（列表/注册/编辑/启停/删除、能力说明书表格化编辑与 JSON 模式、env 不回显不误改、路由与菜单接线），前端 12 例 + parity + 类型检查全绿。当前说明见 [01-agent-tool-pool.md](../../prd/modules/01-agent-tool-pool.md)；本文档仅保留设计过程与决策依据，**不代表当前实现**。

- 日期：2026-09-24
- 状态：已落地（设计期标注「未实现」为当时状态；2026-10-03 归档）
- 关联：[CLI 工具池设计规格](2026-09-24-cli-tool-pool-design.md)（后端 9 个任务已落地并通过 51 例测试）

## 1. 背景与现状

后端 `/admin/cli` CRUD 已就绪（含 RBAC `cli:*` 四权限 + 审计 `cli.create/update/delete`），
前端**零页面**：无路由、无菜单、无 service、无视图——管理员目前只能经 API 管理 CLI。

本规格补上最后一环，使「管理员手动注册 CLI 进工具池」在界面上闭环。

## 2. 后端 API 契约（真实签名，实现不得偏离）

| 方法 | 路径 | 请求 | 响应 |
| --- | --- | --- | --- |
| GET | `/admin/cli` | - | `{items: CliProvider[]}` |
| POST | `/admin/cli` | `{name*, command*, tool_schema*, label?, description?, category?, args?, env?, task_keywords?, timeout_seconds?, enabled?}` | `{id}` |
| GET | `/admin/cli/<id>` | - | `CliProvider`；404 `not_found` |
| PUT | `/admin/cli/<id>` | `{label?, description?, category?, command?, args?, env?, tool_schema?, task_keywords?, timeout_seconds?, enabled?}` | 成功消息；`tool_schema` 传空 → 400；404 `not_found` |
| DELETE | `/admin/cli/<id>` | - | 成功消息；404 `not_found` |

服务端 400 校验（前端**必须先于请求**做同样校验，避免往返）：
- `name` 非空、`command` 非空、`tool_schema` 为**非空 dict**（纯 CLI 无自描述能力，
  不声明能力说明书即不可用）。

`CliProvider` 形状（`CliService.to_dict`，唯一事实源）：

```ts
{
  id: string; name: string; label: string; description: string; category: string;
  command: string; args: string[];
  // 原始能力说明书：{ 工具ID: { description: string, parameters?: object } }
  // （CliService.expand_tool_schema 展开为 cli_tool 行：description + input_schema）
  tool_schema: Record<string, { description?: string; parameters?: object }>;
  task_keywords: string[]; timeout_seconds: number;
  enabled: boolean; is_public: boolean; tool_count: number;
}
```

**安全事实**：`to_dict` **不含 `env`**（加密存储，`ensure_encrypted_env` 经
`tool_credential_encryptor` 权威入口，运行时由 `McpStdioClient._build_subprocess_env`
解密注入）——因此前端**无法回显 env 值**，也不应假装能回显。

## 3. 页面设计

### 3.1 路由与菜单

- 路由：`/admin/cli` → `AdminCliView.vue`（`router/index.ts` 注册）。
- 菜单：**资源编排组**，紧邻「MCP 管理」之后（CLI 与 MCP 同为工具来源，语义并列），
  权限 `permission: 'cli:read'`（`AdminLayout.vue` menuGroups）。
- 权限链（已存在，前端只消费）：`support.py` 将 `("admin", "cli")` 映射
  GET→`cli:read`、写操作→`cli:create/update/delete`；四权限在 `rbac.py`
  `PERMISSION_CATALOG` 登记且 operator 默认授权。

### 3.2 列表页 `AdminCliView.vue`

参照 `AdminMcpView.vue` 形态：
- 列表列：名称（name/label）、命令（command + args 摘要）、分类、工具数
  （`tool_count`）、启用开关（PUT `enabled` 即时切换）、任务关键词标签、操作
  （编辑 / 删除带确认）。
- 操作：「注册 CLI」按钮开创建弹窗；分类筛选 + 名称搜索（前端过滤即可，量级小）。
- 空状态：引导文案指向「注册 CLI」。

### 3.3 创建/编辑弹窗 `CreateOrUpdateCliModal.vue`

**原则：不让管理员面对裸 JSON**（历史教训：extra_config 裸 JSON 被用户反馈看不懂）。
表单分区：

1. **基础**：name*、label、description、category（文本输入，自由字符串——已核实 `mcp.model` 的 category 为 `String(255)` 无枚举，CLI 对齐同为自由文本，默认 `other`）、
   enabled 开关、timeout_seconds（数字，默认 30）。
2. **命令**：command*（如 `python`、`ffmpeg`）、args（**动态行编辑**：每行一个参数，
   支持 `${var}` 模板占位说明）。
3. **能力说明书（tool_schema）—— 表格化行编辑器**：
   - 每行 = 一个工具：`工具 ID` + `描述*` + `参数 JSON（折叠，默认空 {}）`；
   - 「添加工具」按钮增行；行内删除；
   - 提交前组装为 `{ [tool_id]: { description, parameters } }` 并做与服务端一致的
     校验（非空、每项有描述、参数 JSON 合法）；
   - 折叠区提供「JSON 模式」切换（高级用户直接编辑整段，实时校验）。
   - 空 `tool_schema` 前端即拦截，提示「请至少声明一个工具及其描述」（与服务端同文案）。
4. **任务关键词**：动态行（task_keywords），用于工具池语义/关键词命中精调。
5. **环境变量 env（安全约束）**：
   - **不回显**（GET 不返回）；表单为纯写入：键值行编辑 + 「提交时清空 env」开关；
   - 仅当管理员主动编辑（或勾选清空）时才把 `env` 放入 PUT/POST 请求体——
     不编辑则**不带 `env` 键**，服务端保持原值（PUT 只处理传入字段）；
   - UI 明示：「值加密存储、不回显；重新输入即整体覆盖」。

### 3.4 service `ui/src/services/admin-cli.ts`

`listCliProviders / createCliProvider / getCliProvider / updateCliProvider /
deleteCliProvider`，复用 `@/utils/request` 的 `get/post/put/del` 与 `BaseResponse`
包裹（参照 `admin-global-control-config.ts` 写法）；类型 `CliProvider` 按 §2。

### 3.5 i18n（强制）

- 新建 `{zh-CN,en-US}/admin/adminCli.ts` 模块字典，两镜像同步，admin 目录
  `index.ts` 注册；
- `adminLayout.ts` 两侧各增 `menu.cli` 键；
- 所有文案走 `t('admin.adminCli.*')`，无硬编码；
- 提交前 `npx vitest run src/i18n/__tests__/parity.spec.ts` 必须通过。

### 3.6 前端测试

参照 `mcp-list-admin.spec.ts`：列表渲染、创建校验拦截（空 name/command/tool_schema）、
编辑回填、删除确认、启用开关调用——mock service 层，断言请求参数形状。

## 4. 并行性

与 CUA observe-act 规格（A）**文件零重叠**（本规格只动 `ui/src` + i18n），
两条实现轨可并行。

## 5. 接线自检

- 页面入口：系统菜单「资源编排 → CLI 管理」→ `/admin/cli`（`cli:read` 可见）；
- 数据入口：`admin-cli.ts` → 真实 `/admin/cli` 五端点；
- 生效链路（既有，本次不改）：注册 → `cli_tool` 展开 → 候选池
  （`_collect_cli_tools`）→ `ToolSelectorService` → `CliService.build_selected_tools`
  → `McpToolFactory`（`protocol=raw`）执行。
