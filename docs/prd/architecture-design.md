# OpenAgent 架构设计文档

> **文档信息**
>
> | 项 | 值 |
> |---|---|
> | 文档名称 | OpenAgent 通用 Agent 调度平台 — 架构设计 |
> | 版本 | v5.2 |
> | 日期 | 2026-07-30 |
> | 定位 | 只描述产品方向、目标架构与模块设计方案，不包含执行计划与任务拆分 |
> | 配套文档 | execution-roadmap.md（分阶段任务与执行路线） |
> | 文档结构 | 本文档为模块化索引，详细内容拆分至子文档 |

---

本文档定义 OpenAgent 的目标架构与核心模块设计方案。系统应从"可配置 Agent 应用平台"演进为"通用 Agent 调度平台"：管理员配置能力，用户自然语言提出需求，系统自动选择模型、Agent 和工具完成任务。

---

## 文档导航

本文档采用模块化拆分，各章节内容分布如下：

| 章节 | 内容 | 位置 |
|---|---|---|
| Ch 1-7 | 概述、背景、愿景、能力复盘、目标架构、设计原则、角色边界 | 本文（下文） |
| Ch 8-10 | 动态子集归集、Agent 池设计、工具池设计 | [modules/01-agent-tool-pool.md](./modules/01-agent-tool-pool.md) |
| Ch 11 | 知识库双层设计（系统级知识库 + 用户个人知识库） | [modules/02-knowledge-base.md](./modules/02-knowledge-base.md) |
| Ch 12-15 | 模型路由/Key 池/成本控制、Orchestrator、ResultSynthesizer、可观测性 | [modules/03-orchestration-infra.md](./modules/03-orchestration-infra.md) |
| Ch 16 | 脑启发记忆系统（v5.0 新增） | [memory-system/00-overview.md](./memory-system/00-overview.md) |
| Ch 17 | 文件存储与对象存储架构 | [modules/06-file-storage.md](./modules/06-file-storage.md) |
| Ch 18-19 | 社交社区架构、用户共创分身与创作者经济 | [modules/04-social-creator.md](./modules/04-social-creator.md) |
| Ch 20-23 | 安全要求、关键风险、Feature Flag、成功指标 | [modules/05-security-risk-decisions.md](./modules/05-security-risk-decisions.md) |
| Ch 24 | 公共 AI 资源配置板块 | [modules/07-public-ai-config.md](./modules/07-public-ai-config.md) |
| Ch 25 | 指挥官架构与 Prompt 模板管理（v5.2 新增） | 本文 §25 |
| Ch 26-27 | 已确认决策、总结 | [modules/05-security-risk-decisions.md](./modules/05-security-risk-decisions.md) |

### 记忆系统子文档

第 16 章的完整实现细节拆分至 4 个子文档：

| 子文档 | 覆盖模块 |
|---|---|
| [memory-system/00-overview.md](./memory-system/00-overview.md) | 概览：设计原则、脑启发映射、System 1/2 架构、技术栈、路线图、与知识库集成 |
| [memory-system/01-data-models-and-write-path.md](./memory-system/01-data-models-and-write-path.md) | 数据模型 + 写入路径（SalienceScorer、LedgerWriter、实体消解） |
| [memory-system/02-storage-and-retrieval.md](./memory-system/02-storage-and-retrieval.md) | 存储分级 + 读取路径（HebbianDecay、MemoryRetriever、FunnelCompressor、DigestManager） |
| [memory-system/03-consolidation-skill-policy-api.md](./memory-system/03-consolidation-skill-policy-api.md) | 巩固引擎 + 技能池 + Policy + API + 监控 |

---

## 2. 背景与问题定义

OpenAgent 当前已经具备 Agent 平台的多个基础模块：主入口 Assistant Agent、公共 Agent A2A 路由、MCP Provider、AppConfig 模型配置、AppConfig 工具绑定、配置中心、后台管理、应用分配、SSE 流式事件、深度思考 Agent 等。这些能力说明系统已经不是一个简单聊天应用，而是具备 Agent 平台底座。

但当前系统与目标产品形态仍存在差距。当前系统更接近：

```text
用户 -> 主入口 Assistant Agent -> 公共 Agent / 预配置工具 -> 返回结果
```

目标系统应演进为：

```text
用户
  -> 主入口调度器
  -> 任务理解与拆解
  -> 多 Agent 子池动态归集
  -> 多工具子池动态归集
  -> A2A / 工具调用执行
  -> 主入口汇总
  -> 用户
```

其中管理员负责配置多个 Agent 子池、多个工具子池、模型策略、Key 池、权限策略、成本策略和日志策略；普通用户只在主入口输入需求，系统自动完成任务理解、子池选择、模型选择、Agent 选择、工具选择、结果汇总和最终回显。MCP 属于工具池维度，A2A 属于 Agent 协作和调用维度，两者不能混为一个能力池。

本 PRD 的目标是将前期讨论沉淀为一套可分阶段落地、可测试、可回滚、可持续演进的系统改造方案。



## 3. 产品愿景

### 3.1 一句话愿景

把 OpenAgent 从"可配置 Agent 应用平台"升级为"通用 Agent 调度平台"：管理员配置能力，用户自然语言提出需求，系统自动选择合适模型、合适 Agent 和合适工具完成任务，并以统一、可靠、成本可控的方式返回结果。

### 3.2 用户侧体验目标

普通用户不需要知道：

- 有哪些 Agent。
- 有哪些 MCP。
- 哪些工具可用。
- 哪个模型便宜或强大。
- 任务应该拆给谁。
- 工具如何配置。

普通用户只需要：

```text
在首页输入需求或问题。
```

系统应该自动完成：

```text
理解需求 -> 判断复杂度 -> 分配 Agent -> 调用工具 -> 汇总结果 -> 返回答案
```

