# Hermes v0.20 与钰心AI 能力深度盘点

> 更新日期：2026-08-13
> 定位：对 `docs/research/hermes-agent-v0-20-comparison.md` 的补充，按“子系统 + 源码落点 + 运行状态”逐项盘点，
> 补齐此前只写模块名、没有展开核心机制的部分。Hermes 侧以仓库 `NousResearch/hermes-agent` tag `v2026.8.3`
> 源码为准；钰心AI 侧以本仓库当前工作区源码为准。

## 0. 结论速览

- Hermes 的核心不是“一个能对话的模型客户端”，而是一整套**学习闭环、技能生命周期、多端执行环境、消息网关、
  定时/事件自动化、多 Agent 协作和本地可观测**的运行时。
- 钰心AI 也不是“只有对话”，它已经具备编排决策、工具池治理、知识库、记忆、工作流、应用商店、计费、RBAC、
  OpenAPI 交付、标准 A2A、HMAC webhook、宿主机自动化等能力；真正薄弱的是 Hermes 那种**自主技能涌现、
  Curator 维护、跨端持续学习、真实终端/浏览器/桌面环境、以及超长任务的中断续跑**。
- 两边目前最值得对标的不是“谁工具多”，而是**执行生命周期、用户授权交互、学习与技能成长、状态可恢复**这四件事。

---

## 1. Hermes v0.20 深度能力全景

### 1.1 核心 Agent 引擎与轮次生命周期

源码位置：`run_agent.py`、`agent/conversation_loop.py`、`agent/turn_context.py`、
`agent/turn_retry_state.py`、`agent/turn_summary.py`、`agent/turn_finalizer.py`。

已确认能力：

- 自研主循环，非 LangChain 封装；模型工具 schema 是“窄腰”，新增能力优先走 CLI 命令 + skill、service-gated tool、
  插件或 MCP server，而不是加核心工具（见仓库 `AGENTS.md` 的 Footprint Ladder）。
- turn 级生命周期分离：`TurnContext` / `TurnRunner` / `TurnFinalizer` / `TurnSummary` / `TurnRetryState`，
  一轮失败可在轮内重试状态中恢复，而不是整个会话重开。
- `iteration_budget` 控制最大工具迭代数；`reasoning_timeouts` / `thinking_timeout_guidance` /
  `thinking_timeout` 处理思考超时；`stream_single_writer` 防止多个流写同一响应。
- `interrupt_compat` + `interrupt` 支持 Ctrl+C / 新消息打断；打断后保留未完成工作，可 mid-turn redirect。
- `bounded_response`、`message_sanitization`、`think_scrubber` 负责输出边界、消息清洗与思考区清洗。
- `background_review`、`verification_evidence`、`verify_hooks`、`verification_stop` 构成“验证证据 + 后台复核 +
  可核实停止”的 grounding 机制（对应 release 里的 grounded-citations / 事实核查）。
- `title_generator`、`session_activity`、`reactions`、`portal_tags` 等负责会话标题、活性、表情反应和标签。

### 1.2 模型接入、计费与用量

源码位置：`agent/transports/*`、`agent/*_adapter.py`、`plugins/model-providers/*`、
`agent/billing_usage.py`、`agent/billing_view.py`、`agent/credits_tracker.py`、`agent/usage_pricing.py`、
`agent/credential_pool.py`、`agent/credential_sources.py`、`agent/secret_sources/*`。

已确认能力：

- 传输层抽象 `BaseTransport`，落地实现：`chat_completions`、`anthropic`、`bedrock`、`codex`、
  `codex_app_server`、`hermes_tools_mcp_server`；另有 `codex_responses_adapter`、`gemini_native_adapter`、
  `vertex_adapter`、`azure_identity_adapter`、`copilot_acp_client`、`lmstudio_reasoning` 等适配器。
- 模型 provider 插件目录 `plugins/model-providers/`，30+ 个：anthropic、gemini、bedrock、vertex、
  azure-foundry、openai-codex、copilot/copilot-acp、deepseek、kimi-coding、minimax、stepfun、qwen-oauth、
  xai、zai、xiaomi、nvidia、novita、fireworks、deepinfra、huggingface、arcee、upstage、openrouter、nous、
  custom、ai-gateway、alibaba、gmi、kilocode、ollama-cloud、opencode-zen 等。
- 统一 credential pool / secret scope / secret sources（Bitwarden、1Password、command），凭据不散落在 agent 循环里。
- 计费：`billing_usage` / `billing_view` / `credits_tracker` / `usage_pricing` / `subscription_view` /
  `nous_rate_guard` / `account_usage`，并记录 `session_model_usage`（token、cache read/write、reasoning、
  估算/实际成本、按 task 维度拆账）。
- `model_metadata` / `models_dev` / `model_catalog` 管理模型目录；`credential_pool` 支持多 Key 轮换；
  `nous_rate_guard` 做限流保护。

### 1.3 上下文管理

源码位置：`agent/context_engine.py`、`agent/context_compressor.py`、`agent/conversation_compression.py`、
`agent/prompt_caching.py`、`agent/context_breakdown.py`、`agent/manual_compression_feedback.py`、
`plugins/context_engine/`。

已确认能力：

- 可插拔 `ContextEngine` ABC，默认 compressor，可被第三方引擎替换；只有单个引擎激活。
- 自动压缩触发点：每轮检查 token 用量、决定压缩时机、压缩时发状态消息；`manual_compression_feedback`
  支持用户反馈压缩质量。
- 保证 N 条用户消息尾巴、逐轮微压缩、工具结果主动裁剪、ghost-skill 防御（release 声称，源码含
  `conversation_compression` / `prompt_caching` / `context_breakdown` 支撑）。
- 明确“prompt caching 神圣不可破坏”：不允许会话中途改 system prompt / 换 toolset / 重载记忆，
  唯一例外是上下文压缩；斜杠命令默认 deferred 生效，`--now` 才立即失效。

### 1.4 记忆与学习闭环

源码位置：`agent/memory_manager.py`、`agent/memory_provider.py`、`agent/learn_prompt.py`、
`agent/learning_graph.py`、`agent/learning_graph_render.py`、`agent/learning_mutations.py`、
`agent/curator.py`、`agent/curator_backup.py`、`agent/insights.py`、`tools/session_search_tool.py`、
`hermes_state_search.py`、`plugins/memory/*`。

已确认能力：

- `MemoryManager` 是唯一集成点，一次只允许一个外部 provider；`MemoryProvider` 插件化。
- memory provider 插件：holographic（HRR 编码）、mem0、supermemory、honcho、openviking、retaindb、
  byterover、hindsight。
- Agent-curated memory：`memory` 工具可写 MEMORY.md / USER.md，配合 `learn_prompt` 主动向自己提问、
  `learning_mutations` 更新学习内容。
