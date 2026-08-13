# Hermes Agent v0.20 调研与钰心AI 能力对比

> 调研日期：2026-08-13
> 调研对象：Nous Research 的 `hermes-agent`（不是 Cosmos Hermes）
> 来源分级：GitHub API / 官方 Release Notes / 官方博客为第一方来源；其余为二手整理

> **v2 修订（2026-08-13）**：本文只保留结论与矩阵；逐子系统、源码落点和运行状态的完整深度盘点见
> `docs/research/hermes-v0.20-capability-deep-dive.md`。本文同时修正了几处已过时状态：
> 标准 A2A v1.0、HMAC 出站 webhook、审批历史挖掘已落地，不再属于“不存在的能力”。

## 1. 开源结论

**Hermes Agent v0.20.0（Herald Release）已经开源，且当前就是最新正式版。**

- 仓库：`NousResearch/hermes-agent`，默认分支 `main`
- 版本：`v0.20.0`，GitHub tag `v2026.8.3`
- 发布时间：2026-08-03T16:57:52Z（Release Notes 标注 2026-08-03）
- 许可证：**MIT**（GitHub API `license.spdx_id = MIT`；官方博客自托管路线明确标注 MIT licensed）
- 仓库规模（调研当天）：约 229.5k stars / 45.3k forks / 31.5k open issues
- 最近代码推送：2026-08-12，仍处于活跃开发
- 发布形态：GitHub Release 页面提供完整 release body（约 5.8 万字符），无独立二进制资产，安装走官方 shell installer / Docker / Nix

> 重要：GitHub 上存在其他同名项目（如 Cosmos Hermes），本报告所有结论只针对 Nous Research 的 Hermes Agent。

## 2. 一句话定位差异

Hermes Agent 是**单用户、自托管、面向个人工作站的编码/自动化 Agent**，主战场是 CLI、桌面 App 和 IM 网关（WhatsApp/Feishu/DingTalk/QQ/微信等）；钰心AI 是**多租户、管理员治理、面向终端用户的通用 Agent 调度平台**，主战场是 Web 管理端 + 首页助手 + 公共 Agent 路由。

两者不是同类产品，不能“整体对标”。真正值得对比的是**执行编排、工具授权、审批交互、Agent 间通信和可观测性**这几层能力；语音、桌面 App、IM 网关这些属于 Hermes 的场景能力，钰心AI 目前只有 Web 语音输入/播报的雏形，不在同一量级。

## 3. v0.20 主要功能（第一方来源）

### 3.1 语音与免手操作

- 流式分句 TTS，边说边生成
- barge-in：用户说话即打断，模型感知到用户插入
- 设备端唤醒词 + 多 profile 语音路由 + 全表面“stop”
- WhatsApp / Feishu / DingTalk / LINE / QQ / Photon / Weixin 语音笔记接入
- STT/TTS 独立工具分类、统一语言解析、gpt-transcribe 支持

### 3.2 Agent 架构与执行

- **A2A v1.0 插件**：Agent 间发现、对话、被驱动；与 MCP 明确分层（MCP=工具，A2A=Agent 对等通信）
- **Mid-turn redirects**：用户中途纠正当前轮，保留未完成工作，Agent 按新指令转向，不用 stop 重开
- **智能审批（Smart Approvals）**：
  - `hermes approvals suggest` 从审批历史挖掘可安全放行的 allowlist 建议
  - 审批策略可被操作者自定义（`approvals.smart_policy`）
  - 连续拒绝触发熔断，阻止同一坏循环反复请求审批
  - Docker/podman daemon-redirect 新增审批门
- 工具自恢复：终端截断可读回、patch 已应用检测、write_file 落盘校验、搜索零结果探测等
- 上下文压缩：工具结果主动裁剪、逐轮微压缩、保证 N 条用户消息尾巴、ghost-skill 防御
- 子代理委派：超时/stall 元数据、`/agents` 实时子任务状态、子代理可执行代码、公共子代理生命周期 API

### 3.3 集成与安全

- **签名出站 Webhook**（HMAC）：session 活动、turn 完成、工具事件推送到外部 HTTP 端点
- 桌面 App 平台化：Artifacts 版本卡片 + 沙箱预览 + 插件 SDK + 全局快捷输入 + 多窗口
- 多平台网关：Buzz（Nostr）、Relay 四阶段 parity、HSP 个人/组织技能同步、OTLP 可观测性导出
- CLI：`!` shell 直执行、`/init` 生成 AGENTS.md、`/diff`、`/context`、`/focus`、`hermes import-agent` 从 Claude Code / Codex 迁移
- grounded-citations：可核实引用 + 事实核查
- 安全加固：SSRF-safe fetch、DNS pin、凭证注入防火墙、Windows 子进程解码加固、CJK FTS

### 3.4 核心 Agent 引擎（v2026.8.3 仓库级盘点）

以下按 Hermes 仓库实际模块分类，不只看 release 摘要：