### 3.3 管理员侧体验目标

管理员需要能配置和运营：

- 多个 Agent 子池。
- 多个工具子池。
- MCP Provider。
- 模型池。
- Key 池。
- 成本策略。
- 用户积分 / token 扣费策略。
- 路由策略。
- 权限策略。
- 审计和路由日志。
- 日志保留周期。

管理员配置一次公共工具，多个 Agent 可按需使用，而不是给每个 Agent 重复绑定同一批工具。

#### 3.3.1 管理端板块职责分离

管理端分为五个板块，各司其职，严禁跨板块操作：

| 板块 | 定位 | 管什么 | 不管什么 |
| --- | --- | --- | --- |
| 资源编排 | 资源实体 CRUD（目录层） | 系统级资源存在不存在、长什么样（创建/编辑/删除 App/Workflow/Dataset/Tool/MCP/Skill） | 用户分身、上架到商店、使用规则、运行时开关 |
| 资源运营 | 用户创作内容审核 + 创作者经济 + 商店运营（可见层） | 分身审核/上下架/质量监控、创作者信用与收益、推荐位与定价、商店可见性 | 系统资源本身定义、使用规则 |
| 池治理 | 使用规则策略（策略层） | 风险等级、路由优先级、可见性、限流、模型档位 | 资源本身、规则是否生效 |
| 编排控制 | 运行时开关（开关层） | 策略启用/灰度/回滚/熔断（feature flag） | 规则定义、事后观测 |
| 观测中心 | 事后观测反馈（反馈层） | 决策记录、质量反馈、管理员操作审计 | 规则定义、开关控制 |

数据流：`资源编排(创建) → 资源运营(上架) → 池治理(设规则) → 编排控制(开关生效) → 观测中心(看效果)`

**数据所有权原则**：同一份数据只能在一个板块编辑，其他板块只读展示。例如 Agent 的 primary_pool/risk_level/routing_priority 只在池治理的 AgentPoolView 编辑，资源编排的 AppsView 只读展示。



## 4. 当前系统能力复盘

### 4.1 已有能力

| 能力 | 当前实现 | 对目标架构的价值 |
| --- | --- | --- |
| 主入口 Assistant Agent | `/home` + `/assistant-agent/chat` | 可升级为 Orchestrator 入口 |
| 公共 Agent 路由 | `route_public_agents`、`PublicAgentA2AService` | 可演进为 Agent Router |
| 公共 Agent 检索 | `PublicAgentRegistryService` | 可演进为 Agent Pool 检索 |
| A2A 调用 | `send_message(app_id, payload)` | 可作为下游 Agent 执行通道 |
| MCP Provider | `McpProvider`、`McpService` | 可演进为 Tool Pool |
| App 模型配置 | `AppConfig.model_config` | 可演进为 Agent 模型档位配置 |
| App 工具绑定 | `AppConfig.mcp_bindings` | 可作为第一阶段兼容工具装载方式 |
| 深度思考 Agent | `A2ADeepThinkingAgent`、`DeepThinkingAgent` | 可作为复杂任务执行路径 |
| SSE 事件 | `agent_message`、`agent_action`、`deep_step` 等 | 可扩展为调度过程可观测事件 |
| 配置中心 | `/space/*` | 管理员配置 Agent、工具、知识库、工作流 |
| 我的 AI | `/my-ai`、`/my/apps` | 普通用户显式使用已分配应用 |
| 后台应用分配 | `AppAssignment`、`AdminAppAssignmentService` | 可作为可用 Agent 权限来源 |
| 后台 RBAC | `AdminRbacService` | 可作为管理员权限基础 |

### 4.2 当前主要缺口

| 缺口 | 说明 | 影响 |
| --- | --- | --- |
| 缺少 Agent 池元数据 | App 主要依赖名称和描述 | 路由质量不稳定 |
| 缺少共享工具池动态检索 | 工具主要按 AppConfig 预绑定 | 工具复用差、配置重复、上下文膨胀 |
| 缺少成本感知模型路由 | 没有模型档位、价格、预算策略 | 成本不可控 |
| 缺少显式结果汇总器 | 结果主要由 LLM 工具调用后自然整合 | 多 Agent 结果质量不稳定 |
| 缺少调度日志 | agent_thoughts 不是完整调度审计 | 难以调试路由和成本 |
| 工具权限粒度不足 | MCP 有 public/private，但缺少风险、权限、审批 | 动态工具池上线风险高 |
| 长期记忆提取能力严重不足 | long_term_memory_service.py 的 MemoryCandidateExtractor 硬编码只识别"中文"语言偏好 | 无法记住用户画像，每次对话像第一次见面 |
| 知识库 RAG 检索链路缺失 | knowledge_base_service.py 仅有 CRUD，未见向量索引构建/chunking/embedding/相似度召回 | 用户上传文档后 AI 无法检索使用 |
| 上下文管理过于基础 | token_buffer_memory.py 用 trim_messages(strategy="last", max_tokens=2000) 直接截断早期消息 | 长对话丢失关键信息 |
| 缺少日常生活类工具 | 20 个内置工具全偏信息查询/内容生成，无邮件/日历/社交媒体/支付/任务管理 | 无法覆盖工作+生活+社交全场景 |
| 缺少社交社区能力 | 无会话分享/导出、无用户主页、无内容流、无关注关系 | 无法支撑社交社区产品形态 |



### 4.3 底座能力复用与偏离修正

OpenAgent 已具备成熟的 Agent 应用平台底座，池治理改造不应推倒重来，而应区分"可复用"与"需重组"两类。

#### 4.3.1 可直接复用的底座能力