- **技能涌现**：复杂任务完成后自动创建 skill；技能在使用中可自我改进；`skill_usage.py` 记录
  use_count / view_count / patch_count / last_activity_at / state / pinned。
- **Curator（后台技能维护）**：默认 7 天一次，闲置 2 小时后可触发；只处理 agent-created skill，
  永远不删除，最多归档；归档可恢复；pinned 技能豁免；`hermes curator status/run/pause/resume/pin/
  unpin/archive/restore/prune/backup/rollback`。
- **Learning graph**：把技能节点、MEMORY/USER 记忆块节点、related_skills 与词汇重叠连成图，
  供桌面端可视化“学到的东西”。
- **Session search**：FTS5 + trigram + CJK bigram 三套索引，支持跨会话检索并 LLM 摘要；
  `session_search_tool` 让 Agent 自己也能搜历史。
- `insights.py` 生成使用洞察；`hermes insights --days N` 可查。

### 1.5 技能系统

源码位置：`tools/skills_list|skill_view|skill_manage` 对应 `tools/skills_tool.py`、`tools/skill_manager_tool.py`、
`tools/skill_provenance.py`、`tools/skills_guard.py`、`tools/skills_ast_audit.py`、
`tools/skills_hub.py`、`tools/skills_sync.py`、`tools/skills_sync_client.py`、
`agent/skill_bundles.py`、`agent/skill_commands.py`、`agent/skill_preprocessing.py`、
`agent/skill_utils.py`、`hermes_cli/skills_hub.py`、`skills/`、`optional-skills/`。

已确认能力：

- 仓库自带 `skills/`（14 类，默认启用）与 `optional-skills/`（较重/专业，默认不启用）；
  另带网站文档中的 bundled skill 目录（creative / email / github / media / mlops / note-taking /
  productivity / research / smart-home / social-media / software-development / autonomous-ai-agents 等）。
- `skill_manage` 支持 create / edit / patch / write_file / remove_file / delete；
  `skill_provenance` 追踪来源（bundled / hub / agent / user），`skills_guard` 限制越权修改，
  `skills_ast_audit` 对 Agent 创建的代码类 skill 做 AST 审计。
- **Skill bundles**：`~/.hermes/skill-bundles/*.yaml`，一个斜杠命令同时加载 N 个 skill 全文；
  与同名 skill 冲突时 bundle 优先。
- **Skills Hub**：agentskills.io 开放标准兼容；`skills_sync` 支持个人/组织同步。
- `skill_preprocessing`：加载 skill 前预处理；`skill_commands` 解析 `/<skill-name>` 斜杠命令；
  `skill_bundles` 提供 `/bundle` 聚合。

### 1.6 工具系统与 Toolset

源码位置：`tools/registry.py`、`model_tools.py`、`toolsets.py`、`toolset_distributions.py`、
`tools/tool_search.py`、`tools/tool_result_storage.py`、`tools/tool_output_limits.py`、
`tools/budget_config.py`、`tools/schema_sanitizer.py`、`tools/managed_tool_gateway.py`。

已确认能力：

- 工具注册表自动发现：`tools/*.py` 各自 `registry.register()`，`model_tools.py` 汇总成模型 schema。
- Toolset 系统：`web`、`search`、`vision`、`image_gen`、`video_gen`、`bfl`、`computer_use`、
  `terminal`、`file`、`skills`、`browser`、`cronjob`、`tts`、`todo`、`memory`、`context_engine`、
  `session_search`、`project`、`clarify`、`code_execution`、`delegation`、`homeassistant`、`kanban`、
  `discord`、`yuanbao`、`feishu_doc`、`feishu_drive`、`spotify`、`debugging`、`safe`、`coding`、
  `hermes-cli`、`hermes-telegram`、`hermes-discord`、`hermes-api-server`、`hermes-acp`、`hermes-cron` 等。
- 按平台裁剪 schema：CLI、Telegram、Discord、WhatsApp、Slack、Signal、cron、webhook、ACP、API server
  各有独立 toolset；webhook toolset 刻意只保留 web_search / web_extract / vision_analyze / clarify，
  防第三方 webhook 内容 prompt injection。
- service-gated tool：只有配置了对应凭据/环境才出现在 schema（Home Assistant、computer_use、
  desktop GUI 工具等）；core tool 列表在 `toolsets.py::_HERMES_CORE_TOOLS` 可见。
- `tool_search` 支持工具搜索；`tool_result_storage` 保存大工具结果；`tool_output_limits` 控制输出窗口；
  `schema_sanitizer` 清洗 schema；`budget_config` 控制工具调用预算。
- `toolset_distributions.py` 用于数据生成：给不同场景按概率抽样 toolset（research / science /
  development / browser_tasks / terminal_tasks / mixed_tasks 等）。

### 1.7 执行环境：终端与远程后端

源码位置：`tools/terminal_tool.py`、`tools/read_terminal_tool.py`、`tools/close_terminal_tool.py`、
`tools/process_registry.py`、`tools/pty_bridge.py`、`tools/environments/*`。

已确认能力：

- 统一 `ExecutionEnvironment` 抽象，七个后端：`local`、`docker`、`ssh`、`singularity`、`modal`、
  `daytona`、`vercel_sandbox`；`file_sync.py` 负责本地/远端文件同步。
- 每次命令 spawn 新 `bash -c`，但保存 session snapshot（env/functions/aliases）并在下一条命令前恢复；
  CWD 通过 stdout 标记（远端）或临时文件（本地）持久化。
- 进程注册表 `process_registry` + `process` 工具管理后台进程；`read_terminal` / `close_terminal`
  支持桌面端只读终端标签页。
- 输出有界：head/tail 窗口 + spill 文件，命令被截断后可通过读回恢复，不会丢全量输出。
- Windows：`win_pty_bridge`、`windows_ssh_runtime`、`windows_hide_flags`、进程解码加固。

### 1.8 消息网关与多平台

源码位置：`gateway/*`、`gateway/platforms/*`、`plugins/platforms/*`。

已确认能力：

- 单一 gateway 进程支持多平台接入：telegram、discord、slack、whatsapp（cloud）、signal、
  matrix、mattermost、email、sms、dingtalk、wecom、weixin、feishu、qqbot、line、irc、ntfy、
  simplex、buzz（Nostr）、photon、raft、teams、google_chat、homeassistant、webhook、api_server、
  msgraph_webhook、bluebubbles、yuanbao。
- 网关核心：`turn_lease`（轮次租约）、`turn_context`、`delivery_ledger`、`delivery`（可靠投递）、
  `stream_dispatch` / `stream_consumer` / `stream_events`（流式事件）、`session_state` /
  `session_context` / `session_recovery`、`scale_to_zero`（闲置缩容）、`profile_routing`、
  `pairing`（配对审批）、`slash_commands` / `slash_access`、`hooks` / `builtin_hooks`。