| 模块 | Hermes v0.20 实际能力 |
| --- | --- |
| Agent 主循环 | 自研 `conversation_loop` / `turn_context` / `turn_runner`；TurnContext 与 TurnRunner 分离；turn 级重试状态、turn summary、turn finalizer |
| 模型接入 | `anthropic_adapter` / `gemini_native_adapter` / `bedrock_adapter` / `vertex_adapter` / `azure_identity_adapter` / `codex_responses_adapter` / `copilot_acp_client` / `lmstudio_reasoning` / `openrouter_client` / `xai_http`，模型目录 + provider catalog |
| 记忆 | `memory_manager` / `memory_provider` 抽象，插件式 Holographic / mem0 / supermemory / honcho / openviking / retaindb / byterover / hindsight |
| 上下文 | `context_engine` / `context_compressor` / `conversation_compression` / `prompt_caching` / `context_breakdown` / `manual_compression_feedback` |
| 子代理 | `async_delegation` / `subagent_lifecycle` / `delegation_context` / `delegation_live_log` / 公共子代理生命周期 API |
| 审批 | `approval_mode` / `approvals_suggest` / `write_approval` / `slash_confirm` / `pairing`，跨表面确认 |
| 安全 | `path_security` / `file_safety` / `ssl_guard` / `url_safety` / `threat_patterns` / `tirith_security` / `redact` / `credential_sources` / `secret_scope` |
| 学习/技能 | `learn_prompt` / `learning_graph` / `learning_mutations` / `curator` / `skill_manager_tool` / `skill_provenance` / `skills_guard` / `skills_hub` |
| 输出 | `think_scrubber`（思考区清洗）/ `message_sanitization` / `trajectory` / `verification_evidence` / `bounded_response` |
| 计费 | `billing_usage` / `billing_view` / `credits_tracker` / `usage_pricing` / `nous_rate_guard` / `subscription_view` |
| 会话 | `session_activity` / `session_recovery` / `session_export`（html/md）/ `checkpoints` / `session_recap` / `active_sessions` |

### 3.5 工具清单（v2026.8.3，按模块名）

终端/进程：`terminal_tool` / `read_terminal_tool` / `close_terminal_tool` / `process_registry` / `pty_bridge` / `docker` / `daemon_pool`

文件/代码：`file_tools` / `file_operations` / `file_sync` / `file_state` / `patch_parser` / `working_diff` / `code_execution_tool` / `project_tools`

浏览器/网页：`browser_tool` / `browser_cdp_tool` / `browser_camofox` / `browser_supervisor` / `browser_dialog_tool` / `web_tools` / `website_policy`

搜索/研究：`x_search_tool` / `firecrawl`（插件）/ `exa`（插件）/ `ddgs`（插件）/ `tavily`（插件）/ `searxng`（插件）/ `parallel`（插件）/ `brave_free`（插件）/ `arxiv`

委派/协作：`delegate_tool` / `async_delegation` / `clarify_tool` / `clarify_gateway`（多选确认）/ `send_message_tool` / `react_to_message_tool`

记忆/技能：`memory_tool` / `skill_manager_tool` / `skills_tool` / `skills_sync` / `session_search_tool` / `todo_tool`

语音/视觉/生成：`voice_mode` / `tts_tool` / `tts_streaming` / `wake_word` / `transcription_tools` / `vision_tools` / `vision_routing` / `image_generation_tool` / `video_generation_tool` / `flux3_video_tool` / `fal_common` / `xai_video_tools`

平台/办公：`discord_tool` / `feishu_doc_tool` / `feishu_drive_tool` / `homeassistant_tool` / `kanban_tools` / `cronjob_tools` / `microsoft_graph_client` / `mcp_tool` / `computer_use_tool` / `cua_backend` / `yuanbao_tools`

### 3.6 平台适配器（gateway/platforms + plugins/platforms）

**消息/IM**：telegram、discord、slack、whatsapp（cloud）、wecom、weixin、dingtalk、feishu、qqbot、line、matrix、mattermost、google_chat、irc、ntfy、simplex、buzz（Nostr）、photon、raft、email、sms、teams、homeassistant、api_server、webhook、msgraph_webhook、bluebubbles、signal、yuanbao

**A2A**：`plugins/platforms/a2a`（A2A v1.0 标准协议）

### 3.7 CLI 子命令（hermes_cli/subcommands）

`acp`、`approvals`、`auth`、`backup`、`claw`、`config`、`console`、`cron`、`dashboard`、`debug`、`doctor`、`dump`、`gateway`、`gui`、`hooks`、`import_agent`、`import_cmd`、`insights`、`login/logout`、`logs`、`mcp`、`memory`、`model`、`monitoring`、`pairing`、`plugins`、`profile`、`prompt_size`、`security`、`setup`、`skills`、`skin`、`slack`、`status`、`sync`、`tools`、`uninstall`、`update`、`version`、`webhook`、`whatsapp`

另有：`!` shell 直执行、`/init`、`/diff`、`/context`、`/focus`、`/goal`、Ctrl+S prompt stash、mid-turn redirect、多选 clarify、跨表面 theme、session export、kanban、moa（mixture-of-agents）等。

### 3.8 插件体系（plugins/，19 个顶层插件）

- 模型提供商：anthropic / gemini / bedrock / azure-foundry / vertex / openai-codex / copilot / copilot-acp / deepseek / kimi-coding / minimax / stepfun / qwen-oauth / xai / zai / xiaomi / nvidia / novita / fireworks / deepinfra / huggingface / arcee / upstage / openrouter / nous / custom / ai-gateway / alibaba / alibaba-coding-plan / gmi / kilocode / ollama-cloud / opencode-zen
- 记忆：holographic / mem0 / supermemory / honcho / openviking / retaindb / byterover / hindsight
- 图像生成：openai / openai-codex / fal / krea / deepinfra / openrouter / xai
- 视频生成：fal / xai / deepinfra
- 浏览器：browser_use / browserbase / firecrawl
- 搜索：brave_free / ddgs / exa / firecrawl / parallel / searxng / tavily / xai
- 平台：a2a / buzz / dingtalk / discord / email / feishu / google_chat / homeassistant / irc / line / matrix / mattermost / ntfy / photon / raft / simplex / slack / sms / teams / telegram / wecom / whatsapp
- 其他：kanban、context_engine、cron_providers、dashboard_auth（basic/drain/nous/self_hosted）、observability（langfuse / nemo_relay）、security-guidance、spotify、teams_pipeline、disk-cleanup、google_meet、hermes-achievements、web