| 能力 | 现有实现 | 复用方式 |
| --- | --- | --- |
| Agent 载体 | App 表 + AppConfig | App 表继续作为 Agent 的唯一 DB 载体，AppConfig.preset_prompt 存储提示词 |
| Agent 元数据 | App.agent_metadata(JSONB) | 继续使用 JSONB 存储结构化元数据，池治理层读写此字段 |
| 工具绑定 | AppConfig.tools/mcp_bindings/skills/workflows/agent_bindings/datasets | 继续作为工具绑定的配置入口 |
| 工具执行抽象 | LangChain BaseTool | 所有工具统一转成 BaseTool 被 Agent 调用 |
| Builtin 工具 | builtin_provider_manager + providers.yaml | 直接复用，纳入治理 |
| API 工具 | ApiTool + ApiToolProvider + OpenAPI 解析 | 直接复用，纳入治理 |
| MCP 工具 | McpProvider + McpToolFactory | 直接复用，纳入治理 |
| Workflow 工具 | WorkflowTool(BaseTool) | 直接复用，纳入治理 |
| Skill 工具 | SkillToolFactory + SkillPackage | 直接复用，纳入治理 |
| Agent 委派 | agent_binding 包装成委派工具 | 直接复用，纳入治理 |
| 候选收集 | AgentCandidateCollector 从 App 表收集 | 复用收集逻辑，增加治理过滤层 |

#### 4.3.2 需要重组的偏离部分

| 偏离点 | 现状问题 | 修正方向 |
| --- | --- | --- |
| AgentPoolConfig 是孤岛 | AgentCandidateCollector 不读 AgentPoolConfig | AgentPoolConfig 改为 App 的路由元数据扩展，AgentCandidateCollector 读取做过滤 |
| ToolGovernancePolicy 是孤岛 | 运行时不读治理策略 | 在 RuntimeToolMountService 挂载工具前注入 ToolPolicyFilter 校验 |
| 工具来源类型不完整 | ToolSourceType 仅 4 种，workflow/skill/agent_binding 绕开 | 扩展 ToolSourceType，所有可被调用的资源都纳入 |
| 池治理与运行时两套体系 | 治理表自循环，运行时走 AppConfig 绕开 | 统一入口：AppConfig 绑定的工具经 ToolPolicyFilter 过滤后挂载 |
| Agent 元数据缺 prompt 字段 | 文档 9.1 节未设计 prompt 字段 | 补充 preset_prompt 字段到 Agent 元数据定义 |



## 5. 目标架构

### 5.1 简明总体链路

简明链路用于统一产品和研发心智：

```text
用户
  -> /home 主入口
  -> 指挥官 Conductor（单次 LLM 输出编排计划）
  -> direct_answer 直接回复 / single_agent / multi_agent
  -> 动态 Agent 子集
  -> 动态工具子集
  -> 下游 Agent 执行
  -> 结果汇总
  -> SSE 返回用户
```

该链路表达的是产品目标：普通用户只输入需求，指挥官一次性完成意图识别、复杂度判断、任务拆解和执行模式选择，输出结构化 ConductorPlan，由下游执行器执行。指挥官取代了原 Orchestrator 中 TaskClassifier + TaskPlanner + PoolIntentResolver + ExecutionModeSelector 四个模块的串行调用，用单次 LLM structured_output 实现一体化决策。

### 5.2 详细分层架构

```text
┌────────────────────────────────────────────────────────────┐
│ 1. 用户入口层                                                │
│ /home 输入框、图片/文件输入、SSE 流式展示、普通用户黑盒体验     │
└──────────────────────────────┬─────────────────────────────┘
                               │
                               ▼
┌────────────────────────────────────────────────────────────┐
│ 2. 指挥官决策层 Conductor Runtime                            │
│ ConductorService                                             │
│ - 单次 LLM structured_output 输出完整编排计划                  │
│ - 意图识别 + 复杂度判断 + 任务拆解 + 执行模式选择 一体化        │
│ - direct_answer 模式直接回复（不经 Agent，系统承担成本）        │
│ - single_agent / multi_agent / reject_or_confirm 派发         │
│ - model_tier (1/2/3) + capability 自动升级 (vision→4/long→5)  │
│ - Prompt 从 prompt_template 表加载（admin 后台可编辑）         │
│ - 硬约束校验失败回退 single_agent，保证系统可用性               │
└──────────────────────────────┬─────────────────────────────┘
                               │
                               ▼
┌────────────────────────────────────────────────────────────┐
│ 3. Agent 多子池动态归集层                                    │
│ AgentPoolService                                             │
│ - AgentSubPoolRegistry 管理编程、办公、数据、研究等子池          │
│ - AgentInventory 从相关子池读取可治理 Agent                    │
│ - AgentCandidateCollector 在每个相关子池内召回候选 Agent        │
│ - AgentPolicyFilter 按用户权限、可见性、风险、成本过滤           │
│ - AgentRanker 按能力、质量、延迟、成本、历史成功率排序            │
│ - CrossPoolAgentSubsetBuilder 形成跨子池 Agent 子集             │
└──────────────────────────────┬─────────────────────────────┘
                               │
                               ▼
┌────────────────────────────────────────────────────────────┐
│ 4. 工具多子池动态归集层                                      │
│ ToolPoolService                                              │
│ - ToolSubPoolRegistry 管理 MCP/API/Builtin/KB/Workflow 子池    │
│ - ToolInventory 从相关工具子池读取可治理工具                    │
│ - ToolCandidateCollector 按任务和 Agent 需求召回候选工具         │
│ - ToolPolicyFilter 按权限、风险、健康、成本、作用域过滤           │
│ - ToolRanker 按相关性、成功率、延迟、稳定性排序                  │
│ - CrossPoolToolSubsetBuilder 生成每个 Agent 可见工具子集         │
│ - RuntimeToolMountService 将工具子集转换为运行时 tools          │
└──────────────────────────────┬─────────────────────────────┘
                               │
                               ▼
┌────────────────────────────────────────────────────────────┐
│ 5. 模型池与 Key 池治理层                                     │
│ ModelGateway                                                 │
│ - ModelPool 管理模型供应商、模型档位、能力、价格和限流           │
│ - KeyPool 管理供应商 Key、租户配额、健康状态和熔断               │
│ - ModelAssignmentPolicy 支持管理员为每个 Agent 配置底座模型      │
│ - BillingMetering 将内部明细成本转换为用户侧统一扣费             │
└──────────────────────────────┬─────────────────────────────┘
                               │
                               ▼
┌────────────────────────────────────────────────────────────┐
│ 6. 执行编排层                                                │
│ ExecutionCoordinator                                         │
│ - DirectAnswerExecutor 简单任务快速回答                       │
│ - SingleAgentExecutor 单 Agent 执行                           │
│ - MultiAgentExecutor 多 Agent 并行/串行执行                    │
│ - DeepThinkingExecutor 复杂任务深度执行                        │
│ - A2AClient 调用下游 Agent                                    │
│ - ToolInvoker 工具调用、schema 校验、超时、重试、错误封装         │
│ - FallbackManager 模型/Agent/工具失败后的降级路径               │
└──────────────────────────────┬─────────────────────────────┘
                               │
                               ▼
┌────────────────────────────────────────────────────────────┐
│ 7. 结果汇总与质量控制层                                      │
│ ResultSynthesizer                                            │
│ - AgentResultNormalizer 标准化下游 Agent 输出                  │
│ - EvidenceMerger 合并证据和工具结果                           │
│ - ConflictResolver 处理结果冲突                               │
│ - QualityChecker 检查完整性、置信度、风险提示                   │
│ - FinalAnswerComposer 面向用户生成最终答案                     │
└──────────────────────────────┬─────────────────────────────┘
                               │
                               ▼
┌────────────────────────────────────────────────────────────┐
│ 8. 可观测性与治理层                                          │
│ RoutingObservabilityService                                 │
│ - 路由日志、Agent 选择日志、工具过滤日志、模型成本日志            │
│ - SSE 调度事件、审计日志、失败原因、fallback 原因                │
│ - 管理员运营面板、成本面板、质量评估、日志保留策略                │
└────────────────────────────────────────────────────────────┘
```