- `ADDING_A_PLATFORM.md` 提供平台适配器规范；`channel_directory` 管理频道目录；
  `dead_targets` 管理失效目标；`mirror` 支持镜像会话。
- 多平台会话连续：同一 session 可在不同平台继续；profile 隔离通过 `HERMES_HOME` 注入。

### 1.9 定时任务、Webhook 与自动化

源码位置：`cron/jobs.py`、`cron/scheduler.py`、`cron/executions.py`、`cron/lifecycle_guard.py`、
`cron/blueprint_catalog.py`、`cron/suggestions.py`、`cron/suggestion_catalog.py`、
`hermes_cli/webhook.py`、`agent/outbound_webhooks.py`、`plugins/cron_providers/chronos/*`。

已确认能力：

- cron 支持 duration（`30m`）、自然语言（`every 2h`）、5 段 cron、ISO 一次性时间。
- 每个 job 支持：skills 加载、model/provider 覆盖、pre-run script（stdout 注入 prompt，
  `no_agent=True` 时脚本即整个任务）、context_from（把上一个 job 输出作为下一个 prompt）、
  workdir、多平台 delivery、`[SILENT]` 无变化不打扰模式。
- 硬化：3 分钟硬中断、catchup 窗口、grace 窗口、文件锁防双 tick、cron 会话默认 skip_memory。
- Webhook 订阅：GitHub 事件 / API 触发器，HMAC 鉴权，可注入事件字段到 prompt，可带 skills，
  可投递到任意平台。
- 自动化蓝图目录与建议目录：`blueprint_catalog.py` + `suggestions.py` / `suggestion_catalog.py`。
- 第三方 cron provider 插件：Chronos NAS 客户端。

### 1.10 多 Agent、Kanban 与协作

源码位置：`tools/delegate_tool.py`、`tools/async_delegation.py`、`tools/delegation_live_log.py`、
`agent/subagent_lifecycle.py`、`agent/delegation_context.py`、`tools/kanban_tools.py`、
`hermes_cli/kanban*.py`、`plugins/kanban/*`。

已确认能力：

- `delegate_task` 派生隔离子代理；`async_delegation` 支持并行流；`delegation_live_log` 实时日志；
  `subagent_lifecycle` 提供公共子代理生命周期 API；`/agents` 显示实时子任务状态。
- 子代理可执行代码：`execute_code` 支持“用 Python 脚本通过 RPC 调用工具”，把多步 pipeline 压成
  零上下文成本的轮次。
- **Kanban**：SQLite 持久化多 Agent 共享看板；dispatcher 默认在 gateway 内运行，周期 60s；
  支持 task claim、stale reclaim、依赖、attach、comment、block、heartbeat、failure_limit 自动 block；
  board 是硬隔离边界，tenant 是板内软命名空间；附带 web dashboard 与 systemd dispatcher。
- MoA（mixture-of-agents）：`/moa` 标记单轮为 MoA 启用，参考模型并行产出再聚合；隐私过滤器支持
  display/full 两种模式，对邮件/电话等 PII 做额外脱敏。

### 1.11 审批、澄清与交互

源码位置：`tools/approval.py`、`tools/write_approval.py`、`tools/slash_confirm.py`、
`tools/clarify_tool.py`、`tools/clarify_gateway.py`、`hermes_cli/approvals_suggest.py`、
`hermes_cli/approval_mode.py`、`hermes_cli/pairing.py`。

已确认能力：

- 智能审批：`hermes approvals suggest` 从历史挖掘 allowlist 建议；`approvals.smart_policy` 可自定义；
  连续拒绝触发熔断；`approval_mode` 支持不同模式；`write_approval` 写操作审批；`slash_confirm` 斜杠确认；
  `pairing` 桌面配对审批面。
- `clarify` 支持多选/开放式反问，`clarify_gateway` 跨表面把确认传回 Agent，而不是把“反问”丢给模型自由发挥。
- mid-turn redirect：用户中途发新指令，保留未完成工作并转向，不需要 stop 重开。
- 桌面端 GUI 工具：`open_preview`、`focus_pane`、`react_to_message`、`read_terminal`、
  `close_terminal` 均在 `HERMES_DESKTOP` 下才出现。

### 1.12 工具矩阵（按类别）

#### 搜索/研究

- `web_search` / `web_extract`（core）；provider 插件：tavily、serpapi、brave_free、ddgs、exa、
  searxng、parallel、firecrawl、xai。
- `x_search_tool`（X/Twitter 搜索）、`arxiv`、`session_search`。

#### 浏览器/计算机控制

- `browser_tool`（navigate / snapshot / click / type / scroll / back / press / get_images /
  vision / console / cdp / dialog）；插件 browser_use、browserbase、firecrawl。
- `computer_use_tool` + `cua_backend` + `vision_routing` + `permissions`（macOS/Windows/Linux 后台桌面控制，
  不抢用户鼠标键盘焦点）。

#### 文件/代码/终端

- `file_tools`（read_file / write_file / patch / search_files）、`file_operations`、`file_state`、
  `patch_parser`、`working_diff`、`file_sync`、`project_tools`、`binary_extensions`、`read_extract`。
- `code_execution_tool`（沙箱）、`terminal` / `process` / `read_terminal` / `close_terminal`、
  `daemon_pool`、`pty_bridge`。

#### 内容生成

- 图像：`image_generation_tool` + provider openai、openai-codex、fal、krea、deepinfra、openrouter、xai。
- 视频：`video_generation_tool` + fal/xai/deepinfra + `flux3_video_tool` + `xai_video_tools`。
- 语音：`tts_tool` / `tts_streaming` / `transcription_tools` / `voice_mode` / `wake_word` /
  `neutts_synth` / `audio_container`。
- 视觉：`vision_tools` + `vision_routing`（computer-use 内）。

#### 办公/平台

- `discord_tool` / `feishu_doc_tool` / `feishu_drive_tool` / `homeassistant_tool` /
  `kanban_tools` / `cronjob_tools` / `microsoft_graph_client` / `mcp_tool` /
  `yuanbao_tools` / `spotify` 插件 / `google_meet` 插件 / `teams_pipeline` 插件。

### 1.13 桌面 / Web / TUI / ACP 四端

源码位置：`apps/desktop/`、`apps/bootstrap-installer/`、`web/`、`ui-tui/`、`tui_gateway/`、
`acp_adapter/`、`hermes_cli/web_routers/*`。

已确认能力：

- 桌面 Electron 40：流式聊天、工具活动摘要、右侧预览（web/file/tool output）、文件浏览器、
  xterm 终端标签、项目 worktree、命令面板、quick entry、语音、主题/skin、更新、原生 OAuth、
  SSH 连接、桌面端 artifact 卡片。
