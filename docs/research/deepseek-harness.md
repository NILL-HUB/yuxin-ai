# DeepSeek Harness（deepseek-ai/deepseek-harness）深度调研

> 调研时间：2026-08-14。结论优先基于一手来源：官方 GitHub 仓库 README 与 `docs/`、DeepSeek 官网 Harness 页、npm/PyPI 元数据、以及仓库源码；媒体信息只在无法从一手资料确认时作为补充并单独标注。

## 结论

**DeepSeek Harness（`dsh`）是 DeepSeek 官方开源的通用 Agent Harness / 编码智能体框架，不是模型，也不是普通聊天壳。** 官方给出的公式是 `Agent = Model + Harness`：模型负责理解、推理和生成，Harness 负责文件系统、终端、网页、工具、会话、沙箱、记忆、调度、UI 等“让 Agent 在真实环境里持续工作”的部分。

它目前是 **v0.1 开发者预览版**，MIT 协议开源，TypeScript / Cordis 技术栈，提供 Web UI、headless CLI、Python/JSON-RPC SDK 和 npm 插件生态。核心设计是“**一切皆插件**”：模型适配器、工具注册表、会话日志、Agent Loop、沙箱、存储、调度、UI 都由插件组成，用户通过配置层组合和替换，不需要改源码。

对 OpenAgent 而言：

1. **它不是一个 LangGraph 替代品**，而是一个完整的、产品级的 coding-agent harness，可以作为“外部编码 Agent 引擎”接入，也可以作为我们自研 harness 的架构参考。
2. **当前最值得做的是 Linux 容器里的 headless PoC**，用官方 Python SDK 或 JSON-RPC 把 dsh 跑成 OpenAgent 平台的一个执行器/子 Agent。
3. **不建议现在把 OpenAgent 核心执行层迁到 TypeScript/Cordis**。dsh 没有多租户、账号、计费、RBAC、应用发布等平台能力，而这些都是 OpenAgent 的底座；dsh 更适合当“会写代码的执行器”嵌进来。

主要门槛：官方 Python SDK 运行时 wheel 只有 Linux x64 / Linux arm64 / macOS arm64，**当前不支持 Windows**；整个项目处于快速迭代期，README 明确警告“会有破坏兼容性的变更”。

## 它是什么

### 官方定位

DeepSeek 官网 Harness 页的表述：

> DeepSeek Harness 开发者预览版面向全球 Harness 开发者开放测试，并同步开放源代码。模型、工具、技能、会话、沙箱、存储、循环、调度、UI 等所有 Agent 能力均由插件组合而成，可以自由替换和灵活重组。

官网同时给出三个支柱：

| 支柱 | 含义 |
| --- | --- |
| Cordis 内核 | 只负责插件的加载、卸载和依赖关系，不承载 Agent 的具体能力 |
| 插件提供能力 | 模型、工具、技能、会话、沙箱、存储、循环、调度、UI 都由插件提供，通过 Cordis 服务与事件协作 |
| 配置层自由组合 | 开发者不改源码，就能在配置层选择、替换或扩展任一能力 |

### 项目元数据

| 项目 | 值 |
| --- | --- |
| 官方仓库 | <https://github.com/deepseek-ai/DeepSeek-Harness> |
| 官方页面 | <https://www.deepseek.com/harness/> |
| 语言 | TypeScript |
| 协议 | MIT |
| 当前版本 | `@deepseek-ai/dsh@0.1.0-rc.6`（npm，2026-08-13 发布） |
| Python SDK | `deepseek-harness-sdk 0.1.0rc6`（PyPI） |
| GitHub 规模 | 截至 2026-08-14 约 36.5k stars、2.8k forks |
| 仓库公开时间 | GitHub API 显示 2026-08-13 创建；npm 最早的 `0.0.1-rc.1` 出现在 2026-08-10 |
| 状态 | 开发者预览版，README 明确警告未来将有破坏兼容性的变更 |
| 反馈渠道 | GitHub Discussions、Discord、企业微信群 |

### 与 Codex / Claude Code 的关系

行业报道把它定位为对标 OpenAI Codex 和 Anthropic Claude Code 的编程/办公生产力工具，重心是代码智能体和本地开发。这个定位与官方页面“面向 Harness 开发者”“编程 Agent”一致。需要说明的是：**dsh 本身不是 Codex 或 Claude Code 的封装**，而是与它们同一层级的 Agent Harness；它甚至内置了 Codex / Claude Code 作为子 Agent provider 的插件，可以把工作委派给外部 CLI Agent。