### 5.3 核心模块清单

| 模块 | 职责 | 阶段定位 |
| --- | --- | --- |
| ConductorService | 指挥官决策层，单次 LLM 输出完整编排计划（意图+复杂度+拆解+执行模式） | Phase 1 |
| PromptSyncService | Prompt 模板管理，YAML→DB 单向同步，admin 后台可编辑 | Phase 1 |
| AgentSubPoolRegistry | 管理编程、办公、数据、研究、图像等 Agent 子池 | Phase 2 |
| AgentInventory | 从相关 Agent 子池读取可治理 Agent 及元数据 | Phase 2 |
| AgentCandidateCollector | 根据任务从相关 Agent 子池分别召回候选 Agent | Phase 2 |
| AgentPolicyFilter | 根据用户权限、Agent 可见性、风险、成本过滤候选 | Phase 2 |
| AgentRanker | 根据能力匹配、质量、延迟、成本、成功率排序 | Phase 2 |
| CrossPoolAgentSubsetBuilder | 合并多个子池候选，生成本次任务可用 Agent 子集 | Phase 2 |
| ToolSubPoolRegistry | 管理 MCP、API、Builtin、知识库、工作流等工具子池 | Phase 3 |
| SystemKnowledgeService | 管理系统级知识库，服务 Agent 操作规范、工具使用经验和平台规则 | Phase 3 |
| UserMemoryService | 管理用户长期记忆库，服务用户偏好、习惯和长期个性化规则 | Phase 3 |
| UserContentKnowledgeService | 管理用户资料内容库，服务用户上传文档、图片、视频、音频等资料检索 | Phase 3 |
| ToolInventory | 从相关工具子池读取 MCP、API Tool、Builtin Tool、知识库、工作流工具 | Phase 3 |
| ToolCandidateCollector | 根据任务和 Agent 需求从相关工具子池召回候选工具 | Phase 4 |
| ToolPolicyFilter | 根据权限、风险、健康、成本、工具作用域过滤候选 | Phase 4 |
| ToolRanker | 根据相关性、成功率、延迟、稳定性排序 | Phase 4 |
| CrossPoolToolSubsetBuilder | 合并多个工具子池候选，生成本次 Agent 可见工具子集 | Phase 4 |
| RuntimeToolMountService | 将工具子集转换为 LangChain tools 或现有运行时工具 | Phase 4 |
| ModelPool | 管理模型供应商、档位、能力、价格、限流和健康状态 | Phase 5 |
| KeyPool | 管理模型 Key、租户配额、轮询、熔断和故障切换 | Phase 5 |
| BillingMetering | 汇总模型、工具、Agent 的 usage_delta，实时推送用户侧扣费 | Phase 5 |
| ExecutionCoordinator | 协调 direct、single-agent、multi-agent、deep-thinking、fallback | Phase 6 |
| ToolInvoker | 统一工具调用、schema 校验、超时、重试、错误封装 | Phase 4 |
| ResultSynthesizer | 汇总 Agent 和工具结果，统一整理后返回用户 | Phase 6 |
| QualityChecker | 检查结果完整性、冲突、置信度和风险 | Phase 6 |
| RoutingObservabilityService | 记录调度决策、模型成本、Agent/工具选择、失败原因 | Phase 7 |