- Web dashboard（React 19 + Vite + Tailwind 4）：Sessions、Config、Env、Channels、Models、
  Cron、Skills、Plugins、Profiles、Pairing、Webhooks、Logs、Files、Analytics、System、Docs、
  MCP、Chat；插件可注册 dashboard tab（kanban、achievements）。
- TUI（Ink React）：多行编辑、斜杠补全、历史、subagent tree、todo panel、流式 Markdown、
  widget SDK、battery/weather widget、主题。
- ACP adapter：VS Code / Zed / JetBrains 集成，编辑器内补全、编辑审批、工具调用。
- Bootstrap installer（Tauri）：桌面首次安装引导。

### 1.14 会话与状态存储

源码位置：`hermes_state.py`、`hermes_state_schema.py`、`hermes_state_search.py`、
`hermes_state_common.py`、`hermes_state_portability.py`、`hermes_cli/checkpoints.py`、
`hermes_cli/session_recovery.py`、`hermes_cli/session_recap.py`、`hermes_cli/session_export*.py`。

已确认能力：

- SQLite SessionDB，schema 声明式 reconcile（SCHEMA_SQL 即真源，缺列自动 ALTER ADD）。
- FTS5 全文索引 + trigram（子串）+ CJK bigram，消息内容 / 工具名 / 工具调用都可检索；
  增量 merge、deferred rebuild、`hermes sessions optimize-storage` 优化旧版 inline FTS。
- checkpoint 管理、session recovery、session recap、session export（html/md）、session listing、
  session filters、active sessions、session_model_usage 统计。
- `hermes_state_portability.py` 支持跨机器/目录迁移状态。

### 1.15 安全体系

源码位置：`tools/path_security.py`、`tools/url_safety.py`、`tools/threat_patterns.py`、
`tools/tirith_security.py`、`tools/osv_check.py`、`agent/file_safety.py`、`agent/ssl_guard.py`、
`agent/ssl_verify.py`、`agent/redact.py`、`agent/secret_scope.py`、`agent/credential_persistence.py`、
`hermes_cli/mcp_security.py`、`hermes_cli/security_audit*.py`、`hermes_cli/security_advisories.py`。

已确认能力：

- 路径安全（`path_security` / `file_safety`）、URL 安全（`url_safety`）、威胁模式（`threat_patterns`）、
  Tirith 安全检查（`tirith_security`）、依赖漏洞扫描（`osv_check`）。
- SSL 固定与校验（`ssl_guard` / `ssl_verify`）、凭据注入防火墙（credential persistence/secret scope 体系）、
  敏感信息脱敏（`redact`）。
- MCP 安全（OAuth manager、schema cache、stdio watchdog）、权限审计（security audit / advisories）。
- 审批门：危险命令 approval、配对审批、写文件 approval、Docker daemon-redirect 审批门。

### 1.16 可观测性与运维

源码位置：`agent/monitoring/*`、`plugins/observability/*`、`hermes_cli/dashboard_auth/*`、
`hermes_cli/observability/*`、`hermes_cli/doctor.py`、`hermes_cli/backup.py`、`hermes_cli/update*.py`。

已确认能力：

- OTLP exporter、gateway health、cron health、monitoring policy、redaction；插件 langfuse / nemo_relay。
- Dashboard auth 插件：basic、drain、nous、self_hosted；WS ticket / token auth / native flow。
- `hermes doctor`、`hermes backup`、`hermes update`、`hermes logs`、`hermes status`、
  `hermes debug`、`hermes dump`、`hermes insights`。

### 1.17 研究/训练与数据生成

源码位置：`batch_runner.py`、`mini_swe_runner.py`、`trajectory_compressor.py`、
`model_tools.py`、`toolset_distributions.py`、`datagen-config-examples/`、`scripts/`。

已确认能力：

- 批量轨迹生成（batch_runner）、轨迹压缩（trajectory_compressor）、Mini-SWE runner；
  toolset distribution 抽样用于生成多样化工具调用数据；datagen 配置示例。

### 1.18 其他特色

- `agent/pet/*`：桌面 PET 伙伴（生成/孵化/状态/渲染）。
- `plugins/hermes-achievements`：60+ 成就，基于真实会话历史解锁，三态（unlocked/discovered/secret），
  五级（Copper → Olympian），可生成分享卡。
- `plugins/disk-cleanup`：自动跟踪 Hermes 会话产生的临时文件，按类别阈值自动/确认清理。
- `plugins/google_meet`：会议机器人、实时转录/转写、音频桥。
- `plugins/teams_pipeline`：Teams 会议流水线。
- profiles：多个完全隔离实例；dashboard auth、gateway、skills、memory、sessions 全部按 profile 隔离。
- i18n：web 端 20+ 语言；`agent/i18n.py`。

---

## 2. 钰心AI 深度能力全景

> 以下按当前工作区源码盘点。标记说明：✅=有实现且有运行路径；◑=部分/有代码但未完全接线；✗=无。

### 2.1 平台入口与产品形态

| 能力 | 状态 | 落点 |
| --- | --- | --- |
| 首页助手（多轮、推荐问题、图片上传、语音输入、流式 SSE） | ✅ | `api/internal/service/assistant_agent_service.py`、`ui/src/views/pages/HomeView.vue` |
| 首页介绍缓存/预热 | ✅ | `_schedule_introduction_prewarm`、Redis 1h TTL |
| 应用工作台（草稿/发布/版本/对比/调试） | ✅ | `api/internal/service/app_config_service.py`、`app_debug_service.py`、`ui/src/views/space/apps/*` |
| 可视化工作流 | ✅ | `api/internal/service/dag_engine_service.py`、`workflow_service.py`、Vue Flow |
| 商店（App/Tool/MCP/Skill/Workflow） | ✅ | `ui/src/views/store/*`、`ui/src/views/admin/Store*` |
| OpenAPI 交付 + API Key | ✅ | `api/internal/service/openapi_service.py`、`api_key_service.py`、`ui/src/views/openapi/*` |
| WebApp 免登录入口（token + visitor_id） | ✅ | `api/internal/service/web_app_service.py`、`ui/src/utils/visitor.ts` |
| 微信公众号接入 | ✅ | `api/internal/service/wechat_service.py`、`api/internal/model/platform.py` |
| 桌面端 / TUI / CLI | ✗ | 平台是 Web，没有桌面/TUI/CLI |

### 2.2 编排控制板块（用户最初重点）

管理端路由：`GET/POST /admin/orchestration-flags`、`GET /admin/orchestration-release-check`、
`GET /admin/approval-insights`（见 `api/app/http/admin_routes_8.py`）。

13 个 Feature Flag 及真实生效点（`api/internal/service/orchestrator_service.py` 与
`assistant_agent_service.py`）：