### 3.9 技能库（skills/，14 个分类）

apple、autonomous-ai-agents、creative、email、github、media、mlops、note-taking、productivity、research、smart-home、social-media、software-development、index-cache

## 4. 钰心AI 现状盘点

### 4.1 已实现并与 Hermes 有可比性的能力

| 能力 | 钰心AI 现状 |
| --- | --- |
| 编排决策 | 指挥官 `ConductorService` + 执行模式枚举（direct_answer / single_agent / single_agent_with_tools / multi_agent_parallel / multi_agent_sequential / deep_thinking / reject_or_confirm） |
| 编排开关 | 管理端 `OrchestrationFlagsView` + `OrchestrationFeatureFlagService`，13 个运行时 flag（`ENABLE_ORCHESTRATOR` 到 `ENABLE_CONDUCTOR`），支持灰度/回退 |
| 高风险工具授权 | `FunctionCallAgent._tools_node` 创建 `tool_confirmation` 记录，前端 `ToolConfirmationCard` 展示，Agent 轮询等待确认；授权后同一轮继续 |
| 授权状态记忆 | `AgentState.authorized_tools` + `_is_tool_authorized`（30 分钟内近期确认免重复授权） |
| OS 自动化 | `run_os_task`：Codex preview → 一次性 `approval_token` → apply，`ToolPolicy.high_risk_tool_names` 强制走确认链路 |
| 工具治理 | `ToolPolicy` 危险/高风险/硬失败三级，`admin_tool_governance` 后台策略 |
| 成本 | `billing_started/delta/summary/final/cancelled` SSE 事件、`CostDashboardView` 管理端统计 |
| A2A | 标准 A2A v1.0 网关（Agent Card / message/send / tasks/get / message/stream）+ `PublicAgentA2AService` 公共 Agent 路由 + `a2a_send_message` 出站工具 |
| 记忆系统 | System 1/2 双路、Ledger、Hebbian 衰减、FunnelCompressor、Agent-Curated 记忆（`memory_add/replace/remove`）、Post-Execution Nudge |
| 上下文压缩 | `TokenBufferMemory._smart_compress` + `context_compression/compressor.py` |
| 可观测性 | 路由决策/拒绝事件、计费事件 SSE 推送，管理端 `RoutingLogsView` + `CostDashboardView` + `AuditLogsView`；细粒度“候选/过滤原因”链路仍属架构设计，部分未实现 |
| 输出产物 | 图片/文件 artifact 提取、Web 端展示，无沙箱实时预览 |
| 语音 | Web 端 `speech_to_text` / `text_to_speech` 配置 + 语音按钮，非流式对话式语音 |

### 4.1.1 钰心AI 仓库级能力清单（实际代码，非 PRD 设计）

**服务层（api/internal/service，138 个 .py）**

- 编排：`ConductorService`、`ExecutionCoordinatorService`、`ResultSynthesizerService`、`RuntimeToolMountService`、`RuntimeToolGovernanceGate`、`GovernanceModeResolver`、`OrchestratorService`、`ExecutionModeSelectorService`、`PoolIntentResolverService`
- 路由/治理：`PublicAgentA2AService`、`PublicAgentRegistryService`、`AgentPoolService`、`AgentPoolAggregateService`、`AdminSubPoolService`、`RuntimeModelPoolService`、`ModelAssignmentPolicyService`、`CostPolicyService`
- 工具/资源：`BuiltinToolService`、`ApiToolService`、`McpService`、`McpRuntimeAdapter`、`McpImportService`、`SkillService`、`SkillImportService`、`WorkflowService`（admin）、`DagEngineService`、`AppRuntimeService`、`AppConfigService`、`AgentTaskExecutor`
- 知识/记忆：`KnowledgeBaseService`、`KnowledgeIndexingService`、`KnowledgeVectorService`、`FaissService`、`RerankService`、`RetrievalService`、`ScopedKnowledgeService`、`ExternalDataSourceService`、memory/ 子目录（`MemoryWriteService`、`ConsolidationEngine`、`Retriever`、`DigestManager`、`HebbianDecay`、`FunnelCompressor`、`AgentMemoryTool`、`PostExecutionHook` 等 30+ 文件）
- 计费/审计：`BillingMeteringService`、`CreditService`、`CostStatsService`、`AuditLogService`、`RoutingLogService`、`RoutingQualityService`、`RoutingObservabilityService`、`GovernanceAuditLogger`
- 管理/用户：`AdminUserService`、`AdminRbacService`、`AdminAppService`、`AdminAgentPoolService`、`AdminModelPoolService`、`AdminModelProviderService`、`AdminToolGovernanceService`、`AdminBillingPlanService`、`AdminCustomerUserService`、`AdminWorkflowService`、`OrchestrationFeatureFlagService`

**内置工具提供商（providers.yaml + codex_os，24 类）**

search：google、duckduckgo、serpapi、tavily；image：dalle、stability、siliconflow、qwen、atlascloud_image；video：atlascloud_video；academic：arxiv；weather：openweathermap；news：newsapi；compute：wolframalpha；code：github；tool：time、gaode、baidu（翻译）、exchangerate、ipinfo、qrcode、urlshortener；automation：codex_os（`run_os_task`）

