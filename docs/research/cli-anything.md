# CLI-Anything 调研：把“软件 Agent 化”变成可分发 CLI

> 调研时间：2026-08-12。结论基于 GitHub 仓库、HARNESS.md、codex-skill、cli-hub 源码、registry.json、论文摘要等一手来源。

## 结论

CLI-Anything 与钰心AI/OpenAgent 的“能力接入”模型高度同构：它把 GUI 应用、代码库、Web API 转换成统一的 Click CLI（REPL + `--json` + 会话状态 + 测试 + `SKILL.md`），再通过 CLI-Hub 分发。这正好可以映射到我们已有的 Skill catalog、MCP provider、工作流工具节点、应用市场和 OpenAPI 交付能力上。

最现实的三条接入路径：

1. **当工具目录用**：把 `cli-hub-meta-skill` 和官方/公共 registry 转成我们 catalog 里的技能包或工具目录，让 Agent 能发现和选择。
2. **当执行底座用**：新增一个 CLI 执行器（沙箱 skill 或 builtin tool provider），负责 `cli-hub install` / `cli-anything-<name>` 子进程调用；只导入 SKILL.md 无法真正执行。
3. **当设备 Agent 能力用**：在用户设备上安装真实软件 + 对应 harness，通过设备侧 worker 或 MCP stdio 桥接入平台，这与钰心AI 的“设备 Agent”定位最匹配。

风险点：绝大多数 harness 强依赖真实桌面软件，Docker/SCF 沙箱里只能跑纯 API/纯 CLI 型 harness；Codex 官方接入仍标记 experimental；CLI-Hub 有匿名遥测（可关闭）；项目迭代很快，需要镜像审查。

## 它是什么