| Flag | 默认 | 实际读取点 | 状态 |
| --- | --- | --- | --- |
| `ENABLE_ORCHESTRATOR` | true | `OrchestratorService.decide()`：关闭时直接返回 `_feature_disabled_decision()` | ✅ 生效 |
| `ENABLE_AGENT_METADATA_ROUTING` | true | 决定是否按 agent metadata 构造候选池子集 | ✅ 生效 |
| `ENABLE_TOOL_POOL_RETRIEVAL` | true | 决定是否走工具池检索 | ✅ 生效 |
| `ENABLE_COST_MODEL_ROUTING` | true | 决定是否应用成本策略选档位 | ✅ 生效 |
| `ENABLE_MODEL_ASSIGNMENT_POLICY` | true | 决定是否按档位策略分配模型 | ✅ 生效 |
| `ENABLE_MULTI_AGENT_EXECUTION` | true | 关闭时把 multi_agent 模式降级为 single_agent | ✅ 生效 |
| `ENABLE_RESULT_SYNTHESIZER` | false | 关闭时跳过 TaskPlanner 详细规划，用简化摘要 | ✅ 生效 |
| `ENABLE_ROUTING_LOGS` | true | 自动创建 pending routing log、生成 payload | ✅ 生效 |
| `ENABLE_AUTO_DEEP_THINKING` | true | 关闭时只保留关键词+手动开关触发深度思考 | ✅ 生效 |
| `ENABLE_POOL_GOVERNANCE_OBSERVE_ONLY` | true | `GovernanceModeResolver` 决定观察期不拦截 | ✅ 生效 |
| `ENABLE_POOL_GOVERNANCE_BLOCK_SENSITIVE` | false | 第二档：只拦敏感/危险工具 | ✅ 生效 |
| `ENABLE_POOL_GOVERNANCE_BLOCK_ALL` | false | 第三档：全量策略过滤 | ✅ 生效 |
| `ENABLE_CONDUCTOR` | false | `AssistantAgentService.chat()` 判断是否启用 LLM 指挥官 | ✅ 生效（默认关） |

相关服务：

- `api/internal/service/orchestration_feature_flag_service.py`：DB 兜底默认值、未知 code 返回 False。
- `api/internal/service/orchestration_release_check_service.py`：发布前检查高风险 flag 是否开启。
- `api/internal/service/routing_policy_change_service.py`：优化建议落地时同时改 flag。
- `ui/src/views/admin/OrchestrationFlagsView.vue` + `ui/src/services/admin-orchestration-flags.ts`。

### 2.3 执行链路

| 环节 | 状态 | 落点 |
| --- | --- | --- |
| 指挥官（LLM 决策） | ◑ 默认关 | `api/internal/service/conductor_service.py`，`ConductorPlan` 结构化输出 |
| 规则编排 | ✅ | `api/internal/service/orchestrator_service.py` |
| 任务分类/复杂度 | ✅ | `api/internal/service/task_classifier_service.py` |
| 执行模式选择 | ✅ | `api/internal/service/execution_mode_selector_service.py` |
| 任务规划 | ✅ | `api/internal/service/task_planner_service.py` |
| 池意图解析 | ✅ | `api/internal/service/pool_intent_resolver_service.py` |
| Agent 池子集/排序/过滤 | ✅ | `api/internal/service/agent_pool_service.py`、`agent_pool_aggregate_service.py` |
| 工具池子集/排序/过滤 | ✅ | `api/internal/service/tool_inventory_service.py`、`tool_selector_service.py` |
| 运行时工具挂载 | ✅ | `api/internal/service/runtime_tool_mount_service.py` |
| 执行协调器（single/parallel/sequential） | ✅ | `api/internal/service/execution_coordinator_service.py` |
| 子任务实时状态注册表 | ✅ 后端 + 前端已联动 | `api/internal/service/subtask_registry_service.py`（Redis 优先、内存兜底、TTL 1h）；`SingleAgentExecutor` / `MultiAgentExecutor` 以 `message_id` 作为 `request_id` 传入 Coordinator，`GET /subtasks/<request_id>` 可查快照并带超时/stall 元数据，`POST /subtasks/<request_id>/cancel` 可取消执行；SSE 下发 `subtask_started/running/completed`，首页助手 `SubtaskProgressPanel` 展示任务计划、状态、超时与停滞提示 |
| 多 Agent 执行器 | ✅ | `api/internal/service/executors/multi_agent_executor.py`：从 `task_plan_summary.agents` 构建 `TaskPlan`，经 `ExecutionCoordinatorService` 并行/串行执行，支持 concat/best_of 聚合，summarize 由 LLM 综合并失败回退拼接 |
| 单 Agent 执行器 | ✅ | `api/internal/service/executors/single_agent_executor.py`、`agent_task_executor.py` |
| Direct Answer 执行器 | ✅ | `api/internal/service/executors/direct_answer_executor.py` |
| 深度思考 Agent | ✅ | `api/internal/core/agent/agents/deep_thinking_agent.py`、`a2a_deep_thinking_agent.py` |
| 结果合成/质量检查 | ◑ | `result_synthesizer_service.py`、`result_quality_checker_service.py`（flag 默认关） |
| SSE 实时事件/计费 | ✅ | `single_agent_executor` 事件转发 + `BillingUsageAggregator` |

### 2.4 工具平台

内置工具（`api/internal/core/tools/builtin_tools/providers/`）：

- 搜索：google、duckduckgo、serpapi、tavily（含 tavily_answer）、wikipedia。
- 图像：dalle3、stability、siliconflow_kolors、qwen（文生图/编辑/2509）、atlascloud_gpt_image_2。
- 视频：atlascloud（Hailuo、Kling、Seedance、Vidu）。
- 学术/计算/新闻/天气：arxiv、wolframalpha、newsapi、openweathermap。
- 工具类：time、timezone_converter、gaode、baidu_translate、exchangerate、ipinfo、qrcode、urlshortener。
- 代码：github（仓库/Issue/用户）、code_execution_tool（默认关，需 `ENABLE_CODE_EXECUTION_TOOL=1`）。
- 宿主机自动化：codex_os（`run_os_task` / `os_file_task`）。
- Hermes 移植工具：web_tools（`web_search` / `web_extract`）、vision_tools（`vision_analyze`）、
  audio_tools（`tts_speak` / `audio_transcribe`）、todo_tool（`todo`）。

工具治理：

- `api/internal/core/agent/entities/tool_policy_entity.py`：hard_fail / high_risk / dangerous / image_result
  分级；`run_os_task`、`os_file_task`、send_email、execute_sql、transfer_funds 等默认高风险。
- `api/internal/service/admin_tool_governance_service.py` + `api/app/http/admin_routes_6.py`：
  `/admin/tool-governance` CRUD、批量风险、审计、统计。
- `api/internal/service/runtime_tool_governance_gate.py` + `governance_mode_resolver.py`：
  三阶段渐进启用（observe_only / block_sensitive / block_all）。