> **v5.2 架构变更说明**：原 `OrchestratorService` + `TaskClassifier` + `TaskPlanner` + `PoolIntentResolver` + `CostPolicyService` + `ExecutionModeSelector` 六个串行模块已被 `ConductorService` 替代。指挥官用单次 LLM `structured_output` 一体化完成意图识别、复杂度判断、任务拆解和执行模式选择，消除了多模块串行的延迟和上下文丢失问题。`CostPolicyService` 的预算判断职责合并到指挥官 prompt 中（budget_level + balance_credits 作为上下文输入）。

### 5.4 目标数据流

```text
1. 用户在 /home 输入需求。
2. 指挥官 ConductorService 从 prompt_template 表加载系统 prompt（admin 后台可编辑）。
3. 构建 Agent 池摘要 + 模型池摘要 + 用户上下文（query/会话摘要/预算/图片数量）。
4. 单次 LLM structured_output 输出 ConductorPlan：
   - execution_mode: direct_answer / single_agent / multi_agent / reject_or_confirm
   - intent + complexity + reason（决策解释）
   - agents[]：每个子任务的 agent_pool / required_capabilities / model_tier / depends_on
   - direct_answer（直接回复内容，不经 Agent）
5. 硬约束校验（agent 数量 ≤ MAX_AGENTS、model_tier 合法、依赖关系合法），失败回退 single_agent。
6. 如果 direct_answer：经 BillingUsageAggregator 直接返回（系统承担成本，不扣用户额度）。
7. 如果需要 Agent，AgentCandidateCollector 从相关 Agent 子池分别召回候选 Agent。
8. AgentPolicyFilter 过滤未授权、不可见、风险不匹配、成本不允许的 Agent。
9. AgentRanker 在子池内和跨子池排序，CrossPoolAgentSubsetBuilder 裁剪出本次任务 Agent 子集。
10. 对每个被选中 Agent，ToolCandidateCollector 根据任务、Agent 能力、允许工具类别从相关工具子池召回候选工具。
11. ToolPolicyFilter 过滤未授权、高风险、不健康、超作用域工具。
12. ToolRanker 在子池内和跨子池排序，CrossPoolToolSubsetBuilder 裁剪出本次 Agent 可见工具子集。
13. RuntimeToolMountService 将工具子集转换为运行时 tools，只挂载给对应 Agent。
14. 模型档位对齐：指挥官 model_tier (1/2/3 算力档位) + capability 自动升级 (vision→4, long_context→5)，与 fallback_tier (1-5 能力档位) 体系对齐。
15. ModelGateway 从模型池和 Key 池中选择可用模型和 Key，支持管理员对 Agent 的底座模型配置。
16. ExecutionCoordinator 执行 direct/single/multi/deep 路径，Agent 间通过 A2A 协作，工具通过统一 ToolInvoker 调用。
17. AgentResultNormalizer 将不同 Agent 输出标准化。
18. ResultSynthesizer 合并结果、处理冲突、隐藏内部细节、生成最终答案。
19. RoutingObservabilityService 记录全链路决策、候选、过滤原因、成本、错误。
20. 前端通过 SSE 展示低细节进度和最终答案，管理员可在后台查看高细节日志。
```

### 5.5 Agent 子集与工具子集的核心约束

目标架构中，模型不能直接面对完整 Agent 池或完整工具池。更准确地说，系统也不应该只有一个"大池子"，而应该是多个按领域、能力和工具类型拆分的小池子。

```text
任务 -> 识别相关 Agent 子池 -> 子池内候选召回 -> 策略过滤 -> 排序裁剪 -> 跨池 Agent 子集
任务 + 选中 Agent -> 识别相关工具子池 -> 子池内候选召回 -> 策略过滤 -> 排序裁剪 -> 每个 Agent 的工具子集
```

示例：

```text
用户需求：帮我把这张产品图优化一下，并生成一个前端落地页代码
  -> 图片 / 设计子任务：从办公或图像 Agent 子池召回 P 图、视觉优化 Agent
  -> 编程子任务：从编程 Agent 子池召回 UI、前端 Agent
  -> 工具子集：图像处理 MCP / 设计工具 + 代码生成工具 / 文件工具
  -> A2A 多 Agent 协作执行
  -> 主入口统一汇总结果
```

这两个"跨子池动态子集"是系统可控性的核心：

1. 降低上下文噪声，避免把几十上百个 Agent 或工具塞给模型。
2. 限制权限边界，避免普通用户或低风险 Agent 调用敏感工具。
3. 控制成本，避免简单任务误触发强 Agent 或高成本工具。
4. 提高路由质量，让模型只在高相关候选中做选择。
5. 支持跨领域任务，例如同时涉及图片、代码、文档、数据分析。
6. 保持 MCP 与 A2A 的职责边界：MCP 是工具池能力，A2A 是 Agent 协作通道。



## 6. 设计原则

### 6.1 默认简单，必要时复杂

系统不应所有任务都走多 Agent 和强模型。默认策略应为：

```text
简单问题 -> 便宜模型直接回答
中等问题 -> 单 Agent 执行
需要工具 -> 单 Agent + 少量工具
复杂问题 -> 强模型 / 深度思考 / 多 Agent
高风险任务 -> 请求确认或拒绝执行
```

### 6.2 LLM 负责语义，策略负责边界

LLM 可以判断用户意图，但不能决定安全边界。

必须由确定性策略控制：

- 用户权限。
- 工具权限。
- 高风险操作。
- 成本上限。
- 模型档位。
- 是否允许创建、修改、删除。

### 6.3 工具池可检索，不可无约束调用

Agent 不应面对完整工具池。每次执行只允许看到：

```text
任务相关 + 用户授权 + Agent 授权 + 风险可接受 + 成本可接受 + 健康可用
```

的工具子集。

### 6.4 Agent 池必须结构化

Agent 不应只依赖名称和描述被路由。每个可调度 Agent 需要结构化元数据。

### 6.5 调度过程必须可观测

