# CLI 作为工具池独立来源（source_type=cli）设计

> **已归档（2026-10-03）**：该设计已落地（独立 `cli_provider`/`cli_tool` 两表、能力说明书展开、候选收集、选择、`protocol=raw` 执行、cli-hub 清理），33 例后端测试通过。§4.4 的执行面已按实测纠正为 assistant 链路（其余面各有政策原因）。当前说明见 [01-agent-tool-pool.md](../../prd/modules/01-agent-tool-pool.md) 与 [extensibility-design.md](../../prd/extensibility-design.md)；本文档仅保留设计过程与决策依据，**不代表当前实现**。

> 状态：已落地（2026-10-03 归档；初稿「待用户复核」为当时状态）。日期：2026-09-24。
> 关联：`docs/prd/extensibility-design.md`（第三方能力接入）、`docs/prd/modules/01-agent-tool-pool.md`（工具池）。

## 1. 背景与问题

CLI 能力的接入目前存在三个独立问题，此前被混为一谈：

### 1.1 断链：CLI 子命令进不了工具池（根因）
工具候选收集器 `ToolInventoryService._collect_mcp_tools`
（`api/internal/service/tool_inventory_service.py:206-240`）取工具的方式是：

```python
for tool_name in provider.tool_names or []:      # 读 tool_names
    "description": provider.description,          # 用 provider 级描述
```

而 CLI（`transport=cli`）的**按工具定义**（工具 ID + 描述 + 参数）存放在
`mcp_provider.tool_schema`
（`api/internal/model/mcp.py:54-56`：`{tool_name: {description, parameters}}`）。
全仓核实：**没有任何代码把 `tool_schema` 的 key 派生进 `tool_names`**。

后果：CLI provider 即使配置正确，其子命令**永远不进候选池**，`ToolSelectorService`
（关键词快通道 + LLM 兜底）无法选中它 → Agent 无法使用。这是"CLI 是否可用存疑"的真实根因。

### 1.2 概念混淆：CLI 寄生在 MCP 板块
CLI 当前以 `transport=cli` 藏在 MCP 板块内，语义不匹配（MCP = 远程协议工具；
CLI = 本地进程工具）。实测管理员在后台找不到 CLI 入口。

### 1.3 cli-hub 空转：提示词占位，无执行器
`api/internal/core/skills/catalog/cli-hub/` 是 `executor_type: prompt`（`tools: []`）的
纯提示词技能，`skill_tool_factory.build_tools` 对非 `scf` 直接 `return []`（`skill_tool_factory.py:52-53`）。
它指导的 `cli-hub install` 在本环境既未安装、又禁网（`system_access` 的
`capabilities.network: false`，且沙箱后端默认不可用会抛 `FailException`）。
其"发现/安装"生态与系统安全模型冲突：**只有管理员手动注册进池的工具才允许 Agent 使用**。

## 2. 目标与非目标

### 2.1 目标
- 新增 `source_type = "cli"`，CLI 成为与 `builtin` / `api_tool` / `mcp` / `skill` 并列的**独立工具来源**。
- CLI 的**全部子命令全量进候选池**，复用 `ToolSelectorService` 选择（关键词快通道 + LLM 语义兜底）。
- Agent 可在"CLI 一条龙"与"精细原子工具"之间自主权衡（由工具描述表达粒度差异）。
- 彻底清理 cli-hub（代码 / 测试 / 文档 / 数据库），不留概念混淆。
- 同步 `SOURCE_TYPES` 等一致性面，清理相关死代码。

### 2.2 非目标
- 不做 cli-hub 目录同步（registry 拉取）、工具发现、安装生命周期（install / update / doctor）。
- 不新建调度层（复用既有 `Conductor` / `ExecutionCoordinatorService`）。
- 不重复实现本地进程执行器（复用既有 `McpStdioClient` 作为执行原语）。

## 3. 关键设计决策

| 编号 | 决策 | 说明 |
|---|---|---|
| **D1** | `source_type = "cli"`（新增第 8 类），**不复用 `"mcp"`** | 语义独立，治理页可区分 |
| **D2** | CLI **全量进池** | 全部子命令成为候选；靠 `task_keywords` 精调 + `max_tools` 收敛 |
| **D3** | 存储**独立为 `cli_provider` / `cli_tool` 表**，不寄生 `mcp_provider` | 兑现"不混用 mcp"；根治 `tool_names` vs `tool_schema` 语义混淆 |
| **D4** | **删除 cli-hub** 技能 + 测试 + 归档调研文档 + 清理 DB 残留 | 见 §5 |
| **D5** | 执行原语**复用 `McpStdioClient`**（本地进程 raw 执行），**不重复实现** | 遵循 AGENTS.md「禁止平行实现」；`cli` 只是调用方 |