**HTTP/API**

`app.py` + `asgi_app.py`（Quart）、8 组 admin 路由、apps_routes、chat_routes、conversation_routes、workflow_routes、knowledge_mcp_routes、schedule_assistant_routes、skills_tools_routes、user_routes_9、home_misc_routes、account_auth_routes、openapi 交付

**前端（147 个 .vue）**

管理端 33 页：Dashboard、Apps、AgentPool、Tools、ToolGovernance、MCP、Skills、Workflows、Models、ModelProviders、CostStrategy、CostDashboard、Billing、RoutingLogs、RoutingQuality、AuditLogs、Users、Roles、CustomerUsers、Showcase、StoreApps/StoreTools/StoreMcp/StoreSkills/StoreWorkflows、RecycleBin、Storage、SystemKnowledge、PublicAIFeatureConfig、OrchestrationFlags 等；用户端：首页助手、Web App 聊天、工作台、调试预览等

**数据模型/迁移**

40+ 模型（account、app、dataset、knowledge、mcp、skill、workflow、memory、routing_log、routing_quality、schedule_task、tool_governance、tool_confirmation、orchestration_feature_flag、billing、public_ai_feature_config 等）+ 多套 Alembic 迁移

### 4.2 目前不存在的能力

- 桌面 App、插件 SDK、Artifacts 沙箱预览、SSH 远程后端
- `!` shell 直执行、`/init`、`/diff`、`/context`、`/focus` 等终端命令
- grounded-citations / 事实核查
- 工具级自恢复诊断（截断回读、已应用检测、落盘校验等）
- IM 网关多平台接入（Feishu/DingTalk/WhatsApp 等）
- 浏览器自动化、计算机控制、桌面端/TUI/CLI/ACP 编辑器集成
- 会话导出（html/md）、checkpoint 恢复、学习图与技能 Curator 生命周期
- GitHub/API 事件触发的入站 webhook 自动化 + 多平台投递

## 5. 功能对比矩阵

| 维度 | Hermes v0.20 | 钰心AI 当前 | 差距性质 |
| --- | --- | --- | --- |
| 定位 | 单用户本地 Agent | 多租户 Agent 调度平台 | 定位不同，不能直接套用 |
| 审批交互 | 智能审批：历史挖掘 allowlist、可自定义策略、连续拒绝熔断、桌面配对审批面 | 每次高风险工具调用弹卡片，确认/取消/超时安全取消，30 分钟会话内免重复授权；审批历史挖掘与熔断建议已落地（dry-run），`tool_governance_policy.require_confirmation=false` 可运行时自动放行 | **核心差距：桌面配对审批面、策略学习闭环仍待增强** |
| 执行中纠正 | mid-turn redirect，保留进行中工作 | 请求级 redirect：`/subtasks/<request_id>/redirect` 写入纠正，`_llm_node` 每轮前注入并重新规划；确认等待期仍走 `/tool-confirmations/{id}/redirect` | 已对齐；同步工具执行期间需等待该步结束后注入 |
| 确认后续跑 | 确认后同一轮继续 | WebApp 后台 worker 完整执行并落库，SSE 与任务解耦；确认后前端轮询执行摘要，断线不丢结果 | 核心断点已修复；仍缺完整“恢复同一轮 SSE”体验 |
| Agent 互操作 | A2A v1.0 标准协议 | A2A v1.0 网关（Agent Card / message/send / tasks/get / message/stream / 出站客户端） | 已对齐；跨系统认证与流式体验继续完善 |
| 外部事件推送 | HMAC 签名出站 webhook | HMAC 出站 webhook（工具确认/取消事件） | 入站事件触发未做 |
| 工具失败自恢复 | 系统级诊断与提示 | 工具异常统一回灌错误文本，靠模型重试 | 需要增强 |
| 上下文压缩 | 逐轮微压缩 + 尾巴保护 + ghost-skill 防御 | 有压缩器，但未做逐轮摊销/保证尾巴 | 中等差距 |
| 记忆 | Holographic / OpenViking provider + 技能涌现 | System 1/2 + Ledger + Nudge + 技能涌现，架构文档已吸收 Hermes 基因 | 钰心AI 记忆分层更完整，Hermes 自主性更成熟 |
| 语音 | 流式 TTS + barge-in + 唤醒词 + 多平台 | Web 语音转文本 + TTS 播报 | 场景能力差距 |
| 桌面/客户端 | Artifacts + 插件 SDK + 多窗口 | 无桌面端 | 场景能力差距 |
| 可观测性 | OTLP 导出、NeMo Relay、dashboard | 管理端路由日志/成本统计/AuditLogs | 钰心AI 管理面更全，缺标准导出 |

### 5.1 逐项功能存在性矩阵（✅=已实现且有运行路径，◑=设计/部分实现，✗=无）