每次主入口调用必须回答：

- 为什么用这个模型？
- 为什么选这个 Agent？
- 为什么调用这些工具？
- 花了多少成本？
- 哪里失败了？
- 是否发生 fallback？



## 7. 角色与使用边界

### 7.1 管理员

管理员负责：

- 配置 Agent。
- 配置 MCP 和工具。
- 配置模型档位。
- 配置工具风险等级。
- 配置 Agent 可使用的工具类别。
- 配置用户可使用的能力。
- 查看路由日志和成本日志。
- 调优 Agent 描述、标签和策略。

### 7.2 普通用户

普通用户负责：

- 在主入口输入需求。
- 查看结果。
- 使用已分配能力。
- 创作分身（满足准入门槛后，通过创作工作室 `/studio` 入口）。

普通用户不应看到：

- 配置中心。
- Agent 池内部。
- 工具池内部。
- 模型选择细节。
- Prompt 和工具参数。
- 路由候选和过滤细节。

普通用户在创作上下文中可以看到：

- 自己创作的分身列表与草稿。
- 自己分身的调用数据与收益。
- 其他创作者的公开主页与已发布分身。
- 但仍不可看到池治理、路由策略、系统资源配置等管理端内容。

### 7.3 系统

系统负责：

- 自动选择模型。
- 自动选择 Agent。
- 自动选择工具。
- 控制成本。
- 控制权限和风险。
- 汇总结果。
- 记录全链路日志。


---

> **以下章节已拆分至子文档，请点击链接查看完整内容。**

## 8. 动态子集归集与策略过滤设计

> 内容已拆分至子文档，本节为标题索引。

子节索引：
- 8.1 为什么需要动态子集
- 8.2 Agent 多子池归集流程
- 8.3 跨子池 Agent 子集输出
- 8.4 工具多子池归集流程
- 8.5 跨子池工具子集输出
- 8.6 RuntimeToolMountService
- 8.7 执行前约束与执行后校验

## 9. Agent 池设计

> 内容已拆分至子文档，本节为标题索引。

子节索引：
- 9.1 Agent 元数据
- 9.2 Agent 子池设计
- 9.3 Agent 来源
- 9.4 Agent 路由策略

## 10. 工具池设计

> 内容已拆分至子文档，本节为标题索引。

子节索引：
- 10.1 工具池范围与统一抽象
- 10.2 工具元数据与治理映射
- 10.3 工具风险等级
- 10.4 动态工具检索原则
- 10.5 池治理与运行时打通

详见子文档：[modules/01-agent-tool-pool.md](./modules/01-agent-tool-pool.md)


## 11. 知识库双层设计

> 内容已拆分至子文档，本节为标题索引。

子节索引：
- 11.1 系统级知识库
- 11.2 管理员身份与知识库归属边界
- 11.3 用户个人知识库（11.3.1 用户长期记忆库 / 11.3.2 用户资料内容库 / 11.3.3 两类差异对比）
- 11.4 检索优先级与隔离策略
- 11.5 现有知识库能力评估
- 11.6 与工具池的关系

详见子文档：[modules/02-knowledge-base.md](./modules/02-knowledge-base.md)


## 12. 模型路由、模型池、Key 池与成本控制

> 内容已拆分至子文档，本节为标题索引。

子节索引：
- 12.1 模型档位（含 12.1.1 模型池与 Key 池）
- 12.2 复杂度判断
- 12.3 成本策略（含 12.3.1 实时计费与手动终止）
- 12.4 模型升级策略

## 13. Orchestrator 执行模式

> 内容已拆分至子文档，本节为标题索引。

子节索引：
- 13.1 执行模式
- 13.2 快速路径
- 13.3 复杂路径

## 14. ResultSynthesizer 设计

> 内容已拆分至子文档，本节为标题索引。

子节索引：
- 14.1 输入
- 14.2 输出
- 14.3 职责
- 14.4 与记忆系统的集成

## 15. 可观测性与审计

> 内容已拆分至子文档，本节为标题索引。

子节索引：
- 15.1 必须记录的事件
- 15.2 管理员可见信息
- 15.3 日志保留与脱敏策略

详见子文档：[modules/03-orchestration-infra.md](./modules/03-orchestration-infra.md)


## 16. 脑启发记忆系统（v5.0 新增）

> 内容已拆分至子文档，本节为标题索引。

概览子节索引（[memory-system/00-overview.md](./memory-system/00-overview.md)）：
- 16.1 设计原则
- 16.2 脑启发架构映射
- 16.3 最小闭包抽象：(Ledger, Views, Policy)
- 16.4 System 1 / System 2 双系统架构
- 16.5-16.15 详细内容索引
- 16.11 技术栈适配（PostgreSQL 18 + pgvector + Neo4j）
- 16.14 实现路线图（P0-P5）
- 16.15 与知识库系统的集成关系

详细实现见三个专题子文档：
- [memory-system/01-data-models-and-write-path.md](./memory-system/01-data-models-and-write-path.md) — 数据模型与写入路径
- [memory-system/02-storage-and-retrieval.md](./memory-system/02-storage-and-retrieval.md) — 存储层与读取路径
- [memory-system/03-consolidation-skill-policy-api.md](./memory-system/03-consolidation-skill-policy-api.md) — 巩固引擎、技能池、Policy 与 API


## 17. 文件存储与对象存储架构

> 内容已拆分至子文档，本节为标题索引。

子节索引：
- 17.1 设计目标
- 17.2 架构分层（端口 + 工厂 + 三后端）
- 17.3 核心组件（ObjectStoragePort / StorageBackend / StorageFactory）
- 17.4 后端实现（LocalStorageService / CosService / AliyunOSSService）
- 17.5 配置项清单
- 17.6 文件元数据模型
- 17.7 文件上传调用链
- 17.8 切换后端操作指南
- 17.9 与记忆系统冷存储的关系
- 17.10 安全要求
- 17.11 后续演进路线