- `api/internal/service/tool_invocation_audit_service.py` + `GovernanceAuditLogger`：工具调用审计。
- `api/internal/service/mcp_service.py` / `mcp_runtime_adapter.py` / `mcp_import_service.py`：
  MCP provider 管理、预览、运行时挂载、schema 编译。
- `api/internal/service/api_tool_service.py`：OpenAPI 导入 URL/文件、校验、生成图标。

### 2.5 Agent 内核

- `FunctionCallAgent`：工具调用主循环、`tool_confirmation` 等待、30 分钟免重复授权、
  `_tools_node` 生成确认卡片、V4A 补丁授权摘要人话化。
- `ReACTAgent`：思考/行动/观察循环；`DeepThinkingAgent`：子任务拆解 + 深度思考阶段事件。
- `AgentQueueManager` + Redis stop flag：SSE 断开/用户 stop 时终止后台 Agent。
- `checkpointer.py`：图检查点（LangGraph）。
- `api/internal/core/agent/adapters/hermes/`：v4a_patch、redact、outbound_webhook、midturn_redirect、
  approval_mining、a2a_protocol、a2a_client。

### 2.6 知识库与检索

- `knowledge_base_service.py` / `knowledge_indexing_service.py` / `knowledge_vector_service.py` /
  `faiss_service.py` / `rerank_service.py` / `retrieval_service.py` / `scoped_knowledge_service.py`：
  数据集、文档、切片、向量、重排、混合检索、命中测试。
- 双层：系统级知识库（注入助手 system prompt）+ 用户个人知识库。
- 外部数据源：github、notion、lark、local_folder connector（`api/internal/service/connectors/`），
  授权/同步/删除（`/external-data-sources*`）。
- 前端：`ui/src/views/space/datasets/*`、HitTestingModal。

### 2.7 记忆系统

`api/internal/service/memory/`（30+ 文件）：

- 写入：SalienceScorer、ExplicitStatementDetector、EntityExtractor、EntityResolver、LedgerWriter、
  MemoryWriteService、WriteTimeConflictResolver、MemoryGovernor。
- 存储/检索：MemoryRetriever、HebbianDecay、FunnelCompressor、DigestManager、ColdStorageManager、
  SpreadActivation、RepresentationRepulsion、DegradationManager。
- 巩固：ConsolidationEngine、ConflictDetector、PolicyRouter、SkillEmergence、PostExecutionHook、
  SkillDetailTool。
- 前端记忆图：`ui/src/views/settings/MemoryView.vue`、`ui/src/components/memory/*`。

### 2.8 Skills

- `api/internal/service/skill_service.py` / `skill_import_service.py`：包管理、版本、启用/禁用、导入。
- 导入来源：外部目录 / 商店目录；前端 `ImportExternalSkillModal`、`ImportCatalogSkillModal`。
- App 可绑定 Skills（`SkillsAbilityItem`）；管理端 `AdminSkillsView`。

### 2.9 工作流

- `dag_engine_service.py` + `workflow_service.py` + `workflow_run_service.py`：DAG 执行、运行记录、
  节点执行记录、回放。
- 节点：Start、End、LLM、Tool、DatasetRetrieval、Code、HttpRequest、IfElse、TemplateTransform、
  TextProcessor、VariableAssigner、ParameterExtractor。
- 管理端：草稿图、发布、版本、回滚、批量发布/下架、导入/导出、调试；前端 Vue Flow。

### 2.10 应用与能力绑定

- `app.py` 模型：App、AppAssignment、AppConfig、AppConfigVersion。
- App 能力绑定（`ui/src/views/space/apps/components/abilities/*`）：Tools、MCP、Skills、
  AgentBindings、Workflow、Datasets、Opening、SpeechToText、TextToSpeech、LongTermMemory、
  SuggestedAfterAnswer、ReviewConfig。
- 管理端 App 详情：调试、分析、版本对比、提示词对比、发布/下架、WebApp token、微信配置、商店上下架。

### 2.11 计费与会员

- Plan / PlanEntitlement / Membership / CreditAccount / CreditTransaction / RedeemCode。
- `billing_metering_service.py`：SSE 计费事件（started/delta/summary/final/cancelled）；
  `credit_service.py`：幂等扣费；`cost_stats_service.py`：管理端成本统计；
  `cost_policy_service.py`：模型档位与成本策略；`admin_billing_plan_service.py`：套餐管理。
- 前端：MembershipView、BillingView、CostDashboardView、CostStrategyView。

### 2.12 管理后台与 RBAC

- `admin_user_service.py`、`admin_rbac_service.py`、`admin.py` 模型（AdminUser/AdminSession/Role/
  Permission/AdminUserRole/RolePermission/AuditLog）。
- 8 个 admin routes 文件，覆盖 App、Workflow、Knowledge、Tools、MCP、Skills、Users、Roles、Billing、
  Storage、RecycleBin、AgentPool、SubPool、Models、ModelProviders、RoutingLogs、RoutingQuality、
  AuditLogs、OrchestrationFlags、ReleaseCheck、ApprovalInsights、Showcase、Store、OpenAPI、Schedules。

### 2.13 定时任务

- `schedule_task_service.py` + `schedule_intent_parser.py` + `schedule_execution_service.py`：
  自然语言转定时任务、建议/确认/驳回、run-now、运行历史。
- Celery beat + `api/internal/task/schedule_tasks.py`。

### 2.14 存储与文件

- `storage/`：local / MinIO / 阿里云 OSS / RuntimeStorageProxy；配置切换、迁移、文件删除审计。
- kkFileView 在线预览；上传文件模型 + `upload_file_service.py`。
- 回收站：`recycle_bin_service.py` + `/admin/recycle-bin`。

### 2.15 A2A 与外部协作

- 标准 A2A v1.0：`a2a_protocol.py`、`a2a_gateway_service.py`、`a2a_routes.py`；
  Agent Card（`/.well-known/agent-card.json`）、JSON-RPC `message/send`、`tasks/get`、
  `tasks/cancel`、SSE `message/stream`、可选 Bearer token。
- 出站客户端：`a2a_client.py` + `a2a_send_message` 工具，可调用外部 A2A 对端。
- 平台内公共 Agent 路由：`public_agent_a2a_service.py` + `public_agent_registry_service.py`。

### 2.16 工具授权与确认交互

- `tool_confirmation.py` 模型 + `tool_confirmation_service.py`：创建/确认/取消/redirect。
- `/tool-confirmations` CRUD、`/confirm`、`/cancel`、`/redirect`（`knowledge_mcp_routes.py`）。
- 前端：`ToolConfirmationCard.vue` 人话化授权摘要、`IndexView/HomeView` 确认后轮询续跑。
- 匿名访客：`visitor.ts` + WebApp `visitor_id` 绑定，修复“确认失败/会话中断”。
- HMAC 出站 webhook：`outbound_webhook.py`，确认/取消事件推送，重试 + 幂等 ID。
- 审批洞察：`approval_mining.py` + `approval_insights_service.py` + `/admin/approval-insights`。