> **D3 的例外说明**：`cli_provider` 行在运行时会构造成统一 binding dict
> （`command` / `args` / `env` / `tool_schema` / `timeout_seconds`），交给
> `McpStdioClient.call_tool_sync(protocol="raw")` 执行。这是**复用执行原语**，
> 不是"把 CLI 混进 MCP 板块"——数据、服务、路由、UI 均为 CLI 独立。

## 4. 架构设计

### 4.1 数据模型（新增两表）
- **`cli_provider`**：`id` / `account_id` / `name` / `label` / `description` / `category` /
  `command` / `args`(JSONB) / `env`(JSONB，加密存储) /
  `tool_schema`(JSONB：`{tool_id: {description, parameters}}`) /
  `task_keywords`(JSONB，GIN 索引) / `timeout_seconds` / `enabled` / `is_public` /
  `sync_status` / `source_type`(默认 `cli`) / 时间戳。
- **`cli_tool`**：`provider_id` / `name` / `description` / `input_schema`(JSONB) /
  `task_keywords`(JSONB) / `enabled`（对齐 `mcp_tool`，供关键词/向量检索）。

### 4.2 候选收集（补断链，核心改动）
- 新增 `ToolInventoryService._collect_cli_tools(account_id)`：以 **`cli_tool` 表为候选唯一事实源**
  （`cli_tool` 在注册/编辑时由 `cli_provider.tool_schema` 展开写入，二者不重复作为读取源），
  输出 `source_type="cli"` 候选，携带**工具级 description** + `task_keywords`。
- 在 `ToolInventoryService.collect()` 中注册该收集器。
- 修复语义：候选的 `description` 取**工具级**（而非 provider 级）。

### 4.3 选择逻辑（零新增）
候选进池后，`ToolSelectorService.select_tools` 的关键词快通道 + LLM 兜底原样生效
（其 docstring 已声明覆盖全 source_type），与 `builtin` / `mcp` / `skill` 同池竞争。

### 4.4 执行链路（复用）
- 新增 CLI 工具装配：把选中的 cli 工具转成 LangChain 工具；执行时构造 binding dict →
  `McpStdioClient.call_tool_sync(binding, tool_name, arguments)`（`protocol="raw"`）。
- **实测挂载面（2026-10-03 复核，以代码为准）**：CLI 工具进工具池候选（`ToolInventoryService._collect_cli_tools`）
  → `ToolSelectorService` 选择 → **助手链路**挂载执行（`assistant_agent_service._load_non_mcp_tool`
  → `CliService.build_selected_tools`，经 `RuntimeToolMountService` 治理）。
  本 spec 初稿列出的另外三个面经核实**均未接入，且各有其政策原因**，非漏接线：
  - `app_runtime_service` / `web_app_service`：`tool_subset` 自动注入**按策略仅取 builtin**
    （`_extract_builtin_tools_from_tool_subset`，理由：无需额外凭证与本地依赖），cli 需本地二进制 + 凭证，不在此列；
  - `admin_agent_chat_service`：管理端 Agent 只能调用 `BOARD_ACTIONS` **显式登记**的板块动作（现为 `builtin_tool` / `schedule_task`），cli 未登记即拒绝（fail closed）；
  - 工作流 `tool_node.py`：`ToolNodeData.tool_type` 枚举未含 cli。
  如需在这些面启用 CLI，属**独立的产品/治理决策**（凭证与本地依赖边界），需单独提方案。

### 4.5 治理与一致性
- `SOURCE_TYPES` 增加 `"cli"`：
  - `api/internal/schema/admin_tool_governance_schema.py:10`（及 L16 的 `AnyOf` 校验）
  - `api/internal/service/admin_tool_governance_service.py:15`
- `runtime_tool_governance_gate._COMPOSITE_SOURCE_TYPES = {"workflow", "agent_binding"}`：
  `cli` 属原子工具，**无需改**（实现阶段确认）。
- 权限 / 审计 / `ToolPolicy` / `env` 加密链路（`encrypt_env`）全部复用。

### 4.6 "一条龙 vs 精细"如何体现（无需新抽象）
同一候选池内并存两种粒度：
- **打包 CLI 命令**：描述写"一站式完成 X"（例：videocaptioner 的整链命令）。
- **builtin 原子工具**：`asr` / `translate` / `ffmpeg_edit`。
LLM 按 query + 描述权衡"1 个打包 vs N 个原子"。省钱机理：打包 = 1 次调用；精细 = N 次往返。
粒度差异由**候选描述**天然表达，不引入能力路由层。