| 能力 | Hermes v0.20 | 钰心AI |
| --- | --- | --- |
| Agent 自研主循环 | ✅ `conversation_loop` / `turn_runner` | ◑ LangGraph 图执行 + `SingleAgentExecutor`，非自研 |
| 多模型 provider | ✅ plugins/model-providers 下 30+ 个 provider 插件 | ✅ LangChain 多 provider + `AdminModelPoolService` |
| 模型路由/降级 | ✅ provider catalog + credential pool + fallback | ✅ `ModelGatewayService` / `FallbackManager` / 模型档位 |
| 上下文压缩 | ✅ 逐轮微压缩 + 尾巴保护 + ghost-skill 防御 | ◑ `FunnelCompressor` / `TokenBufferMemory`，未做逐轮摊销 |
| 子代理委派 | ✅ delegate + 生命周期 API + 实时状态 | ✅ `MultiAgentExecutor` + Redis 化 `SubtaskRegistryService` + `GET/POST /subtasks/<request_id>[/cancel]` + SSE 实时事件 + 首页 `SubtaskProgressPanel` |
| 审批/授权 | ✅ 历史挖掘 allowlist + 熔断 + 跨面确认 | ✅ `tool_confirmation` 卡片 + 30 分钟免重复授权 + 审批挖掘 dry-run；运行时自动放行策略未接 |
| 执行中纠正 | ✅ mid-turn redirect | ✅ 请求级 redirect（每轮 LLM 前注入 + 重新规划） |
| 终端执行 | ✅ 多终端/进程管理 + 工具自恢复 | ◑ `run_os_task` 经宿主 worker 调 Codex，非平台原生终端 |
| 文件工具 | ✅ file/patch/diff/write 校验 | ✅ 文件存储 + 工作流文件节点 + artifact |
| 浏览器自动化 | ✅ CDP/camofox/supervisor | ✗ |
| 计算机控制 | ✅ computer-use / cua | ✗ |
| 网页搜索 | ✅ 8 个搜索 provider | ✅ google/duckduckgo/serpapi/tavily |
| 图像生成 | ✅ 7 个 provider | ✅ dalle/stability/siliconflow/qwen/atlascloud |
| 视频生成 | ✅ fal/xai/deepinfra | ✅ atlascloud_video |
| 语音对话 | ✅ 流式 TTS + barge-in + 唤醒词 | ◑ 录音上传 + TTS 播报 |
| 视觉理解 | ✅ vision tools + 路由 | ◑ 图片理解依赖模型能力，无独立视觉工具编排 |
| 记忆 | ✅ 8 个 provider + Agent-curated | ✅ System 1/2 + Ledger + Nudge + 技能涌现 |
| 技能 | ✅ 14 类 skills + Curator + 即时涌现 | ✅ `SkillService` + `SkillImportService` + 技能商店 |
| MCP | ✅ 懒加载 server + schema cache + OAuth | ✅ `McpService` + MCP 商店 + 运行时挂载 |
| A2A | ✅ A2A v1.0 标准插件 | ✅ A2A v1.0 网关 + 出站客户端 |
| 消息平台 | ✅ 28+ 平台适配器 | ✗ 仅 wechatpy 微信公众号 |
| 桌面端 | ✅ Electron 40 + 插件 SDK + Artifacts | ✗ |
| TUI | ✅ Ink TUI | ✗ |
| Web dashboard | ✅ React dashboard | ✅ Vue 3 管理端 33 页 |
| CLI 命令集 | ✅ 40+ 子命令 + 斜杠命令 | ✗（平台无终端 CLI） |
| 定时任务 | ✅ croniter + 插件 | ✅ Celery beat + `ScheduleTaskService` |
| 看板/任务板 | ✅ kanban 插件 | ◑ 工作流/任务编排，无看板 |
| 外部事件推送 | ✅ HMAC webhook | ✅ HMAC 出站 webhook（工具确认/取消事件；入站事件触发未做） |
| 可观测性 | ✅ OTLP + Langfuse + NeMo Relay | ✅ 路由日志/成本/AuditLogs，无标准导出 |
| 计费 | ✅ 订阅/credits/usage pricing | ✅ credits/积分/成本统计/实时计费事件 |
| 多租户 | ✗ 单用户 profile | ✅ 账号/RBAC/租户隔离/资源分配 |
| 可视化工作流 | ✗ | ✅ `DagEngineService` + Vue Flow 编辑器 |
| 知识库/RAG | ◑ 云记忆 + 文件引用 | ✅ 数据集/切片/混合检索/知识库 |
| 文件预览 | ✗ 桌面内预览 | ✅ kkFileView + 文件存储 |

## 6. 技术栈对比（v2026.8.3 实际依赖 + 本仓库实际依赖）

### 6.1 后端

| 维度 | Hermes v0.20 | 钰心AI |
| --- | --- | --- |
| 语言 | Python `>=3.11,<3.14`（`.python-version` 为 3.11） | Python 3.12（`api/Dockerfile` 基于 `python:3.12-slim-bookworm`） |
| 依赖管理 | `uv` + `uv.lock`，核心依赖**全精确 pin**（`==X.Y.Z`），供应商类依赖全部放 extras 按需懒加载（`tools/lazy_deps.py`） | `pip` + `api/requirements.txt` 全量安装，核心运行依赖也基本固定版本，但无 lockfile 分层 |
| Web 框架 | FastAPI + uvicorn（web/dashboard 与 API server） | Quart + uvicorn（HTTP 已全量迁移到 Quart），Flask 仅保留为兼容依赖 |
| Agent 框架 | 自研 agent loop（`agent/` 目录，直接调 OpenAI/Anthropic/Gemini/Bedrock adapter），不依赖 LangChain | LangChain 1.x + LangGraph + deepagents，Agent 统一转 LangChain `BaseTool` |
| 模型 SDK | 核心仅 `openai`，Anthropic/Gemini/Bedrock/Azure 等按 provider 分 extra | openai、langchain-openai/anthropic/google-genai/deepseek/ollama 等聚合 |
| MCP | 可选 extra（`mcp==1.28.1` + starlette），MCP server 懒启动 | `mcp>=1.0.0`，内置 `McpProvider` / `McpToolFactory` |
| 任务队列 | 内置 croniter 定时器，无 Celery 类独立 worker | Celery + celery-beat（`docker-compose.yaml` 三个独立服务：api / celery / celery-beat） |
| 实时通信 | WebSocket + SSE（dashboard、桌面 SSH、Relay） | SSE（首页助手/Web App 流式）+ Socket.IO（python-socketio） |
| 终端/进程 | `ptyprocess` / `pywinpty` / `pywin32`，node-pty（桌面） | pexpect / psutil / python-engineio 等，OS 自动化走独立宿主 worker |