- 官方仓库：<https://github.com/HKUDS/CLI-Anything>，港大数据智能实验室（HKUDS）
- 口号：Making ALL Software Agent-Native。目标是把任何 GUI 应用、代码库、Web API 变成 AI Agent 可调用的结构化 CLI
- 技术报告：[arXiv:2606.03854](https://arxiv.org/abs/2606.03854)，标题 *CLI-Anything: Towards Agent-Native Computer Use*，作者 Yuhao Yang、Tianyu Fan、Chao Huang，2026-06-02 提交，分类 cs.HC
- 许可：Apache License 2.0（不是 MIT，v0.4.0 中专门修正了 badge）
- 最新 release：v0.4.0（2026-06-25）；此前 v0.3.0（2026-04-24）、v0.2.0（2026-03-30）
- 测试规模：README 当前宣称 2,461 个测试通过（测试汇总表为 2,464），分单元测试、原生 E2E、真实后端 E2E、CLI 子进程测试四层
- 分发中心：CLI-Hub，Web 端 <https://clianything.cc/> 和 <https://hkuds.github.io/CLI-Anything/>，包管理器 `cli-anything-hub`

论文的核心论点：主流的 GUI Agent 通过截图、像素坐标、点击来操作软件，本质上是在模拟人类感知，而不是发挥模型的优势。CLI-Anything 主张“Agent-native computer use”，用结构化命令、显式状态、确定性 JSON 输出来替代视觉 GUI 控制。

## 核心架构

### 1. 七阶段生成流水线

官方 `cli-anything-plugin/HARNESS.md` 是方法论的唯一权威来源，完整 SOP 是：

1. **代码分析**：识别后端引擎（如 MLT、sox、Script-Fu）、GUI 动作到 API 的映射、数据模型、已有 CLI、命令/undo 系统
2. **CLI 架构设计**：命令组、状态模型、输出格式（人类表格 + `--json`）、REPL + 一次性子命令双模式
3. **实现**：先做数据层，再加探针/信息命令、变更命令、真实软件 backend wrapper、渲染导出、会话管理和统一 REPL skin
4. **测试规划**：先写 `TEST.md` 计划，再写测试代码
5. **测试实现**：单元测试 + 原生文件 E2E + 真实后端 E2E + 安装后 CLI 子进程测试，禁止“退出码 0 就认为成功”，必须校验 magic bytes、文件结构、像素/音频内容
6. **测试文档 + SKILL.md 生成**：生成可被 Agent 发现的 `SKILL.md`（顶层 `skills/` 为 canonical 位置，同时打包进 pip 包）
7. **PyPI 发布 / `pip install -e .`**

### 2. 生成物形态

每个 harness 是独立 PyPI 包：

```text
<software>/agent-harness/
├── <SOFTWARE>.md                 # 该软件的架构 SOP
├── setup.py
├── cli_anything/                 # PEP 420 namespace 包，顶层无 __init__.py
│   └── <software>/
│       ├── <software>_cli.py     # Click CLI，默认进入 REPL
│       ├── core/                 # 每个领域一个模块
│       ├── utils/
│       │   ├── <software>_backend.py  # 调用真实软件
│       │   └── repl_skin.py           # 统一 REPL 皮肤
│       ├── skills/SKILL.md
│       └── tests/                # TEST.md + test_core.py + test_full_e2e.py
```

所有 harness 的通用契约：

- 命令名统一为 `cli-anything-<software>`
- 无子命令时进入 REPL；支持一次性 subcommand；所有命令支持 `--json`
- 会话状态持久化到 JSON，带原子文件锁，尽量支持 undo/redo、`--dry-run`
- 必须调用真实软件渲染/导出，禁止用 Python 库替代（例如禁止用 Pillow 替代 GIMP）
- 可预览的软件实现 `preview recipes/capture/latest`，产出的 bundle 遵循 `docs/PREVIEW_PROTOCOL.md` 的 `preview-bundle/v1` 协议，`cli-hub previews` 只做只读查看
- 包内自带 `SKILL.md`，同时顶层 `skills/` 统一管理，可用 `npx skills add HKUDS/CLI-Anything --skill <name> -g -y` 安装

### 3. CLI-Hub 分发机制

`cli-hub` 是轻量 pip 包装器，核心代码在 `cli-hub/`：

- `pip install cli-anything-hub`，命令 `cli-hub list/search/info/install/update/uninstall/launch`
- 注册表是仓库里的 JSON：`registry.json`（官方 harness）和 `public_registry.json`（第三方 CLI，支持 pip/npm/brew/bundled/uv/script 等安装方式）
- 每个条目包含 `name`、`category`、`requires`、`install_cmd`、`entry_point`、`skill_md`、`contributors`
- v0.4.0 新增 `cli-hub matrix`：把多 CLI 工作流按“能力 × provider”打包，支持 `can`、`preflight`、按 capability 局部安装、`--dry-run`、`--resume`
- 安装后 `cli-anything-<name>` 作为独立可执行文件存在，多个 harness 通过 namespace package 共存
- `cli-hub` 默认向 PostHog 发送匿名使用事件，可用 `CLI_HUB_NO_ANALYTICS=1` 关闭

### 4. Agent 侧接入形态

官方提供多种 SKILL 兼容接入：

- `cli-hub-meta-skill/SKILL.md`：让 Agent 自己 `cli-hub search/install` 并按任务选择工具
- `codex-skill/`：自包含 Codex 技能，安装到 `$CODEX_HOME/skills/cli-anything`，把 HARNESS.md、命令规格、guides、repl_skin 等 vendor 进 skill；README 标记为 **experimental**
- Claude Code 插件（`cli-anything-plugin/`，命令 `/cli-anything`、`/refine`、`/test`、`/validate`、`/list`）
- Pi、OpenClaw、OpenCode、Qoder、Hermes、Reasonix 等也有社区适配
- 对只暴露 MCP 的软件（如浏览器 DOMShell），HARNESS.md 提供 `guides/mcp-backend.md` 的 MCP backend wrapper 模式，把 MCP tools 包成 CLI 命令

### 5. 适用边界

官方 README 明确：

- 适合：有清晰数据模型/现有 CLI/API 的 GUI 应用、Web API 聚合、代码库
- 不适合/降级明显：只有闭源二进制的未文档化格式、实时交互、依赖 GPU/显示访问的应用
- 生成质量依赖前沿模型（官方举例 Claude Opus/Sonnet、GPT-5.x 级别），弱模型容易产出不完整 CLI
- 一次生成后通常还要跑 `/refine` 扩展覆盖

## 与钰心AI/OpenAgent 的适配分析

### 高度契合的点

- **Skill 目录可直接吸收**：我们已有 `api/internal/core/skills/catalog/*/manifest.yaml`，支持 `executor_type: prompt` 和 `executor_type: scf`。CLI-Anything 的 `SKILL.md` 本身就是给 Agent 看的技能文档，转成 prompt 技能只需补一个 manifest；仓库里已有 `cli-creator` 这种“给 Codex 造 CLI”的同类技能，说明方向一致。
- **MCP 底座可复用**：我们有完整的 `mcp_provider_manager`、`mcp_tool_factory`、`mcp_stdio_client`，可以把 `cli-anything-* --json` 包装成一个 stdio MCP 服务器，然后像普通 MCP provider 一样接入应用绑定和工作流。
- **工作流节点可扩展**：`api/internal/core/workflow/nodes/tool/tool_node.py` 已经按 `tool_type` 分发 builtin/api/mcp/knowledge/skill/workflow/agent_binding 七种类型。加一种 `cli` 类型，或在设备侧把 CLI 包装成 MCP 再走现有 `mcp` 类型，都能和可视化工作流打通。
- **设备 Agent 定位天然匹配**：CLI-Anything 的哲学就是“在本机软件上给 Agent 一条结构化命令通道”，这正好是钰心AI 设备 Agent 的形态。
- **API 型 harness 能直接进沙箱**：OpenRefine、WireMock、AdGuardHome、Firefly III、Mailchimp、MiniMax、SiYuan、n8n、Dify 等 harness 只依赖 REST API/纯 Python，可以在 Docker 或 SCF 沙箱直接运行。
- **市场/生态位重合**：CLI-Hub 里已经有 Feishu/Lark、WeCom、Sentry、Shopify、Contentful、Obsidian、Joplin、SiYuan、Zotero、n8n 等，很多正是我们应用市场想覆盖的工具。

### 需要注意/不适合的点

- **当前没有 CLI 执行工具**：内置工具里没有 `execute_shell`/subprocess provider，`ToolPolicy` 还把 `execute_shell` 列为 dangerous tool。只导入 SKILL.md 只能让 Agent“知道该用什么”，不能真正执行。
- **沙箱预装不了 GUI 软件**：SCF 沙箱和 Docker 容器没有 Blender/GIMP/ArcGIS 这类桌面软件，相关 harness 必须跑在设备侧。
- **Codex 接入仍是 experimental**：`codex-skill` 是社区贡献，安装脚本是 Bash/PowerShell vendor 方式，依赖完整仓库 checkout；直接照搬要评估维护成本。
- **Windows 兼容不统一**：部分 harness 需要 `bash` + `cygpath`，或仅支持 macOS/Linux（NSLogger、Safari、QuietShrink 等）。
- **供应链与安全**：注册表里的工具由社区维护，安装命令可能来自任意 GitHub/PyPI/npm；虽然项目已修过 token 路径穿越、XML 注入等问题，接入时必须做安装来源白名单和权限隔离。
- **遥测与外部依赖**：`cli-hub` 默认匿名遥测，实时 catalog 放在第三方 CDN；生产接入要确定是否允许、能否镜像。
- **生成式 harness 不是开箱即用**：官方也承认单次生成可能不完整，需要 `refine` 和真实软件 E2E 验证。

## 接入建议（按优先级）

### P0：CLI-Hub 作为工具目录 + 执行器

1. 在 catalog 增加 `cli-hub` prompt 技能：把 `cli-hub-meta-skill/SKILL.md` 转成 `manifest.yaml`（`executor_type: prompt`），让 Agent 知道何时用 CLI-Hub、如何搜索和安装。
2. 新增 `cli-hub` 沙箱技能（`executor_type: scf`）或 builtin tool provider，暴露 `hub_search`、`hub_install`、`hub_run` 工具，内部用 subprocess 调 `cli-hub` / `cli-anything-*`。先选纯 API/纯 Python harness 验证，例如 OpenRefine、WireMock、MiniMax、Firefly III。
3. 安全策略：白名单注册表来源、限制安装命令、禁止 `pip install git+` 之外的非预期来源、`CLI_HUB_NO_ANALYTICS=1`。

### P1：设备 Agent 集成

1. 设备端预装 `cli-anything-hub` 和目标软件（Blender、LibreOffice、OBS 等）。
2. 写一个通用的 CLI-MCP 桥：把设备上已安装的 `cli-anything-* --json` 命令自动映射为 MCP tools，注册进我们已有的 MCP provider/manager。
3. 应用“能力接入”里新增“设备 CLI 工具”绑定，复用现有的 MCP/skill 绑定流程，用户端就能把设备能力绑到 Agent 或工作流。

### P2：工作流与市场

1. `tool_node.py` 增加 `tool_type: "cli"`，或在设备侧统一走 MCP 包装；工作流节点可直接编排“OpenRefine 清洗 → 知识库入库 → LLM 总结”这类跨工具流程。
2. 定时同步 `registry.json` / `public_registry.json` 到应用商店，展示 `category`、`requires`、`install_cmd`、`entry_point`、`skill_md`，作为可安装“设备工具”目录。
3. 对纯 API harness，可以复用现有 OpenAPI 交付模式，把 CLI 包装成 REST 端点；优先级低于前两条。

### 最小 PoC 建议

- 在 API 容器 `pip install cli-anything-hub`，选 1-2 个无 GUI 依赖的 harness 跑通 `--json` 子进程调用。
- 新增 `catalog/cli-hub` prompt 技能 + 一个 `cli-hub` SCF 技能包，让 Agent 能在会话里搜索、安装并调用。
- 在设备 Agent 分支上做 CLI-MCP 桥 PoC，注册一个真实桌面软件 harness（例如 LibreOffice 或 Blender），验证“用户让设备 Agent 生成/导出文件”闭环。
- 所有 harness 二进制和依赖都要进设备或沙箱镜像的不可变层，避免运行时任意下载。

## 来源

官方/一手：

- GitHub 仓库：<https://github.com/HKUDS/CLI-Anything>
- README（能力、测试、项目结构）：<https://github.com/HKUDS/CLI-Anything/blob/main/README.md>
- 方法论 SOP：<https://github.com/HKUDS/CLI-Anything/blob/main/cli-anything-plugin/HARNESS.md>
- Codex 技能：<https://github.com/HKUDS/CLI-Anything/tree/main/codex-skill>
- Codex PowerShell 安装器：<https://github.com/HKUDS/CLI-Anything/blob/main/codex-skill/scripts/install.ps1>
- CLI-Hub 包管理器 README：<https://github.com/HKUDS/CLI-Anything/blob/main/cli-hub/README.md>
- 官方注册表：<https://github.com/HKUDS/CLI-Anything/blob/main/registry.json>
- 公共注册表：<https://github.com/HKUDS/CLI-Anything/blob/main/public_registry.json>
- CLI-Hub Meta-Skill：<https://github.com/HKUDS/CLI-Anything/blob/main/cli-hub-meta-skill/SKILL.md>
- 预览协议：<https://github.com/HKUDS/CLI-Anything/blob/main/docs/PREVIEW_PROTOCOL.md>
- Web CLI-Hub：<https://clianything.cc/>、<https://hkuds.github.io/CLI-Anything/>
- Release v0.4.0：<https://github.com/HKUDS/CLI-Anything/releases/tag/v0.4.0>
- 论文：<https://arxiv.org/abs/2606.03854>

本项目代码现状（用于适配判断）：

- Skill catalog：`api/internal/core/skills/catalog/`
- Skill 解析与执行：`api/internal/core/skills/skill_catalog.py`、`skill_executor.py`、`skill_tool_factory.py`
- MCP 基础设施：`api/internal/core/tools/mcp_tools/providers/`
- 内置工具：`api/internal/core/tools/builtin_tools/providers/`
- 工作流工具节点：`api/internal/core/workflow/nodes/tool/`
- 现有同类技能：`api/internal/core/skills/catalog/cli-creator/manifest.yaml`
