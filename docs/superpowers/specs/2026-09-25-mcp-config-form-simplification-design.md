# MCP 配置表单化改造（批次 1）设计

> 状态：在途（实现中）
> 背景：仓库内存在 11 处「要求管理员手工输入原始 JSON / 逗号分隔列表」的配置点，其中 MCP 相关最集中、最易出错，且同一组字段在 2 个组件里各抄一份解析逻辑。本设计为「配置项填写方式语义化 / 自动化」改造的**批次 1**，只覆盖 MCP；其余批次另行立项。

## 1. 问题与判定

### 1.1 现状盘点（已实测）

| # | 位置 | 手填内容 | 性质 |
|---|---|---|---|
| 1 | `CreateOrUpdateMcpModal.vue`（`/admin/mcp` 与业务侧共用） | `headers`/`env`/`tool_schema` 三段 JSON；`tool_names`/`args`/`task_keywords` 三个英文逗号列表 | 真硬核 |
| 2 | `McpBindingsAbilityItem.vue`（应用编排 → MCP 绑定） | 同上 5 个字段（重复实现） | 真硬核 |
| 3 | `ImportMcpModal.vue` | 整段 `mcp.json` / 单 server JSON | 导入场景 |
| 4 | `AdminStorageView.vue` | 整段后端配置 JSON | 配置 |
| 5 | `CreateOrUpdateSkillModal.vue` | `tools` JSON 数组 + `tags` 逗号列表 | 半硬核 |
| 6 | `ImportExternalSkillModal.vue` | manifest JSON 全文 | 导入场景 |
| 7 | `ImportWorkflowModal.vue` | 工作流 JSON 全文 | 导入场景 |
| 8 | `admin/agents/ListView.vue` | 定时任务参数 JSON | 半硬核 |
| 9 | `ToolsView.vue` | OpenAPI Schema JSON | 技术规范 |
| 10 | `WorkflowDebugPanel.vue` | 工作流输入 JSON | 半硬核 |
| 11 | `ConversationVariableDrawer.vue` | 会话变量 JSON 值 | 半硬核 |

### 1.2 轮胎 vs 补丁判定

**判定为「补丁堆」征兆，本批次按「建单一权威入口」处置，不得逐处贴补丁。**

- **无核心能力层**：全仓不存在共享的结构化编辑器组件；`parseJsonObject` / `parseJsonArray` 在 `CreateOrUpdateMcpModal.vue`（L89-107）与 `McpBindingsAbilityItem.vue`（L210-228）**各抄一份**，逻辑完全一致。
- **平行机制**：`ImportMcpModal.vue`（L241-280）另有一份私有的 headers 行编辑器。
- **写入散落**：同一组字段在 2 个组件各写一套 `JSON.stringify` / `split(',')`。
- **可循的既有「轮胎」先例**：`ModelsView.vue` 峰谷时段已改为可视化行编辑器、`capabilities` 用 `a-input-tag`、子池定义用 `a-input-tag`。

**处置**：新建共享层 `ui/src/components/config-editors/` 作为单一权威入口，批次 1 接入 MCP 两处并收编导入弹窗的私有 KV 实现；后续批次复用该层，不新建平行机制。

### 1.3 顺带修复的真实缺陷（数据破坏）

后端详情接口对 `headers` / `env` **无条件脱敏**（`mcp_service.py` L337-339），前端 `applyMcpPayload`（`CreateOrUpdateMcpModal.vue` L119-146）把**掩码值**原样回填到表单并原样提交，后端再执行 `encrypt_env` / `encrypt_headers` → **真实密钥被掩码覆盖，且不可逆**。

本批次必须修复：密钥字段在编辑态不回填掩码，未修改则不提交该键。

## 2. 目标与非目标

**目标**

1. MCP 配置**全表单化**：管理员无需手写任何 JSON 或逗号列表。
2. 提供**内置 CLI 模板**（百炼、方舟），选中即预填 `transport` / `command` / `args` / `tool_schema` / `env` 键名。
3. 按 `transport` **动态显示**相关字段，消除「所有字段一股脑铺开」。
4. 收敛重复实现为单一权威解析入口。
5. 修复 1.3 的密钥回填缺陷。

**非目标（本次不做）**

- 批次 2 / 批次 3 的其余 9 处配置点。
- JSON **导入**场景（#3 / #6 / #7）不表单化——导入语义就是粘贴整段 JSON，表单化反而更糟；仅后续加实时校验与格式化。
- 后端接口结构变更（除 1.3 缺陷所需的前端侧处理）。

## 3. 组件架构

新建目录 `ui/src/components/config-editors/`：

| 文件 | 替代字段 | 职责 |
|---|---|---|
| `KeyValueEditor.vue` | `env`、`headers` | 行式 KV 编辑器；支持增删行；`secret` 模式支持密钥语义 |
| `OrderedArgListEditor.vue` | `args` | **有序**参数行编辑器（参数值可能含逗号与空格，逗号分隔是错的） |
| `TagListEditor.vue` | `tool_names`、`task_keywords` | 标签输入（等价 `a-input-tag`） |
| `ToolSchemaBuilder.vue` | `tool_schema` | 可视化工具声明：工具 → 参数表（名称/类型/必填/说明）→ 产出 JSON Schema；保留「高级：直接编辑 JSON」折叠兜底 |
| `McpTemplatePicker.vue` | — | 模板选择器；选中触发 `apply` 事件回填表单 |
| `mcp-cli-templates.ts` | — | 模板数据（百炼 + 方舟） |
| `config-parse.ts` | 两处重复解析 | 单一权威解析入口 |
| `types.ts` | — | 共享类型 |

### 3.1 单一权威解析入口（`config-parse.ts`）