### 2.17 新增“干活”工具（Hermes 移植）

| 工具 | 状态 | 落点 |
| --- | --- | --- |
| `run_os_task` | ✅ preview → approval_token → apply | `codex_os/run_os_task.py` + `api/scripts/os_automation_worker.py` |
| `os_file_task` | ✅ 安全根目录 + V4A 补丁 | `codex_os/os_file_task.py` + worker `/file` |
| `web_search` | ✅ Tavily→SerpAPI→DDG 降级 | `web_tools/web_search.py` |
| `web_extract` | ✅ SSRF 防护 + 大小限制 | `web_tools/web_extract.py` |
| `vision_analyze` | ✅ 平台视觉模型，URL/data URI | `vision_tools/vision_analyze.py` |
| `tts_speak` / `audio_transcribe` | ✅ SiliconFlow 底座，支持 language/provider/model | `audio_tools/audio_tools.py` |
| IM 语音笔记 | ◑ 微信闭环；LINE/WhatsApp/飞书/钉钉 webhook 事件接入；QQ 语音转写适配器（Bot 网关已移除）；Photon 为 Hermes 私有协议 | `im_voice_service.py` + `im_voice_routes.py` + `wechat_service.py` |
| `execute_code` | ✅ 默认关，需 E2B 凭证 + 高风险确认 | `code_execution_tool/execute_code.py`；支持 `tool_calls` 预取已挂载平台工具结果并以 `TOOL_RESULTS_JSON` 注入沙箱 |
| `todo` | ✅ Redis 优先、内存兜底 | `todo_tool/todo.py` |
| `a2a_send_message` | ✅ | `a2a_client.py` 工具 |

### 2.18 可观测性

- 路由日志：`routing_log_service.py`、`routing_event_logger.py`、`routing_log_redaction_service.py`、
  `routing_log_retention_service.py`；管理端 `/admin/routing-logs`。
- 路由质量：`routing_quality_feedback_service.py`、`routing_quality_metrics_service.py`、
  `routing_optimization_suggestion_service.py`、`routing_policy_change_service.py`；
  `/admin/routing-quality/*`。
- 成本：`cost_stats_service.py`、`/admin/cost-stats/*`。
- 审计：`audit_log_service.py`、`/admin/audit-logs`；工具治理审计 `/admin/tool-governance/audit`。
- 通知：Socket.IO websocket + polling（`notification_service.py`、`use-agent-notification-*`）。

### 2.19 基础设施与部署

- `docker/docker-compose.yaml`：nginx + ui + api + celery + celery-beat + redis + pgvector + neo4j
  + minio + kkfileview。
- Quart + uvicorn、SQLAlchemy + Alembic（130+ 迁移）、Celery、Redis、PostgreSQL、Neo4j、MinIO。

---

## 3. 双向逐项对比矩阵