详见子文档：[modules/06-file-storage.md](./modules/06-file-storage.md)


## 18. 社交社区架构设计（v4.0 新增）

> 内容已拆分至子文档，本节为标题索引。

子节索引：
- 18.1 社区架构分层
- 18.2 会话分享与导出
- 18.3 用户主页与内容流
- 18.4 AI 辅助社交
- 18.5 隐私与安全边界

## 19. 用户共创分身与创作者经济

> 内容已拆分至子文档，本节为标题索引。

子节索引：
- 19.1 核心概念定义
- 19.2 分身与现有架构的关系
- 19.3 创作门槛分层设计（L0 模板 / L1 对话 / L2 编排 / L3 代码）
- 19.4 质量门槛与审核成本控制
- 19.5 积分经济模型
- 19.6 用户侧创作入口
- 19.7 管理端资源运营板块的新定位
- 19.8 分身入池与治理
- 19.9 第一阶段范围与后续演进

详见子文档：[modules/04-social-creator.md](./modules/04-social-creator.md)


## 20. 安全要求

> 内容已拆分至子文档，本节为标题索引。

子节索引：
- 20.1 权限边界
- 20.2 Prompt 注入防护
- 20.3 高风险工具策略

## 21. 关键风险与应对

> 内容已拆分至子文档，本节为标题索引。

本章为整体内容，包含 8 项关键风险与应对矩阵（成本失控 / 路由不稳 / 工具误用 / 安全越权 / 响应变慢 / 结果冲突 / 过度设计 / 破坏现有功能）。

## 22. Feature Flag 与回滚策略

> 内容已拆分至子文档，本节为标题索引。

本章为整体内容，包含 7 个 Feature Flag 开关（ENABLE_ORCHESTRATOR / ENABLE_AGENT_METADATA_ROUTING / ENABLE_TOOL_POOL_RETRIEVAL / ENABLE_COST_MODEL_ROUTING / ENABLE_MULTI_AGENT_EXECUTION / ENABLE_RESULT_SYNTHESIZER / ENABLE_ROUTING_LOGS）及回滚原则。

## 23. 成功指标

> 内容已拆分至子文档，本节为标题索引。

子节索引：
- 23.1 产品指标
- 23.2 成本指标
- 23.3 路由指标
- 23.4 工程指标

## 24. 公共 AI 资源配置板块（v5.1 新增）

> 内容已拆分至子文档，本节为标题索引。

子节索引：
- 24.1 背景与定位（含 24.1.1 问题定义 / 24.1.2 设计目标 / 24.1.3 设计原则）
- 24.2 数据模型（含 24.2.1 `public_ai_feature_config` 表 / 24.2.2 索引与约束 / 24.2.3 Alembic 迁移）
- 24.3 23 个预置功能清单（24.3.1 图标类 2 个 / 24.3.2 记忆系统类 11 个 / 24.3.3 路由类 1 个 / 24.3.4 助手类 4 个 / 24.3.5 对话类 4 个 / 24.3.6 平台资源类 1 个 / 计费汇总 8 billable + 15 非 billable）
- 24.4 模型取用策略（含 24.4.1 `get_feature_model` 三级回退 / 24.4.2 `model_type` 过滤防类型错配 / 24.4.3 40+ 调用点改造）
- 24.5 计费集成（含 24.5.1 `CreditService.consume_for_feature` / 24.5.2 8 个 billable 调用点集成 / 24.5.3 失败处理）
- 24.6 架构理念与最佳实践（含 24.6.1 记忆系统精准度优先异步执行 / 24.6.2 模型选择原则 / 24.6.3 降级策略层级 / 24.6.4 异步精准架构）
- 24.7 Admin 后台管理（菜单位置 / 列表页 / 编辑页仅 3 字段可编辑 / API 端点 / 权限）
- 24.8 与其他模块的集成（§12 模型路由 / §16 记忆系统 / §13 Orchestrator / 计费系统）
- 24.9 实施验证清单
- 24.10 后续演进

详见子文档：[modules/07-public-ai-config.md](./modules/07-public-ai-config.md)

## 25. 指挥官架构与 Prompt 模板管理（v5.2 新增）

### 25.1 指挥官 ConductorService

指挥官是 v5.2 引入的决策层，取代了原 Orchestrator 中 TaskClassifier + TaskPlanner + PoolIntentResolver + ExecutionModeSelector 四个串行模块。

#### 25.1.1 设计动机

原 Orchestrator 多模块串行存在三个问题：
1. **延迟累积**：每个模块独立调用 LLM，4 次串行调用延迟叠加
2. **上下文丢失**：模块间传递的是结构化字段，原始用户请求的语义在传递中衰减
3. **决策不一致**：分类和拆解分两步做，可能出现分类判定与拆解策略矛盾

指挥官用单次 LLM `with_structured_output(ConductorPlanModel)` 一体化输出完整编排计划，解决上述问题。

#### 25.1.2 输入

| 输入 | 来源 | 说明 |
|---|---|---|
| 用户请求 | /home 输入 | 原始 query |
| 会话摘要 | ConversationService | 上下文压缩摘要 |
| 预算等级 | budget_level | normal/strict/loose |
| 余额 | balance_credits | 用户剩余积分 |
| 图片数量 | image_url_count | 输入模态判断 |
| Agent 池摘要 | _build_agent_pool_summary | 轻量，仅 name+label+description+capabilities+task_keywords |
| 模型池摘要 | _build_model_summary | 从向量索引查询，仅 model_id+name+capabilities+cost_tier |
| 系统 Prompt | prompt_template 表 | admin 后台可编辑，YAML→DB 同步 |