## 核心架构

### 1. Cordis 与“一切皆插件”

dsh 底层是 vendored 的 [Cordis](https://github.com/cordiverse/cordis) 插件框架，其设计论文是 [A Programming Paradigm for Spatiotemporal Composability](https://github.com/cordiverse/paper)。Cordis 的五个核心概念：

- **插件**：导出 `apply(ctx)` 的模块，或带生命周期注入的 Service 类。
- **上下文**：`ctx` 是服务仓库，服务通过稳定 key（如 `ctx.tools`、`ctx.llm`、`ctx.sessions`）被发现，插件之间不直接 import 具体实现。
- **依赖注入**：插件声明 `inject`，框架等依赖服务就绪后再加载，不靠手工启动顺序。
- **类型化事件**：服务通过 `emit`、`waterfall`、`parallel`、`serial` 四种分派模式通信。
- **可逆副作用**：注册项都是 effect，插件卸载时自动撤销，支持热重载。

产品没有“特权内核”：模型适配器、工具注册表、会话日志、Agent Loop 本身都是插件，所以都可以从配置替换。

### 2. Profile / Bundle / 配置层

一个运行中的 `dsh` 是一棵插件树，启动时按层组合：

- **Profile**：`$DSH_HOME/profiles/<name>` 下的具名组合，列出它叠放的 bundle、外部插件和用户自己的 `cordis.patch.yml`。
- **Bundle**：npm 包形式的分发单元，通过 `package.json` 的 `dsh.bundle` 字段声明一个 patch 文件，向插件树贡献配置行。
- **Patch**：按行 id 替换配置或插入新行；层级顺序是 bundle 列表 → profile patch → home patch → `--patch` overlay。

可以用 `dsh --profile web --dump-config` 查看实际启动的完整配置树。`dsh-base` 是每个 profile 的第一层，提供模型适配器、工具、持久化、沙箱与审批策略、设置、凭据、遥测；`dsh-web-app` 加浏览器 UI；`dsh-headless` 加一次性运行器且不带 HTTP 服务。

### 3. 会话事件日志（Session Event Log）

dsh 最核心的持久化模型是**仅追加的 `SessionEvent` 日志**：

- 每条持久事件有单调 `seq`、时间、payload、可选的 surface 元数据。
- 模型看到的一切都必须先落到日志：系统提示词、用户消息、assistant 内容、`assistant/chunk`、工具调用与结果、上下文注入、子 Agent 调度都被记录。
- 官方原则是“**模型可见即已记录**”（model-visible means logged），并有一条运行时 invariant 校验：任何到达模型请求的输入都必须能从日志重建。
- 会话恢复、fork、回放、transcript、遥测、UI 都从同一份事件流派生。
- 持久化后端默认是 JSONL（默认用带校验和的 Zstandard 帧压缩，也可配置为明文行），另有 SQLite 后端；会话格式版本目前为 `0`，属 pre-release，官方明确不承诺兼容。

### 4. 轮次 / 步骤生命周期

官方把执行模型拆成 step 和 turn：

- **step**：一次模型请求加上它调用的工具。
- **turn**：零个或多个 step，从领取首条输入开始，到不再欠任何工作时结束。

典型流程：

```text
turn/start
  claim next-step input + one queued message
  assemble prompt sections + tool schemas
  -> agent/pre-step（可改写或拒绝）
  step/start
  derive model history from session log
  agent/request -> llm/stream -> assistant/chunk* -> assistant/message
  tool/call* -> tools/pre-execute -> tools/execute -> tools/post-execute -> tool/result*
  step/end
turn/end
```

事件分为三层：持久会话事件（`turn/*`、`step/*`、`user/message`、`assistant/*`、`tool/*`）、实时 Agent 事件（`agent/*`）、能力事件（`fs/*`、`tools/*`、`telemetry/*` 等）。`agent/pre-step`、`agent/request`、`llm/stream`、三个 `tools/*` 事件是 waterfall，监听器必须调 `next()` 才能委派。

### 5. 能力 Seam

dsh 把可替换能力定义为“seam”，包含三个角色：

1. **Service Definition**：声明接口。
2. **Service Provider**：实现接口。
3. **Consumer**：使用接口，通常是面向模型的工具。

例子：文件系统与子进程 provider 共享同一个执行世界，把 provider 指向远程沙箱，Bash、PTY、LSP 就一起搬过去；子 Agent provider 可以从进程内 spawn、fork，也可以换成 ACP、Codex、Claude Code 或 dsh-sdk 的独立子进程。

### 6. 标准 Agent 的模型可见工具

官方 `standard` preset 的 `agent.cordis.yml` 实际挂载的能力包括：

| 能力族 | 工具/插件 |
| --- | --- |
| Shell | `bash`（POSIX）/ `pwsh`（Windows），支持持久 shell |
| 文件 | `read`、`write`、`edit`、`read_image`、`glob`、`grep`、`str_replace_editor` |
| 后台任务 | `job_list`、`job_output`、`job_kill` |
| 技能 | `skill` 工具 + `.dsh/skills`、`.agents/skills` 等本地发现 |
| 目标 | `create_goal`、`get_goal`、`update_goal` |
| 计划 | `/plan` + `exit_plan_mode`（软性计划模式，不替代 sandbox/approval） |
| 压缩 | `compact` 命令 + 自动 compaction + tool-result pruner |
| 子 Agent | `subagent`、`subagent_fork`、`send_message`、`interrupt_agent`、`list_agents`、`report` |
| 工作流 | `workflow`（模型写脚本，worker_thread 执行） |
| 网页 | `web_search`、`web_fetch` |
| 其他 | `todo_write`、`ask_user_question`、`lsp`、`terminal_*`、`schedule_*`、`session_search/trace`、`run_code` |

### 7. 安全、沙箱与权限

这是 dsh 做得比较系统化的部分：

- **Sandbox mode**：`read-only`、`workspace-write`、`danger-full-access`。前两者会真正包一层 argv；`danger-full-access` 是显式放行，不调用沙箱。
- **沙箱后端**：Linux bwrap/Landlock、macOS Seatbelt、Windows ACL restricted-token runner；后端会报告 `full` 或 `partial` enforcement，`partial` 时调用方不能把它当绝对边界。
- **Approval policy**：`ask` / `never`，默认 `ask`；`never` 用于 CI/无人值守；审批结果 fail-closed，只有 `allowed-once` 会放行。
- **默认权限**：新会话默认 `workspace-write`，写操作限制在会话 workspace 和平台临时目录；读、网络、进程可见性不在沙箱词汇内。
- **凭据**：保存在 `$DSH_HOME/.credentials.yaml`，模型页面只回传脱敏描述符；另支持环境变量和 `.env`。
- **遥测**：默认关闭；`DSH_TELEMETRY_MODE=FULL` / `FEEDBACK_ONLY` 才会上报，默认无脱敏规则，所以不建议随意开启。
- **MCP**：CLI 自带 `@deepseek-ai/dsh-mcp-client`，但**默认不启用任何 MCP server**，因为 MCP server 命令是可执行代码，位于 Agent 沙箱之外。
- **Web**：默认只监听 `127.0.0.1:3080`，官方 CLI 目前不支持 `--host 0.0.0.0`；远程使用要走 `--trusted-host` 或反向代理。

## 运行方式

### 四种 Agent preset（模式）

官方页面和仓库 `apps/cli/config/agent-presets/` 均确认四种模式：

| 模式 | 官方描述 | 适用 |
| --- | --- | --- |
| 标准模式 | 功能完整的编码 Agent，支持文件编辑、Shell、文件与网页检索、Skills、计划、目标、子代理和工作流 | 日常编码 Agent |
| PTC 模式 | 具备标准模式的全部能力，并通过 Code Mode SDK 呈现工具，让模型用一个 TypeScript 程序组合多步操作 | 多步工具工作流，减少往返 |
| 极简模式 | 仅提供持久 `bash` 与 `str_replace_editor` 的双工具编码 Agent | 最小环境基准、简单任务 |
| 创造模式 | 具备标准模式的全部能力，并提供运行时检查、插件实验和 preset 创作指导 | 创建自定义 Agent preset |

注：“PTC”在媒体报道中解释为 Programmatic Tool Calling（程序化工具调用）；官方中文页没有展开全称。

### Web UI

```sh
npx @deepseek-ai/dsh web
```

默认地址 `http://127.0.0.1:3080`。首次启动自动初始化 `web` profile，选择 workspace 后即可创建会话。支持多模型 provider、Trajectory 视图、插件管理、permission preset、后台任务、会话 fork 等。

### Headless / CLI

```sh
dsh --profile headless "fix the failing test in this workspace"
```

headless profile 会创建一次全新持久会话，打印最终答案后退出；`completed` 退出码 0，否则 1。它不启动 HTTP 服务，适合 CI、脚本和 SDK 包装。插件管理：

```sh
dsh plugin --profile <name> add <package-or-git-spec>
```

`dsh plugin` 实际转发给 pnpm，在 profile 目录里安装依赖并自动把声明了 `dsh.bundle` 的包加入 layer stack。

### Python SDK / JSON-RPC

```sh
python -m pip install deepseek-harness-sdk
```

```python
from deepseek_harness import DeepSeekHarness

with DeepSeekHarness(
    provider="deepseek-official",
    model="deepseek-v4-flash",
    max_tokens=49_152,
    cwd="/abs/path/to/workspace",
    session_root="/abs/path/to/sessions",
    cordis="examples/jsonrpc-agent/minimal.cordis.yml",
) as harness:
    result = harness.run("Inspect the repository and fix the failing tests.", session_id="example-001")
```

SDK 通过新行分隔 JSON-RPC stdio 驱动一个子进程运行时，自带 DeepSeek adapter、JSONL 持久化、本地 bash 和文件工具。**官方运行平台限制：Linux x64、Linux arm64、macOS 14+ arm64；没有 Windows wheel。** 安装 SDK 时会同时安装 `deepseek-harness-runtime-bin`（内含单文件 Node 可执行运行时），目标机器不需要自己装 Node。

### 插件开发与分发

- 一个插件就是一个导出 `apply(ctx)` 的 TypeScript 模块。
- 通过 `cordis.yml` / `cordis.patch.yml` 插入插件行，`--patch` 可覆盖配置。
- 打包成 bundle：在 `package.json` 声明 `dsh.bundle.patch`，然后 `dsh plugin --profile <name> add <pkg>`。
- 发布方式可以是 npm、本地 tarball 或 git host；Git 安装时 pnpm >=10 会拦截 `prepare` 脚本，需要在 profile 的 `pnpm-workspace.yaml` 里显式 allowBuilds。
- GitHub 上有 `dsh-plugin` topic，用于社区插件发现。

## 生态与版本

### npm

- CLI：`@deepseek-ai/dsh`，`dsh` bin。
- 官方插件包按 `@deepseek-ai/dsh-*` 命名，npm 搜索可见约 14 个官方包；仓库内部实际有更多独立包，覆盖 agent、agent-loop、llm、session、compaction、sandbox、shell、fs、skill、subagent、workflow、web、mcp、terminal、jobs、schedule 等。
- 社区已有 `dsh-grok-tui`、`task-passport`、图像生成插件等，生态刚起步但发布速度很快。

### PyPI

- `deepseek-harness-sdk 0.1.0rc6`：Python >=3.10，依赖 `pydantic>=2.12,<3` 和 `deepseek-harness-runtime-bin==0.1.0rc6`。
- `deepseek-harness-runtime-bin` 只发布三个 wheel：`manylinux_2_28_x86_64`、`manylinux_2_28_aarch64`、`macosx_14_0_arm64`。

## “一切皆插件”是怎么实现的

“一切皆插件”不是一句宣传语，而是由两层机制共同保证的：**Cordis 插件内核提供插件生命周期与可逆副作用，dsh 产品层在它之上定义服务 seam、scope、registry 和配置组合**。

### 1. 插件内核：Cordis

dsh 不是简单 import 一个插件框架，而是把 [Cordis](https://github.com/cordiverse/cordis) 整个 vendored 进仓库，改名成 `@deepseek-ai/cordis` 并打了大量本地补丁（`vendor/README.md` 记录了 18 项本地修改，包括事务化 Loader、配置热更新、effect 生命周期加固、Windows 配置写入重试等）。

Cordis 的核心模型：

- **插件 = `apply(ctx)`**：一个插件是一个函数/对象/Service 类，通过 `apply(ctx)` 注册能力。
- **上下文 = 服务仓库**：`ctx.tools`、`ctx.llm`、`ctx.sessions` 等是稳定服务 key；插件之间按 key 找服务，不互相 import 实现。
- **依赖注入**：插件用 `inject` 声明依赖，框架等依赖服务 ready 后才执行 `apply`，加载顺序由依赖关系决定，而不是手工排序。
- **可逆副作用**：工具注册、监听器、定时器、prompt section 都通过 `ctx.effect()` / `ctx.on()` 安装；插件卸载时自动逆序撤销。dsh 源码里几乎每个 `register()` 都返回“精确的 disposer”，供上层嵌套进自己的 effect 保证卸载顺序。
- **类型化事件**：事件分 `emit` / `waterfall` / `parallel` / `serial` 四种分派模式；policy、metrics、approval 都是通过监听事件拦截，而不是改 Agent Loop 源码。

### 2. 配置层：profile / bundle / patch

插件本身只是“能力”，真正决定“一个 Agent 长什么样”的是配置组合：

```yaml
# 简化版 cordis.yml 概念
- id: tool-bash
  name: '@deepseek-ai/dsh-tool-bash'

- id: tool-fs
  name: '@deepseek-ai/dsh-tool-fs'

- id: planning
  name: cordis:group
  group: true
  isolate:
    planMode: true
  config:
    - id: plan-mode
      name: '@deepseek-ai/dsh-plan-mode'
```

Loader 把这类行当成配置项挂载：

- `id` 是行身份，后层 patch 可以按 id 替换整行 config。
- `name` 解析到插件包；`disabled` 可以是 `!!js` 动态表达式。
- 层级是 bundle 列表 → profile patch → home patch → `--patch` overlay，后面的层按行覆盖前面的层。
- 配置变化会走事务化 reload：先加载新插件，成功后再卸载旧插件；失败回滚，避免留下半配置状态。

所以“不改源码扩展能力”是字面成立的：能力由插件提供，装配关系完全由配置决定。

### 3. 服务 seam：定义、实现、消费分离

dsh 把可替换能力抽象成“seam”，每种能力都拆成三个角色：

| 角色 | 例子 |
| --- | --- |
| Service Definition | `ctx.tools`、`ctx.llm`、`ctx.shell`、`ctx.sandbox`、`ctx.skills`、`ctx.subagents` |
| Service Provider | `dsh-bash-local`、`dsh-bash-sandbox`、`dsh-web-search-exa`、`dsh-subagent-codex` |
| Consumer | 面向模型的工具，如 `bash`、`web_search`、`subagent`、`skill` |

以工具为例，`packages/core/tools/src/index.ts` 里的 `ToolRuntime` 是真正的注册表和执行流水线：

- 每个工具定义包含 schema、执行函数、canonical output 声明和展示回调。
- 注册后自动接入 `systemPrompt`，把工具 schema 组装进模型可见的 prompt。
- 执行流水线有 `tools/pre-execute` → `tools/execute` → `tools/post-execute` 三道 waterfall，policy、审批、限流、metrics、错误处理都可以挂在这里。
- 返回的 disposer 精确注销这次注册，支持热重载。

同一个模式贯穿 LLM adapter、skills、subagent、web、persistence、sandbox 等所有能力族。

### 4. Scope：为什么每个 Agent 可以有不同的插件集合

“一切皆插件”最难的部分不是加载插件，而是让同一个进程里不同会话/Agent 看到不同能力集。dsh 的做法是 `dsh-scope`：

- `createScope(ctx, key)` 给一个 Agent 铸造独立上下文；通过这个上下文注册的工具、prompt section、监听器都属于该 Agent。
- `bindScopeParent(child, parent)` 把子 Agent 的 scope 挂到父 scope / preset 的 standing mount 下，于是子 Agent “继承”父级的注册。
- 工具注册表用 `ScopedLayers` 保存多层 layer；读取时从当前 Agent 的 scope 链向上找，最近的 layer 覆盖全局。
- 事件向上分派：父级监听器能看到所有子 Agent 的事件，但子 Agent 看不到兄弟/父级之外的事件。
- Agent preset 是“一次 standing mount，多个 Agent join”：preset 的插件实例和注册只创建一次，Agent 通过 scope 父子关系加入，而不是每个会话复制一份插件树。

这解释了四种模式为什么能共存：标准、PTC、极简、创造本质上是四个不同的 standing composition，同一个 dsh 进程可以同时跑。

### 5. 会话日志是插件的“统一事实层”

插件之间通过 SessionEvent 日志协作，而不是各自维护状态。任何模型可见输入都必须先写日志，再从日志 `deriveMessages()` 投影出模型历史；UI、fork、resume、telemetry 都只读这一份日志。这让插件可以自由增删，但运行事实始终可重放、可审计。

### 6. 统一纪律

dsh 能把“一切皆插件”执行到这么彻底，还靠几条硬纪律：

- **fail loud**：能力缺失、schema 不支持、provider 未配置，都在调用前报错，不静默降级。
- **fail closed**：审批、沙箱、凭据解析失败默认拒绝，不偷偷放行。
- **model-visible means logged**：模型能看到的东西必须能从日志重建。
- **精确 disposer**：每个注册都返回自己的卸载函数，不允许“注册了但不知道在哪注销”。
- **scope 是身份的组成部分**：工具、技能、子 Agent、审批都按 Agent scope 路由，而不是全局一把梭。

## OpenAgent 可以借鉴什么

结论：**可以借鉴，而且我们已经有很接近的雏形，不需要照搬 Cordis/TypeScript。**

### 我们已有的相似物

OpenAgent 已经有“provider manager + 协议端口 + 服务注入”的雏形：

| 现有实现 | 对应 dsh 概念 |
| --- | --- |
| `BuiltinProviderManager` | 工具 provider 注册表 |
| `ApiProviderManager` | 动态生成工具 |
| `McpProviderManager` + MCP factory | 外部工具 provider |
| `LanguageModelManager` | LLM provider registry / adapter |
| `ObjectStoragePort`（Protocol） | seam / Service Definition |
| `injector @singleton` | DI 容器，但没有插件生命周期 |
| `BaseAgent` + `AgentQueueManager` | 简单版 agent 生命周期与事件 |

所以我们不是从零起步，而是把现在“各自独立的 manager”升级成**统一的运行时上下文 + 注册/注销契约 + 配置组合**。

### 值得借鉴的最小闭环

建议先做一条端到端链路，而不是全面铺开：

1. **定义统一 `RuntimeContext`**：一个持有 service map、注册表和 disposer 列表的上下文对象；所有能力都从 `ctx` 找服务，而不是直接 import manager。
2. **定义 capability seam 协议**：`ToolProvider`、`LLMProvider`、`SandboxProvider`、`ApprovalPolicy`、`SubagentProvider`、`SessionStore` 都用 `Protocol`/ABC 声明接口，每个 seam 分开 package/模块。
3. **给工具执行加中间件流水线**：在 `ToolInvokerService` 上加 `pre_execute` / `execute` / `post_execute` 钩子，让审批、限流、计量、审计可以像 dsh 一样挂在事件上。
4. **做配置化 Agent preset**：把“标准 / 极简 / 深思考 / 多 Agent”等 preset 定义为 JSON/YAML 组合行，每行声明要启用的工具、provider、prompt section、沙箱策略；应用/会话按 preset id 装配，而不是在代码里硬编码组合。
5. **引入可逆副作用**：所有注册返回 disposer；进程退出、应用删除、preset 切换时逆序清理，避免 manager 越攒越多。
6. **会话状态向事件日志演进**：至少先把模型可见的输入、assistant 输出、工具调用/结果、上下文注入都记录成带 seq 的事件流，再做 fork/resume/trajectory。

### 不建议借鉴的部分

- 不引入 TypeScript/Cordis 作为我们的运行时底座，Python 生态和现有代码成本太高。
- 不做“从 npm 任意加载插件代码”的多租户机制：这带来供应链和代码执行风险，我们的开放形态更适合“内置 provider 注册 + 数据库启用的工具/技能 + 受控 MCP/OpenAPI”。
- 不为借鉴而把 LangGraph 拆掉；LangGraph 已经承担状态图编排，我们要借的是它外围的“seam + registry + composition”，不是重写状态图。

## 对 OpenAgent 的适配分析

### 现状对比

| 维度 | OpenAgent（钰心AI） | DeepSeek Harness |
| --- | --- | --- |
| 语言/运行时 | Python 3.11+、Quart、Celery | Node.js、TypeScript、Cordis |
| Agent 编排 | LangChain / LangGraph，`BaseAgent`、`FunctionCallAgent`、`DeepThinkingAgent`、`ReACTAgent` | 自研 Agent/AgentLoop，step/turn 事件生命周期 |
| 会话状态 | DB 会话 + LangGraph Redis checkpoint + token buffer memory + 自研 context compression | 仅追加 SessionEvent 日志 + JSONL/SQLite + compaction seam |
| 工具 | LangChain `BaseTool`、MCP factory、Workflow 工具适配器 | `ctx.tools` 注册表 + capability seam |
| 工作流 | 可视化节点编排（LLM、工具、RAG、代码、HTTP、分支等） | 模型写 JavaScript/TypeScript workflow 脚本 + 子 Agent |
| Skills | 平台 Skill 体系 | `.dsh/skills`、`.agents/skills` 等本地分层目录 |
| 模型 | OpenAI、DeepSeek、Anthropic、Grok、Qwen、Ollama 等 | DeepSeek adapter + Pi-AI + Anthropic/OpenAI/Bedrock/Vertex/Azure/Codex 等 catalog |
| 沙箱 | 已见 Baidu CFC sandbox backend 等 | bwrap/Landlock/Seatbelt/Windows ACL |
| 多租户/计费 | 有账号、应用、发布、计费、OpenAPI | 无；本地单用户产品 |
| UI | Vue 3 工作台 | 官方 Web UI（Trajectory 视图等） |

### 可行的接入路径

1. **Linux 容器 headless PoC（推荐先做）**
   在 Docker 里安装官方 Python SDK，把 dsh 当作“会写代码的执行器”。OpenAgent 侧通过一个适配服务把任务、workspace、session_root 传给 dsh，拿回 `final_response`、事件和 session JSONL。这个路径对现有 Python 栈侵入最小。

2. **作为平台内“编码 Agent”类型**
   在现有应用类型/Agent 类型里增加一个 “DeepSeek Harness coding agent” 执行器，使用 dsh 的 headless profile 或 JSON-RPC SDK。可以在 OpenAgent 的 OpenAPI 或 A2A 路由里作为子 Agent 调用，类似已有的 assistant agent / 子 Agent 委派。

3. **用 ACP 桥接**
   dsh 自带 `packages/acp`、`subagent-acp` 和 `examples/acp-agent`，支持 ACP（Agent Client Protocol）。如果 OpenAgent 侧已经或计划支持 ACP，可以直接把 dsh 当作 ACP agent 驱动，而不是自己维护 JSON-RPC 协议。这条需要先做协议验证。

4. **架构借鉴**
   dsh 的 SessionEvent 日志、能力 seam、审批/沙箱分离、compaction、agent preset 分层都值得对照我们现有实现。我们已经有 `api/internal/core/context_compression/` 和工具/MCP 体系，可以先做差距分析，再把合适的设计搬回 Python。

### 不建议的路径

- **用 dsh 重写 OpenAgent 核心**：会丢掉多租户、账号、计费、发布、RAG、可视化工作流等平台能力，而且 Python SDK 不支持 Windows、API 不稳定。
- **直接把 `npx @deepseek-ai/dsh web` 作为生产 Web 服务**：官方当前面向本地开发，`--host 0.0.0.0` 不支持，没有多租户和鉴权体系，需要大量自建。
- **在生产开 MCP/代码执行而跳过审批和沙箱**：PTC 模式会让模型生成 TypeScript 并执行，MCP server 也是沙箱外可信代码；必须保留 approval/sandbox 边界。

## 落地建议

1. **1 到 2 周**：做 Linux 容器 PoC。Dockerfile 装 `python:3.11`、`pip install deepseek-harness-sdk`，用一个 disposable workspace 跑 `minimal.py` 或 headless CLI；验证 DeepSeek API key、模型 `deepseek-v4-flash`、session JSONL、工具调用、错误恢复。
2. **PoC 通过后**：设计 `DshExecutor` 适配服务。输入输出对齐现有 `SingleAgentExecutor` / `MultiAgentExecutor` 的调用形状；把 dsh session id 映射到 OpenAgent conversation/message；记录 token usage 和计费。
3. **并行做架构评估**：把 dsh 的 SessionEvent 日志、seam 接口、compaction、approval/sandbox 与我们现有实现逐项对比，输出一份差距清单；重点关注是否把我们的 conversation 状态模型往“事件日志 + 投影”演进。
4. **验收指标**：能在一个干净 Linux 容器里完成“读仓库 → 改代码 → 跑测试 → 返回 diff/结果”；同一任务 10 次不出现不可恢复的会话损坏；能按用户隔离 workspace 和 session；能统计模型调用次数、token、成本。

## 风险与注意点

- **预览期**：版本才 `0.1.0-rc.x`，README 明确警告破坏性变更；`SESSION_FORMAT_VERSION = 0`，官方不承诺兼容。不要把持久化格式当成稳定契约。
- **迭代速度极快**：npm 首个 rc 在 2026-08-10，rc.6 在 2026-08-13；仓库公开首日即约 36.5k stars。功能、文档和配置项可能每天变化。
- **平台限制**：Python SDK 无 Windows；Web/CLI 支持 Windows（有 pwsh 工具和 Windows ACL 沙箱），但 Python 集成只能在 Linux/macOS 容器或机器上跑。
- **安全边界**：默认 `workspace-write`，但网络、进程可见性不在沙箱词表内；Windows ACL 沙箱是 `partial` enforcement；`web_fetch` 默认禁用，因为它可能访问内网目标。
- **MCP 与代码执行**：MCP server 和 PTC 的 `run_code` 都是可执行代码，默认策略之外需要额外信任评估。
- **遥测**：默认关闭，但一旦开启可能包含消息文本、工具参数和 workspace 路径，且默认无脱敏规则。
- **平台能力缺失**：没有多租户、计费、RBAC、应用市场、版本发布等；这些是 OpenAgent 现有底座，接入时不能让 dsh 反向主导产品边界。

## 资料来源

### 一手来源

- DeepSeek Harness 官网：<https://www.deepseek.com/harness/>
- 官方仓库：<https://github.com/deepseek-ai/DeepSeek-Harness>
- 官方中文 README：<https://github.com/deepseek-ai/DeepSeek-Harness/blob/master/README.zh.md>
- 官方架构文档：<https://github.com/deepseek-ai/DeepSeek-Harness/blob/master/docs/architecture.md>
- Agent 生命周期：<https://github.com/deepseek-ai/DeepSeek-Harness/blob/master/docs/agent-lifecycle.md>
- CLI 行为参考：<https://github.com/deepseek-ai/DeepSeek-Harness/blob/master/apps/cli/reference/README.md>
- Python SDK 指南：<https://github.com/deepseek-ai/DeepSeek-Harness/blob/master/docs/user/guide/python-sdk.md>
- 模型配置：<https://github.com/deepseek-ai/DeepSeek-Harness/blob/master/docs/user/guide/providers.md>
- 工具目录：<https://github.com/deepseek-ai/DeepSeek-Harness/blob/master/docs/tool-catalog.md>
- 配置目录：<https://github.com/deepseek-ai/DeepSeek-Harness/blob/master/docs/config-catalog.md>
- 持久化目录：<https://github.com/deepseek-ai/DeepSeek-Harness/blob/master/docs/persistence-catalog.md>
- 子系统文档：<https://github.com/deepseek-ai/DeepSeek-Harness/blob/master/docs/subsystems/session.md>（以及同目录 sandbox/approval/compaction/subagent/workflow/skills/web/terminal 等）
- Cordis 入门：<https://github.com/deepseek-ai/DeepSeek-Harness/blob/master/docs/cordis-primer.md>
- Vendored 框架说明：<https://github.com/deepseek-ai/DeepSeek-Harness/blob/master/vendor/README.md>
- 工具注册表与执行流水线源码：<https://github.com/deepseek-ai/DeepSeek-Harness/blob/master/packages/core/tools/src/index.ts>
- Scope 源码：<https://github.com/deepseek-ai/DeepSeek-Harness/blob/master/packages/core/scope/src/index.ts>
- Agent preset 源码：<https://github.com/deepseek-ai/DeepSeek-Harness/blob/master/packages/preset/agent-presets/src/index.ts>
- npm：<https://www.npmjs.com/package/@deepseek-ai/dsh>
- PyPI：<https://pypi.org/project/deepseek-harness-sdk/>
- Cordis：<https://github.com/cordiverse/cordis>
- Cordis 论文：<https://github.com/cordiverse/paper>

### 二手来源（仅用于补充发布背景与模式命名）

- IT之家《对标 Claude Code：DeepSeek Harness 公测，同步开放 npm 插件生态》：<https://m.ithome.com/html/989446.htm>
- DoNews《DeepSeek 正式开源 Harness》：<https://www.donews.com/news/detail/1/6670452.html>
- 爱范儿首发体验：<https://www.ifanr.com/1675083>