导出（替代两处私有实现）：

- `parseJsonObject(text: string): Record<string, unknown>`
- `parseJsonArray<T = unknown>(text: string): T[]`
- `formatJson(value: unknown): string`

约束：两处组件删除各自的私有实现，改为从本模块导入，保证行为一致。错误信息统一，交由调用方按 i18n 渲染。

### 3.2 密钥语义（`KeyValueEditor` 的 `secret` 模式）

用于 `env` / `headers`。规则：

1. 编辑态**不回填后端返回的掩码值**；密钥项显示为「已设置（留空则保持不变）」占位。
2. 未修改的密钥键**不进入提交载荷**（避免掩码覆盖真值）。
3. 新增 / 修改的密钥键正常提交，由后端 `encrypt_env` / `encrypt_headers` 加密落库。
4. 需要「清空某密钥」时，提供显式删除操作（删除即提交该键被移除的语义）。

> 说明：删除语义取决于后端接口是否支持「键删除」。实现阶段若后端为「全量覆盖」，删除行即为删除该键；若为「增量合并」，需在实现中显式处理并在此文档回填结论。

### 3.3 transport 动态显字段

| transport | 显示字段 |
|---|---|
| `http` / `sse` / `streamable_http` | `url`、`headers` |
| `stdio` | `command`、`args`、`env` |
| `cli` | `command`、`args`、`tool_schema`、`env`、模板选择器 |

`tool_schema` 在 `cli` 下必填（后端 schema 已强制）。

## 4. 内置模板库

模板**必须基于实测命令签名**（已在本机容器内验证），不得凭想象编写。

| 模板 Key | 展示名 | args 模板（已实测） | 需要 Key |
|---|---|---|---|
| `bailian_model_search` | 百炼 · 模型目录检索 | `-y, bailian-cli@2.0.1, model, search, --keyword, {keyword}, --limit, {limit}, --output, json` | 否（免鉴权） |
| `bailian_text_chat` | 百炼 · 文本对话 | `-y, bailian-cli@2.0.1, text, chat, --model, {model}, --message, {message}, --output, json` | 是（`DASHSCOPE_API_KEY`） |
| `ark_text_chat` | 方舟 · 文本对话 | `-y, @volcengine/ark-cli@1.0.36, +chat, {prompt}, --model, {model}, --text-format, json` | 是（`ARK_API_KEY`） |
| `ark_model_search` | 方舟 · 模型检索 | `-y, @volcengine/ark-cli@1.0.36, models, search, --keyword, {keyword}` | 是（`ARK_API_KEY`） |

**实测依据**（容器 `llmops-api` 内，方式与 raw 模式一致：`subprocess.run` + 继承 env）：

- `npx -y bailian-cli@latest --version` → `bl 2.0.1`
- `npx -y @volcengine/ark-cli@latest --version` → `arkcli version 1.0.36`
- `bl model search --keyword qwen --output json` → 免鉴权返回真实目录
- 命令签名差异：百炼为命名参数（`bl text chat --message <text>`），方舟为**位置参数**（`arkcli +chat <prompt>`）

**版本策略**：模板默认写**固定已验证版本**；界面提供「更新到最新」按钮，将版本号替换为 `@latest`（或重新探测最新版本号）。避免 `@latest` 长期驻留导致上游发布未测行为。

每个模板同时内置对应的 `tool_schema`（工具名、描述、参数名/类型/必填），使管理员无需手写 JSON。

## 5. 接线与影响面

| 文件 | 变更 |
|---|---|
| `ui/src/components/config-editors/*` | 新增共享层 |
| `CreateOrUpdateMcpModal.vue` | `headers_text`/`env_text`/`tool_schema_text`/`args_text`/`tool_names_text`/`task_keywords_text` 换用共享组件；接入模板选择器；删除私有 `parseJsonObject`/`parseJsonArray`；修复密钥回填 |
| `McpBindingsAbilityItem.vue` | 同上（字段集合同源）；删除私有解析；修复密钥回填 |
| `ImportMcpModal.vue` | 收编私有 headers 行编辑器为共享 `KeyValueEditor` |
| `ui/src/i18n/messages/{zh-CN,en-US}/space.ts`、`appStudio.ts`、`admin/mcpAdmin.ts` | 新增组件与模板文案键（两侧同步） |
| `AdminStorageView.vue` | 顺带修复硬编码中文 `'JSON 格式不正确'` → i18n |

**字段透传核对**：`tool_schema` / `protocol` 需从表单 → 提交载荷 → 应用 `mcp_bindings` → `McpToolFactory` 全程保留，实现后按仓库「中间层核对字段透传」规则逐层验证。

## 6. 测试与验收

- **单测**：`config-parse` 正常/异常输入；`KeyValueEditor` 增删改；`OrderedArgListEditor` 有序性与含逗号值；`ToolSchemaBuilder` 产出合法 JSON Schema；模板预填结果。
- **回归（重点）**：编辑一个含密钥的 MCP 保存后，密钥不被掩码破坏（对应 1.3）。
- **i18n**：`npx vitest run src/i18n/__tests__/parity.spec.ts` 通过（键集合一致 + 可编译性）。
- **端到端**：选「百炼 · 模型目录检索」模板（免鉴权）→ 应用内调用，工具名按 `mcp__<provider名>__<tool_schema key>` 规则生成并返回真实数据。

## 7. 后续批次（仅登记，不在本设计范围）

- **批次 2**：`/admin/storage`（#4）、skills `tools`/`tags`（#5）、agents payload（#8）、`openapi_schema`（#9）、会话变量（#11）、工作流调试输入（#10）。
- **批次 3**：JSON 导入页（#3 / #6 / #7）保留粘贴，仅加实时校验 + 格式化。