#### 25.1.3 输出 ConductorPlan

```json
{
  "execution_mode": "direct_answer | single_agent | multi_agent_parallel | multi_agent_sequential | reject_or_confirm",
  "intent": "任务意图简述",
  "complexity": "simple | moderate | complex",
  "reason": "决策原因",
  "direct_answer": "直接回复内容（仅 direct_answer 模式）",
  "agents": [
    {
      "task_id": "t1",
      "title": "子任务标题",
      "description": "子任务描述",
      "agent_pool": "general | coding | office | data | research",
      "required_capabilities": ["coding", "translation"],
      "model_tier": "1 | 2 | 3",
      "depends_on": [],
      "risk_level": "safe | medium | high",
      "expected_output": "期望输出说明"
    }
  ],
  "aggregation_strategy": "concat | summarize | best_of",
  "risk_level": "safe | medium | high",
  "estimated_cost_tier": "low | medium | high"
}
```

#### 25.1.4 模型档位对齐机制

指挥官输出的 `model_tier` (1/2/3) 是算力档位，与 `public_ai_feature_config.fallback_tier` (1-5) 能力档位体系需要对齐：

| 指挥官 model_tier | 含义 | 对应 fallback_tier |
|---|---|---|
| 1 | 轻量省钱 | 1 (cheap) |
| 2 | 标准 | 2 (standard) |
| 3 | 强模型 | 3 (premium) |
| 4（自动升级） | 视觉模型 | 4 (vision)，required_capabilities 含 vision 时触发 |
| 5（自动升级） | 长上下文模型 | 5 (long_context)，required_capabilities 含 long_context 时触发 |

升级规则：`_resolve_effective_tier(agent)` 取 model_tier 和 capability 升级档位中的较高值。

#### 25.1.5 硬约束校验

校验失败自动回退 `single_agent` 模式，保证系统可用性：
1. execution_mode 必须是枚举值之一
2. direct_answer 模式下 agents 必须为空
3. agent 数量 ≤ MAX_AGENTS_PER_PLAN
4. model_tier 必须是 1/2/3 之一
5. multi_agent_parallel 模式下 depends_on 必须为空

#### 25.1.6 计费隔离

| 执行模式 | 计费方式 |
|---|---|
| direct_answer | 指挥官 LLM 成本由系统承担，经 BillingUsageAggregator 返回，**不扣用户额度** |
| single_agent / multi_agent | 下游 Agent 执行成本由用户承担，正常扣费 |

direct_answer 路径不调用 `CreditService.consume_for_feature`，避免双重计费（系统承担指挥官成本 + 用户承担回答成本）。

### 25.2 Prompt 模板管理

#### 25.2.1 设计目标

将系统级 prompt（如指挥官 prompt）从硬编码迁移到数据库管理，支持 admin 后台编辑，无需修改代码或配置文件。

#### 25.2.2 数据模型 prompt_template 表

| 字段 | 类型 | 说明 |
|---|---|---|
| prompt_key | VARCHAR(64) PK | prompt 标识，如 `conductor` |
| name | VARCHAR(128) | 显示名称 |
| category | VARCHAR(64) | 分类，如 `routing` |
| description | TEXT | 描述说明 |
| content | TEXT | prompt 正文，支持 `{变量名}` 插值 |
| variables | JSONB | 变量声明 |
| source | VARCHAR(32) | `catalog`（YAML 同步）/ `custom`（admin 编辑后标记） |
| source_path | VARCHAR(512) | YAML 源文件路径，reset 时用于重新加载 |
| content_hash | VARCHAR(128) | 内容哈希，用于同步去重 |
| enabled | BOOLEAN | 是否启用 |
| version | INTEGER | 版本号，每次编辑 +1 |

#### 25.2.3 YAML→DB 单向同步

```
api/internal/core/prompts/
├── index.yaml          # prompt 索引，列出所有 prompt_key 和文件路径
└── routing/
    └── conductor.yaml  # 指挥官 prompt 原始内容
```

同步规则（`PromptSyncService.sync_yaml_to_db`）：
1. 应用启动时执行一次
2. `source=catalog` 的记录：content_hash 不匹配时更新内容
3. `source=custom` 的记录：**跳过，不覆盖** admin 的编辑

#### 25.2.4 Admin 后台管理

融合进"系统知识库"板块的 Prompt 模板页签：

| 操作 | API | 说明 |
|---|---|---|
| 列表 | GET /admin/prompt-templates | 支持分类/启用状态过滤 |
| 详情 | GET /admin/prompt-templates/{prompt_key} | 返回完整 content |
| 编辑 | PATCH /admin/prompt-templates/{prompt_key} | 更新 content/description/enabled，source 标记为 custom |
| 重置 | POST /admin/prompt-templates/{prompt_key}/reset | 从 source_path 指向的 YAML 文件重新加载，source 改回 catalog |

#### 25.2.5 运行时读取

`PromptSyncService.get_prompt(prompt_key, **variables)`：
1. 从 DB 查询 enabled=True 的记录
2. 用 variables 填充 `{变量名}` 插值
3. 返回填充后的 prompt 字符串
4. 查询失败时调用方使用兜底 prompt（如 `_FALLBACK_CONDUCTOR_PROMPT`）


## 26. 已确认决策与后续讨论点

> 内容已拆分至子文档，本节为标题索引。

子节索引：
- 26.1 已确认决策（41 条）
- 26.2 设计决策与未解决问题（6 条已确认设计决策 + Knowledge Convergence Note）

## 27. 总结

> 内容已拆分至子文档，本节为标题索引。

本章为整体内容，包含演进路径总结（主路径 + 社区与创作者经济支线）与后续推荐路径。

详见子文档：[modules/05-security-risk-decisions.md](./modules/05-security-risk-decisions.md)
