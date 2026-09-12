## Agent 技能

### Issue tracker

本仓库的 issue 使用 GitHub Issues 跟踪，并通过 `gh` CLI 管理。参见 `docs/agents/issue-tracker.md`。

### Triage 标签

使用默认标签：`needs-triage`、`needs-info`、`ready-for-agent`、`ready-for-human`、`wontfix`。参见 `docs/agents/triage-labels.md`。

### Domain docs

本仓库为 single-context 布局：根目录 `README.md` + 全部领域/架构文档集中在 `docs/`（导航入口 `docs/README.md`）。`docs/agents/domain.md` 为通用模板；本仓库**不使用** `CONTEXT.md` / `CONTEXT-MAP.md` / `docs/adr/`，凡引用这三个位置的描述均为过时残留。

## 架构文档同步（强制规则）

架构文档是 Agent 判断当前系统真实结构的唯一权威来源；**文档过期会直接误导后续开发与代码审查**。因此：

- 任何开发任务，只要其改动涉及架构（新增/删除/重命名模块、service、路由、数据表、迁移、核心流程、跨模块调用关系、API 语义），**必须在完成代码后同步更新对应架构文档**，再宣告任务完成。
- 文档映射（写到哪）：
  - 核心架构/演进方向：`docs/prd/architecture-design.md`
  - 顶层模块（Agent/知识库/编排/存储/安全/等）：`docs/prd/modules/01-*.md` ~ `08-*.md`
  - 记忆系统：`docs/prd/memory-system/*.md`
  - 执行状态类：`docs/prd/execution-roadmap.md` 中的任务状态栏
  - API 契约（对外接口）：`docs/api/*.md`
  - 权限/RBAC 变更：`docs/rbac.md`
- 同步更新的动作要求：
  - 若文档描述与实际代码不符（引用已删除文件/模块、声称未实现的功能已实现、模块已被取代但文档仍为主线叙事），**立即修正**，不得保留过期内容。
  - 删除模块时同步删除文档中对它的描述；新增模块时在对应文档补一节。
  - 文档中禁止留下"状态待确认/执行中/待开始"之类与实际不符的标记——完成了就标完成，未实现就标注"愿景设计、未实现"。
- 若某任务涉及删除或大改一篇文档的定位（如 roadmap 已完成需归档），在 commit message 中说明"docs: archive ..."，将过期规划移到 `docs/archive/` 而不是让它们继续出现在导航里误导 Agent。
- 完成涉及架构的改动后，运行 `python -m graphify update .` 保持知识图谱最新（见下节）。

## 前端 i18n 规范（强制规则）

前端所有面向用户的文案（按钮、导航、提示语、表单字段、空状态、错误提示、管理后台文案等）**必须**走 i18n，**禁止硬编码**中文字符串或英文字符串到组件/页面中。规范要点：

- **只能用 i18n 键引用**：组件内通过 `t('admin.customerUsers.editUser')` 一类语义化键取值（或 `useI18n()`），不得出现 `"编辑"`、`'Edit'` 这类直接写在模板/脚本里的展示文案。例外仅限：非展示性字符串（key、id、URL、单位缩写等）与纯视觉占位（如 `<a-tag>` 的 color 枚举）。
- **字典按板块模块化组织**：i18n 字典位于 `ui/src/i18n/messages/<locale>/`（`<locale>` 为 `zh-CN`/`en-US`），按顶层板块一文件（`common.ts`、`layout.ts`、`admin/` 等），`admin/` 目录内再按子模块拆文件（`admin/customerUsers.ts`、`admin/adminUsers.ts`）。**禁止**回退为单文件巨型字典（`messages/zh-CN.ts` / `en-US.ts` 已废弃）；新增板块时新建对应模块文件，并在目录 `index.ts` 中注册聚合。
- **结构必须镜像且同步增改**：`zh-CN/` 与 `en-US/` 目录结构必须一致（同路径必有同文件）。新增/修改文案时，**同时**在 zh-CN 与 en-US 的对应板块文件各改一处，不允许只改一侧；删除/重命名键同理两侧同步。
- **保持 zh/en 键集合一致**：新增文案后运行 `npx vitest run src/i18n/__tests__/parity.spec.ts` 校验。该测试递归断言 zh-CN 与 en-US 叶子键集合完全一致，缺键会直接失败并报出缺失路径；**提交前必须通过**。
- **不硬编码语境文案的归属**：一个语义单位（如删除确认标题、表单 label + placeholder）归入其所属页面的板块命名空间下（如用户管理页文案统一放 `admin.customerUsers.*`），复用高频通用词放 `common.*`，不要为凑数随意铺散或复制整段键。
- **消息插值用 i18n 语法**：含动态值的文案在字典里写成 `删除用户：{name}`，代码侧用 `t('...', { name })`，不要用字符串拼接代替。

## graphify

本项目在 `graphify-out/` 中维护一个知识图谱，包含 god nodes、社区结构和跨文件关系。

当用户输入 `/graphify` 时，先使用已安装的 graphify 技能或本段指引，再做其他操作。

规则：
- 回答代码库问题时，如果 `graphify-out/graph.json` 存在，先运行 `python -m graphify query "<question>"`。查询关系用 `python -m graphify path "<A>" "<B>"`，聚焦概念用 `python -m graphify explain "<concept>"`。这些命令返回范围更小的子图，通常远小于 `GRAPH_REPORT.md` 或直接 grep。
- `graphify-out/` 中的文件在 hook 或增量更新后出现未提交变动是正常现象；不要因为 graph 文件 dirty 就跳过 graphify。只有当任务本身涉及过期或错误的 graph 输出，或用户明确要求不用时，才跳过。
- 如果 `graphify-out/wiki/index.md` 存在，优先用它做全局导航，而不是直接浏览源码。
- 只有做整体架构评审，或 query/path/explain 无法提供足够上下文时，才读 `graphify-out/GRAPH_REPORT.md`。
- 修改代码后运行 `python -m graphify update .` 保持 graph 最新（仅 AST，无 API 成本）。

## Better Harness

本项目已安装 Better Harness 插件（`better-harness@better-harness`），用于评估和改善 coding-agent 交付流程。

规则：
- 当用户提及 Better Harness，或任务涉及交付流程评审、工作流改进、修复计划时，先使用 `@better-harness` 技能分析本仓库并生成报告，再继续其他操作。
- 报告输出在 `.codex/better-harness/` 下；分析后按报告中的验收清单落地改进。
- 修改代码后仍按上方 graphify 规则运行 `python -m graphify update .` 保持知识图谱最新。