| 能力 | Hermes v0.20 | 钰心AI | 差距性质 |
| --- | --- | --- | --- |
| 自研 Agent 主循环 | ✅ conversation_loop / turn lifecycle | ◑ LangGraph + FunctionCallAgent/ReACT | 架构不同，非优劣；钰心AI 更依赖 LangGraph 生态 |
| 模型 provider | ✅ 30+ 插件 provider | ✅ OpenAI/Atlas/DeepSeek/Grok/Google/Moonshot/Tongyi/Wenxin/Ollama/Zhipu 等 | 钰心AI 管理端模型池/Key 池更平台化 |
| 模型路由/降级/成本档位 | ✅ credential pool + fallback + billing | ✅ ModelGateway + FallbackManager + TierPolicy + CostPolicy | 双强 |
| 上下文压缩 | ✅ 逐轮微压缩 + 尾巴保护 + ghost-skill 防御 | ✅ TokenBufferMemory + ContextCompressor，含 12k 字符工具结果兜底截断、最近 3 条用户消息硬保护、逐轮摊销压缩、已加载技能防幽灵重复注入 | 已对齐 |
| 记忆 | ✅ 8 provider + Agent-curated + 学习图 + Curator | ✅ System1/2 + Ledger + 巩固 + 技能涌现 | 钰心AI 分层完整，Hermes 自主生命周期更成熟 |
| 技能涌现/维护 | ✅ 自动创建 + 自改进 + Curator 归档 | ◑ SkillEmergence + 技能商店，无 Curator 生命周期 | 需补技能生命周期治理 |
| 会话搜索 | ✅ FTS5 + trigram + CJK | ✅ ConversationSearch（PG/Redis） | 双有，机制不同 |
| 子代理 | ✅ delegate + /agents 实时状态 + 可执行代码 | ✅ `MultiAgentExecutor` + Redis 化 registry + `/subtasks` 查询/取消 + SSE 实时事件 + 首页面板 + `execute_code` 工具 RPC 桥 | 已对齐 |
| 审批 | ✅ 智能审批 + 熔断 + 配对 + 跨面 | ✅ 确认卡片 + 30 分钟免重复 + approval-mining 建议 + `SmartApprovalPolicyService` 运行时自动放行 + Docker/podman daemon 危险命令审批门 | 桌面配对审批面与策略学习闭环仍待增强 |
| mid-turn redirect | ✅ 任意时刻 | ✅ 请求级 redirect：`POST /subtasks/<request_id>/redirect` + `_llm_node` 轮前注入 | 已对齐；同步工具执行期需等待该步结束 |
| 确认后续跑/断点 | ✅ 同一轮继续 | ✅ WebApp 后台任务落库 + 确认后轮询 | 已修复核心断点；仍缺完整恢复 UI 语义 |
| 终端执行 | ✅ 7 类后端 + PTY + 后台进程 | ◑ 宿主 worker 调 Codex，平台无原生终端 | 平台形态差异 |
| 文件工具 | ✅ file/patch/diff/write 校验 | ✅ 文件存储 + V4A 补丁 + kkfileview | 双有 |
| 浏览器自动化 | ✅ 13 个 browser 工具 + 云浏览器插件 | ◑ `browser_action`（navigate/snapshot/click/type/scroll/back）+ Playwright worker，默认关闭、高风险审批 | 需部署 browser worker |
| 计算机控制 | ✅ computer-use + CUA | ◑ `computer_action`（move/click/scroll/type/press/hotkey/screenshot）+ pyautogui worker，默认关闭、高风险审批 | 需桌面端集成与产品决策 |
| 网页搜索 | ✅ 9 provider | ✅ 4 provider + 统一 web_search 降级 | 双有 |
| 网页提取 | ✅ web_extract | ✅ web_extract（SSRF 防护） | 双有 |
| 图像生成 | ✅ 7 provider | ✅ dalle/stability/siliconflow/qwen/atlascloud | 双有 |
| 视频生成 | ✅ fal/xai/deepinfra + FLUX3 | ✅ atlascloud（Hailuo/Kling/Seedance/Vidu） | 双有 |
| 语音 | ✅ 流式 TTS + barge-in + 唤醒词 + 多平台语音 | ◑ STT/TTS 工具（language/provider/model 可选）+ 分句播放 + 打断播放 + 连续语音模式（自动发送/自动朗读）+ 微信/LINE/WhatsApp/飞书/钉钉语音事件闭环 + 四表面 stop（含 A2A tasks/cancel） | 需 Photon 私有协议映射；设备端唤醒词以连续语音模式替代（Web 形态） |
| 视觉理解 | ✅ vision + 路由 | ✅ vision_analyze 工具 | 双有 |
| 代码执行 | ✅ 沙箱 execute_code + RPC | ✅ execute_code（默认关 + 高风险确认 + tool_calls 预取 RPC 桥） | 需配置沙箱凭证 |
| MCP | ✅ 懒加载 + OAuth + catalog | ✅ MCP 商店 + 运行时挂载 | 双有 |
| A2A | ✅ A2A v1.0 插件 | ✅ A2A v1.0 网关（message/send、tasks/get、tasks/cancel、message/stream）+ 出站客户端 | 已对齐 |
| 消息平台 | ✅ 28+ 适配器 | ◑ 微信完整接入 + IM 语音笔记（LINE/WhatsApp/飞书/钉钉 webhook） | 语音链路已通，完整消息/会话按合规逐步接入 |
| 定时任务 | ✅ cron + webhook + 蓝图 + 脚本注入 | ✅ 自然语言定时任务 + Celery | 钰心AI 无“GitHub/API 触发 + 多平台投递” |
| 多 Agent 看板 | ✅ Kanban 板/调度器/fleet | ✗（工作流图替代） | 形态不同 |
| Webhook | ✅ HMAC 出站 + 入站订阅 | ✅ HMAC 出站（确认/取消事件） | 入站触发未做 |
| 桌面端 | ✅ Electron 40 + 插件 SDK + 预览 | ◑ Electron 壳（`desktop/`）+ 本地 workers + 唤醒词 worker | 壳已封装，构建发布待验证 |
| TUI | ✅ Ink TUI | ✗ | 平台形态差异 |
| ACP 编辑器集成 | ✅ | ✗ | 平台形态差异 |
| Web dashboard | ✅ React（单机管理） | ✅ Vue 3 管理端 33+ 页（多租户治理） | 钰心AI 管理面更强 |
| 知识库/RAG | ◑ 云记忆 + 文件引用 | ✅ 双层知识库 + 向量 + 重排 + 混合检索 | 钰心AI 更强 |
| 可视化工作流 | ✗ | ✅ DAG + Vue Flow | 钰心AI 独有 |
| OpenAPI 交付 | ✅ OpenAI 兼容 API server | ✅ 自定义 OpenAPI chat + API Key | 双有，协议不同 |
| 多租户/RBAC | ✗ 单用户 profile | ✅ 账号/角色/权限/审计/资源分配 | 钰心AI 独有 |
| 对象存储/文件预览 | ◑ 本地文件 | ✅ MinIO/OSS/kkFileView/存储迁移 | 钰心AI 更强 |
| 会话导出/检查点 | ✅ export md/html + checkpoint | ✗ 无导出/断点恢复 UI | 可借鉴 |
| 可观测性 | ✅ OTLP + Langfuse + Nemo Relay | ✅ 路由日志/质量/成本/审计 | 钰心AI 缺标准导出 |
| 计费 | ✅ 订阅/credits/usage | ✅ 套餐/会员/积分/幂等扣费/成本策略 | 双强 |
| 成就/PET/皮肤 | ✅ achievements + PET + themes | ✗ | 趣味性场景，非核心 |
| 研究/数据生成 | ✅ batch + trajectory compression | ✗ | 训练向，非核心 |

---

## 4. 主要差距与建议（按优先级）

1. **技能生命周期治理（P0）**：Hermes 的 Curator + skill_usage + learning graph 是“学习闭环”的落地；
   钰心AI 已有 SkillEmergence，但缺使用统计、自动归档、可恢复归档与学习图展示。
2. **子任务实时状态（P0，已完成）**：`SubtaskRegistryService` + `SingleAgentExecutor` /
   `MultiAgentExecutor` + `GET /subtasks/<request_id>` + SSE `subtask_started/running/completed` +
   首页 `SubtaskProgressPanel` 已闭环，registry 已升级为 Redis 优先、内存兜底，并补齐超时/stall
   元数据（`timeout_seconds` / `last_activity_at` / `timed_out` / `stall_warning`）与 `POST /subtasks/<request_id>/cancel`
   取消 API；`execute_code` 已增加 tool_calls 预取 RPC 桥。
3. **通用授权阶段机（P0）**：把“先授权 → 再只读扫描 → 再反问范围 → 再执行”做成平台级能力，
   不只修 `run_os_task` 单场景。
4. **工具自恢复（P1）**：V4A 补丁诊断已就绪，但未把“已应用/空白差异/落盘校验”结果喂回 Agent 提示。
5. **审批策略运行时化（P1，已完成）**：`approval_mining` dry-run + `SmartApprovalPolicyService`
   （`tool_governance_policy.require_confirmation=false` 自动放行，危险工具永不自动放行）。
6. **入站 webhook / 事件触发（P2）**：当前只有出站推送；Hermes 的 GitHub/API 触发 + 多平台投递可做平台化“事件触发任务”。
7. **浏览器自动化与计算机控制（P2）**：多租户下高风险，建议先从受控云浏览器/受限沙箱接入。
8. **完整 mid-turn redirect（P2，已落地请求级）**：`POST /subtasks/<request_id>/redirect` 按 request_id
   暂存纠正，`_llm_node` 每轮前注入并重新规划；剩余是同步工具执行期的即时中断。

---

## 5. 来源

- Hermes 源码：`NousResearch/hermes-agent` tag `v2026.8.3`（本地稀疏克隆 `%TEMP%\hermes-agent`）。
- Hermes README / AGENTS.md：`README.md`、`AGENTS.md`。
- Hermes 发布说明：`https://github.com/NousResearch/hermes-agent/releases/tag/v2026.8.3`。
- 钰心AI 源码：`api/`、`ui/`、`docker/`、`docs/prd/`。
- 既有报告：`docs/research/hermes-agent-v0-20-comparison.md`、`docs/research/hermes-v0.20-alignment-report.md`、
  `docs/research/hermes-v0.20-e2e-verification.md`。