### 6.2 前端

| 维度 | Hermes v0.20 | 钰心AI |
| --- | --- | --- |
| Web | React 19 + Vite 8 + TailwindCSS 4 + `@nous-research/ui`（web dashboard） | Vue 3 + Vite 8 + TypeScript + Pinia + TailwindCSS 4 + Arco Design |
| 桌面 | Electron 40 原生桌面 App（`apps/desktop`），xterm.js、CodeMirror、mermaid、shiki、DnD Kit | 无桌面端 |
| TUI | React Ink TUI（`ui-tui`） | 无 TUI |
| 可视化 | `@observablehq/plot`、React Three Fiber / three | ECharts + vue-echarts、Vue Flow、Monaco Editor |
| 流式渲染 | streamdown（token 级流式渲染） | 自研 chat-stream + markdown-it + highlight.js |

### 6.3 数据与基础设施

| 维度 | Hermes v0.20 | 钰心AI |
| --- | --- | --- |
| 会话/状态 | 本地 SQLite / 文件式 session 存储 + 云记忆 provider（mem0 / supermemory / honcho / hindsight，均懒加载） | PostgreSQL 18 + pgvector、Redis、Neo4j，SQLAlchemy 模型 + Alembic 迁移 |
| 向量检索 | 云 memory provider 负责；本地核心不带重向量库 | FAISS + pgvector + 混合检索 + 知识库切片 |
| 记忆实现 | Holographic Memory（HRR 编码）+ provider 抽象 | System 1/2 双路 + Ledger + Hebbian 衰减 + FunnelCompressor + Agent-Curated 记忆 |
| 文件存储 | 本地文件 + 云服务按需 | MinIO / 阿里云 OSS / 本地存储 + kkFileView 预览 |
| 网关/平台 | WhatsApp / Feishu / DingTalk / LINE / QQ / WeChat / Telegram / Discord / Slack / Matrix / WeCom / Buzz（Nostr）等 | wechatpy（微信公众号）为唯一渠道类依赖 |
| 部署 | shell installer / Docker / Nix，单机自托管 | Docker Compose 全家桶（nginx + ui + api + celery + redis + pgvector + neo4j + minio + kkfileview） |
| 可观测性 | OTLP export、NeMo Relay、dashboard 统计 | Prometheus client、路由日志、AuditLogs、成本统计 |

### 6.4 技术栈差异的实质影响

1. **Agent 内核差异最大**：Hermes 是自研 agent loop，几十个 adapter 直接面对模型 API，核心依赖刻意保持很瘦；钰心AI 站在 LangChain/LangGraph 生态上，换来工具/工作流/记忆集成速度，代价是依赖面大、升级受上游约束。
2. **状态模型不同**：Hermes 是“单机 session + 可选云记忆”，钰心AI 是“全托管多租户事务型底座（PG + Redis + Neo4j + MinIO）”。Hermes 的 SQLite 方案无法直接套到多租户计费/审计/治理上。
3. **前端形态不同**：Hermes 是 React + Electron + TUI 三端，钰心AI 是 Vue 3 Web 单端。功能可以借鉴，组件不能直接移植。
4. **依赖治理可借鉴**：Hermes 对供应商类 SDK 全部做成 optional extra 并懒加载，核心依赖精确 pin；钰心AI 现在把 LangChain 全家、文件解析、社交 SDK 全部装进一个镜像，镜像体积、攻击面和启动时间都会更重。
5. **异步任务体系不同**：Hermes 用进程内 cron，钰心AI 有 Celery 独立 worker，适合长任务、多租户隔离和后台批处理，这一点反而是钰心AI 更匹配平台形态。

## 7. 与用户侧交互问题的直接关联

用户反馈的“确认卡片弹出后 Agent 直接结束会话”问题，根源不是清理 C 盘单场景，而是**执行器生命周期与前端确认回调没有闭环**：

- 后端 `FunctionCallAgent._tools_node` 会发布 `TOOL_CONFIRMATION_REQUIRED` 并进入 `_wait_for_confirmation` 轮询，设计上确认后应继续同一轮（见 `api/internal/core/agent/agents/function_call_agent.py`）。
- 前端 `IndexView.handleConfirmTool` 确认成功后只更新本地卡片状态，没有重新订阅/恢复 SSE 流（见 `ui/src/views/web-apps/IndexView.vue`），所以用户点击确认后看不到任务恢复。
- 卡片直接把 `tool_input` 参数表展示给用户（`ToolConfirmationCard.vue`），用户看到的是 `task` / `mode` / `approval_token` 这类工程字段，而不是“将执行什么、影响什么、能否回滚”的可读说明；这正是用户抱怨“带 Markdown、显示 JSON、不像产品交互”的原因。

Hermes 给出的参照是**把审批做成策略化交互面，而不是裸参数确认**：