### 4.7 管理入口与迁移（`admin 可编辑 + 运行时读取` 成对交付）
- **admin API**：CLI Provider 的 CRUD（对齐 `/admin/mcp` 形态），含 `command` / `args` /
  `tool_schema`（能力说明书）/ `task_keywords` / `env`（加密）/ `timeout_seconds` / `enabled`；
  保存时将 `tool_schema` 展开写入 `cli_tool`。
- **admin UI**：CLI 管理页（transport=cli 的 MCP 弹窗经验可复用，但为独立入口，不与 MCP 混列）。
- **Alembic 迁移**：新建 `cli_provider` / `cli_tool` 两表；`down_revision` 指向**已被 git 跟踪的
  单 head**；另需一条迁移清理 cli-hub 的 `skill_package` / `skill_package_version` 残留（见 §5）。

## 5. cli-hub 清理清单

| 项 | 路径 | 动作 |
|---|---|---|
| cli-hub manifest | `api/internal/core/skills/catalog/cli-hub/manifest.yaml` | 删除 |
| cli-hub skill.md | `api/internal/core/skills/catalog/cli-hub/skill.md` | 删除（磁盘存在；被 `.gitignore` 的 `**/*.md` 忽略故未入库） |
| 单元测试 | `api/test/internal/core/skills/test_cli_hub_skill.py` | 删除 |
| 调研文档 | `docs/research/cli-anything.md` | 归档至 `docs/archive/research-completed/`，标注"cli-hub 方案作废" |
| 数据库残留 | `skill_package`(source_key=`cli-hub`) + `skill_package_version` | **迁移清理**（catalog 同步只增不删，需显式删除） |
| 目录本身 | `api/internal/core/skills/catalog/cli-hub/` | 随文件删除后移除空目录 |

> 备注：cli-hub 之外，`transport=cli` 的 MCP 语义描述若在文档中仍以"MCP 工厂的 transport 别名"表述，
> 需按 §6 更新为独立 `cli source_type`。

## 6. 一致性与死代码维护清单

| 类型 | 位置 | 动作 |
|---|---|---|
| 一致性 | `admin_tool_governance_schema.py:10` / `admin_tool_governance_service.py:15` | `SOURCE_TYPES` 7 类 → 8 类（加 `cli`） |
| 一致性 | `docs/prd/modules/01-agent-tool-pool.md` §10.1.1 等多处（7 类表述） | 更新为 8 类，补 `cli` 行 |
| 一致性 | `docs/prd/extensibility-design.md` §3.2 / §3.2.1 | 从"MCP 工厂的 `transport=cli`"改写为"独立 `cli` 工具来源" |
| 死代码 | cli-hub 技能 / 测试 / 调研文档 | 见 §5 |
| 死代码（评估） | `.gitignore` 的 `**/*.md` 使 `catalog/*/skill.md` 全部未入库 | 既有缺陷，**单独评估**是否顺带修复（不阻塞本设计） |
| 死代码（评估） | `mcp_provider.tool_names` 对 CLI 的语义 | CLI 迁独立表后，`tool_names` 回归 MCP-only 语义 |

## 7. 风险与权衡

- **D3 新表 vs 复用 `mcp_provider`**：新表语义清晰、根治混淆，但需迁移 + 模型 + 服务 + 路由 + UI；
  复用省事但延续 1.2 的混淆。**本设计选新表**。
- **全量进池可能稀释选择**：靠 `task_keywords` 精调 + `max_tools` 收敛，行为与既有工具池一致。
- **执行环境依赖**：CLI 需在运行环境可执行。容器默认无 GUI 软件，**纯 CLI / 纯 API 型**方可跑通；
  环境预装属运维范畴，非本设计范围。

## 8. 验收标准

1. Agent 能选中并端到端执行一个 CLI 子命令（有真实 stdout 返回）。
2. `cli-hub` 零残留：全仓 grep 无命中，`skill_package` 无 `cli-hub` 行。
3. `SOURCE_TYPES` 与 `docs/prd/modules/01-agent-tool-pool.md` 表述一致（8 类）。
4. 既有测试不回归（工具池 / 工具治理 / MCP / 技能）。

## 9. 测试策略

- **单测**：`_collect_cli_tools` 候选收集（工具级 description + task_keywords）；
  CLI 工具装配与 `protocol=raw` 调用；`SOURCE_TYPES` 含 `cli` 的一致性断言。
- **迁移测试**：`cli_provider` / `cli_tool` 建表与回滚；cli-hub DB 残留清理。
- **集成**：构造一个纯 API 型 CLI，验证 Agent 经选择器选中并执行。