1. 先请求工具/任务授权（此时不执行任何操作）
2. 授权后自动进入只读扫描/计划生成
3. 把可执行范围和预估影响以人话展示
4. 反问用户具体范围（只清回收站、只清某类缓存、预估释放空间）
5. 用户明确后带着上下文继续执行

这套流程对任意高风险工具都成立（发邮件、删文件、支付、外部写操作等），应抽象成通用“工具执行阶段机”，而不是在 `run_os_task` 的 prompt 里写死。

## 8. 建议借鉴点（按优先级）

| 优先级 | 借鉴点 | 落地方向 |
| --- | --- | --- |
| P0 | 确认后同一轮续跑 | 前端确认回调后恢复 SSE 订阅/拉取；后端等待确认改为可重入的轮询任务，断线可恢复 |
| P0 | 授权卡片人话化 | 卡片展示“将执行什么 / 影响范围 / 是否可回滚 / 预估成本”，隐藏 tool_input 原始 JSON；由后端按工具类型生成确认文案模板 |
| P1 | 通用“先授权→再扫描→再反问范围→再执行”阶段机 | 把确认对象从“单个工具调用”升级为“任务级授权上下文”，支持多轮反问后携带同一授权令牌继续 |
| P1 | 审批策略与历史 | 已落地：历史挖掘 dry-run + `require_confirmation=false` 自动放行 + 30 分钟免重复授权；剩余是策略学习闭环 |
| P1 | 超时默认行为明确化 | 当前超时一律安全取消；若产品要“超时默认执行推荐项”，必须由管理员策略显式声明，不能静默切换 |
| P2 | mid-turn redirect | 已落地：`/subtasks/<request_id>/redirect` 请求级注入；剩余是同步工具执行期的即时中断 |
| P2 | 标准 A2A v1.0 | 在私有 `route_public_agents` 之上增加协议适配层，便于外部 Agent 互操作 |
| P2 | 签名出站 webhook | 复用现有 SSE 事件模型，增加 HMAC 签名推送，供外部系统/运维订阅生命周期事件 |
| P3 | 工具自恢复 | 终端截断可读回、写文件后校验、搜索零结果探测，减少模型盲目重试 |
| P3 | 依赖治理 | 参考 Hermes 的 extras 懒加载，把模型/搜索/文档/社交类 SDK 从核心镜像拆出去，按功能启用 |

## 9. 不建议模仿的部分

- 桌面 App / 插件 SDK / Artifacts 沙箱：与钰心AI Web 平台形态不符，除非产品明确要做客户端
- IM 网关全家桶：多租户合规、消息签名、异步回调成本高，建议按实际渠道逐个接入
- `!` shell 直执行：钰心AI 是多租户平台，不能让终端用户直接获得 shell；该能力只应存在于受限的宿主 OS worker 链路中
- 单用户 profile/配对审批：钰心AI 需要的是账号级授权与审计，不是本机配对

## 10. 结论

Hermes v0.20 已开源（MIT，正式版，活跃维护），但它与钰心AI 不是竞争关系，而是两种形态：一个偏个人工作站 Agent，一个偏多租户调度平台。钰心AI 在编排开关、成本、治理、记忆、私有 A2A、管理端可观测性上有自己的体系；真正值得立刻对齐的是**审批/确认交互的通用化**，也就是把“授权→扫描→反问→执行”做成平台级阶段机，并修好确认后 SSE 续跑的断点。这样无论用户提的是清理 C 盘、发邮件还是外部写操作，都不会再出现“弹卡后会话死了”的问题。

## 11. 能力移植落地进度

> 目标：从 Hermes v2026.8.3 选择性复用能力，不是整仓库搬运。Hermes 的工具与其
> CLI/配置/网关运行时强耦合，直接复制会拖入整个 Hermes 底座；本项目按
> LangChain + 多租户治理架构重写算法与安全规则。

### 11.1 已完成（含测试）

| 模块 | 来源 | 落地位置 | 说明 |
| --- | --- | --- | --- |
| V4A 补丁解析/应用 | `tools/patch_parser.py` + `tools/file_operations.py` | `api/internal/core/agent/adapters/hermes/v4a_patch.py` | add/update/delete/move、CRLF 保留、已应用 no-op、空白诊断 |
| 敏感信息脱敏 | `agent/redact.py` | `api/internal/core/agent/adapters/hermes/redact.py` | 常见 token 前缀、env/JSON/Authorization/URL 参数遮蔽 |
| 审批历史挖掘 | `hermes_cli/approvals_suggest.py` + `tools/approval.py` | `api/internal/core/agent/adapters/hermes/approval_mining.py` | allowlist 建议 + 连续拒绝熔断，破坏性工具永不建议 |
| 宿主机文件操作 worker 端点 | `tools/file_tools.py` 思想 | `api/scripts/os_automation_worker.py` `/file` | read + patch preview/apply，安全根目录校验，approval_token 一次性 |
| Agent 侧文件工具 | `tools/file_tools.py` 思想 | `api/internal/core/tools/builtin_tools/providers/codex_os/os_file_task.py` | `os_file_task`，读取/补丁，接入高风险确认 |
| 首页助手挂载 | — | `api/internal/service/assistant_agent_service.py` | `run_os_task` + `os_file_task` 自动挂载 |
| 授权摘要人话化 | — | `api/internal/core/agent/agents/function_call_agent.py` | `os_file_task` 确认文案区分读取/补丁，授权后强制 preview |
| 匿名访客确认链路 | Hermes 跨表面确认思想 | `api/app/http/knowledge_mcp_routes.py` + `ui/src/utils/visitor.ts` + `ui/src/services/tool-confirmation.ts` + `ui/src/services/web-app.ts` | WebApp 访客用稳定 `visitor_id` 绑定对话与确认，修复“确认失败/会话中断”断点 |
| WebApp 任务生命周期解耦 | 断点续传思想 | `api/internal/service/web_app_service.py` | Agent 后台 worker 完整执行并落库，SSE 只转发；前端断线不丢结果 |
| 确认后结果轮询 | — | `ui/src/views/web-apps/IndexView.vue` | 与 HomeView 对齐：确认后轮询执行摘要，断线后仍能拿到后台结果 |
| HMAC 签名出站 webhook | `agent/outbound_webhooks.py` + `hermes_cli/webhook.py` | `api/internal/core/agent/adapters/hermes/outbound_webhook.py` + `api/internal/service/tool_confirmation_service.py` | 事件信封 + HMAC 签名 + 重试；工具确认/取消时经 `OUTBOUND_WEBHOOK_URL/SECRET` 推送 |
| A2A v1.0 网关 | `plugins/platforms/a2a/*` | `api/internal/core/agent/adapters/hermes/a2a_protocol.py` + `api/internal/service/a2a_gateway_service.py` + `api/app/http/a2a_routes.py` | Agent Card + JSON-RPC（message/send、tasks/get），外部 A2A 对端可发现并委派公共 Agent |
| A2A v1.0 出站客户端 | `plugins/platforms/a2a/tools.py` | `api/internal/core/agent/adapters/hermes/a2a_client.py` | Agent 可调用外部 A2A 对端（`a2a_send_message` 工具），双向互操作闭环 |
| 语音工具（STT/TTS） | `tools/tts_tool.py` + `tools/transcription_tools.py` 思想 | `api/internal/core/tools/builtin_tools/providers/audio_tools/` | `tts_speak` 返回音频 data URI；`audio_transcribe` 转写 URL/data URI；复用 SiliconFlow 底座并挂载首页助手 |
| 网页提取工具 | `tools/web_tools.py::web_extract_tool` | `api/internal/core/tools/builtin_tools/providers/web_tools/` | `web_extract` 抓取网页并转可读文本；带 SSRF 防护、大小限制，挂载首页助手 |

### 11.2 待落地（按依赖顺序）

1. **确认后续跑闭环（P0，基本完成）**：匿名访客身份、确认接口、WebApp 任务生命周期解耦（后台 worker 继续执行并落库）、确认后轮询执行摘要均已落地；剩余是前端主动“恢复同一轮 SSE”的体验增强。
2. **工具自恢复接入**：把 V4A 诊断输出接进 Agent 提示，`os_file_task` 失败时自动尝试已应用/空白修复。
3. **审批策略服务化（已完成）**：`approval_mining` dry-run + `SmartApprovalPolicyService` 运行时自动放行
   （`tool_governance_policy.require_confirmation=false`），危险工具永不自动放行。
4. **A2A v1.0 协议适配层**：已完成 Agent Card、message/send、tasks/get、message/stream、出站客户端与 `a2a_send_message` 工具；剩余是跨系统认证与发现增强。
5. **签名出站 webhook**：已完成工具确认/取消事件推送；剩余是可扩展为 session/turn 生命周期事件与多订阅端点管理。
6. **语音对话能力**：STT/TTS Agent 工具已完成；剩余是流式分句播放与打断语义（barge-in）。
7. **更多通用工具拆装**：web_extract、web_search、vision_analyze、代码执行（含 tool_calls RPC 桥）、任务清单等已接入；代码执行默认关闭且按高风险工具确认。

8. **子任务实时状态（P0，已完成）**：`SubtaskRegistryService` + `MultiAgentExecutor` +
   `GET /subtasks/<request_id>` + SSE `subtask_started/running/completed` + 首页 `SubtaskProgressPanel`
   已形成闭环，registry 已升级为 Redis 优先、内存兜底，支撑多 worker 部署；新增
   `POST /subtasks/<request_id>/cancel` 公共取消接口。

完整逐项盘点见 `docs/research/hermes-v0.20-capability-deep-dive.md`。

### 11.3 许可证与归属

Hermes v0.20 为 MIT，本项目为 MIT。移植时保留模块头注释声明来源；若后续整体复制
较大文件，需在仓库增加 `THIRD_PARTY_NOTICES` 保留上游版权与许可文本。

## 来源

- GitHub 仓库与 release API：https://github.com/NousResearch/hermes-agent
- v0.20.0 Release Notes：https://github.com/NousResearch/hermes-agent/releases/tag/v2026.8.3
- Hermes v2026.8.3 依赖清单：仓库根 `pyproject.toml`、`uv.lock`、`package.json`、`apps/desktop/package.json`、`web/package.json`、`ui-tui/package.json`
- 官方博客 v0.20 Herald Release：https://hermes-agent.ai/blog/hermes-agent-v0-20-herald-release
- 钰心AI 架构文档：`docs/prd/architecture-design.md`
- 编排/可观测性子文档：`docs/prd/modules/03-orchestration-infra.md`
- OS 自动化模块：`docs/prd/modules/08-os-automation.md`
- 工具授权执行链路：`api/internal/core/agent/agents/function_call_agent.py`
- 确认卡片前端：`ui/src/components/ToolConfirmationCard.vue`、`ui/src/views/web-apps/IndexView.vue`
