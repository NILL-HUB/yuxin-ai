# OpenAgent 架构设计文档

> **文档信息**
>
> | 项 | 值 |
> |---|---|
> | 文档名称 | OpenAgent 通用 Agent 调度平台 — 架构设计 |
> | 版本 | v1.0 |
> | 日期 | 2026-06-30 |
> | 定位 | 只描述产品方向、目标架构与模块设计方案，不包含执行计划与任务拆分 |
> | 配套文档 | execution-roadmap.md（分阶段任务与执行路线） |

---

本文档定义 OpenAgent 的目标架构与核心模块设计方案。系统应从"可配置 Agent 应用平台"演进为"通用 Agent 调度平台"：管理员配置能力，用户自然语言提出需求，系统自动选择模型、Agent 和工具完成任务。

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

把 OpenAgent 从“可配置 Agent 应用平台”升级为“通用 Agent 调度平台”：管理员配置能力，用户自然语言提出需求，系统自动选择合适模型、合适 Agent 和合适工具完成任务，并以统一、可靠、成本可控的方式返回结果。

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
| 缺少 Orchestrator | 主入口仍是一个 Agent，而不是显式调度流程 | 路由、模型、工具、汇总不可控 |
| 缺少 Agent 池元数据 | App 主要依赖名称和描述 | 路由质量不稳定 |
| 缺少共享工具池动态检索 | 工具主要按 AppConfig 预绑定 | 工具复用差、配置重复、上下文膨胀 |
| 缺少成本感知模型路由 | 没有模型档位、价格、预算策略 | 成本不可控 |
| 缺少显式结果汇总器 | 结果主要由 LLM 工具调用后自然整合 | 多 Agent 结果质量不稳定 |
| 缺少调度日志 | agent_thoughts 不是完整调度审计 | 难以调试路由和成本 |
| 工具权限粒度不足 | MCP 有 public/private，但缺少风险、权限、审批 | 动态工具池上线风险高 |
| TaskClassifier 仍依赖关键词匹配 | 实际代码 task_classifier_service.py 用关键词匹配（删库/drop table/rm -rf），仅 deep_thinking 用 LLM | 分类智能度不足，路由质量不稳定 |
| MultiAgentExecutor 名不副实 | multi_agent_executor.py 只创建单个 TaskPlanItem，无真正多 Agent 并行/串行编排 | 复杂任务无法分解并行 |
| 长期记忆提取能力严重不足 | long_term_memory_service.py 的 MemoryCandidateExtractor 硬编码只识别"中文"语言偏好 | 无法记住用户画像，每次对话像第一次见面 |
| 知识库 RAG 检索链路缺失 | knowledge_base_service.py 仅有 CRUD，未见向量索引构建/chunking/embedding/相似度召回 | 用户上传文档后 AI 无法检索使用 |
| 上下文管理过于基础 | token_buffer_memory.py 用 trim_messages(strategy="last", max_tokens=2000) 直接截断早期消息 | 长对话丢失关键信息 |
| 缺少日常生活类工具 | 20 个内置工具全偏信息查询/内容生成，无邮件/日历/社交媒体/支付/任务管理 | 无法覆盖工作+生活+社交全场景 |
| 缺少社交社区能力 | 无会话分享/导出、无用户主页、无内容流、无关注关系 | 无法支撑社交社区产品形态 |



### 4.3 底座能力复用与偏离修正

OpenAgent 已具备成熟的 Agent 应用平台底座，池治理改造不应推倒重来，而应区分“可复用”与“需重组”两类。

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
  -> 主入口调度器 Orchestrator
  -> 动态 Agent 子集
  -> 动态工具子集
  -> 下游 Agent 执行
  -> 主入口结果汇总
  -> SSE 返回用户
```

该链路表达的是产品目标：普通用户只输入需求，系统自动完成能力选择、工具选择、执行和汇总。但工程实现不能把 Agent 池、工具池直接暴露给模型，必须通过候选归集、策略过滤、排序裁剪和运行时挂载形成受控子集。

### 5.2 详细分层架构

```text
┌────────────────────────────────────────────────────────────┐
│ 1. 用户入口层                                                │
│ /home 输入框、图片/文件输入、SSE 流式展示、普通用户黑盒体验     │
└──────────────────────────────┬─────────────────────────────┘
                               │
                               ▼
┌────────────────────────────────────────────────────────────┐
│ 2. 主入口调度层 Orchestrator Runtime                         │
│ OrchestratorService                                          │
│ - RequestContextBuilder 构建用户/会话/权限/计费上下文          │
│ - TaskClassifier 判断意图、复杂度、风险、模态、工具需求          │
│ - TaskPlanner 将跨领域需求拆成结构化子任务                     │
│ - PoolIntentResolver 判断需要哪些 Agent 子池和工具子池          │
│ - CostPolicyService 选择模型档位、扣费策略和升级策略            │
│ - ExecutionModeSelector 选择 direct/single/multi/deep 路径     │
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
| RequestContextBuilder | 构建用户、会话、角色、权限、预算、输入模态上下文 | Phase 1 |
| OrchestratorService | 主入口总调度，串联分类、路由、执行、汇总 | Phase 1 |
| TaskClassifier | 判断意图、复杂度、是否需要工具、是否需要 Agent、是否需要深度执行 | Phase 1 |
| TaskPlanner | 将复杂任务拆分为结构化子任务 | Phase 6 |
| CostPolicyService | 根据复杂度、用户套餐、积分余额和策略选择模型档位与执行深度 | Phase 5 |
| AgentSubPoolRegistry | 管理编程、办公、数据、研究、图像等 Agent 子池 | Phase 2 |
| PoolIntentResolver | 根据任务识别需要访问哪些 Agent 子池和工具子池 | Phase 2 |
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

### 5.4 目标数据流

```text
1. 用户在 /home 输入需求。
2. RequestContextBuilder 构建上下文：account、role、conversation、membership、token_balance、input_modalities。
3. TaskClassifier 输出任务分类：intent、complexity、risk、needs_agent、needs_tools、needs_deep_thinking。
4. TaskPlanner 将跨领域需求拆成子任务，例如图片处理子任务、代码实现子任务、文档整理子任务。
5. PoolIntentResolver 判断每个子任务需要访问哪些 Agent 子池和工具子池。
6. CostPolicyService 输出模型策略：model_tier、max_agent_count、max_tool_count、billing_mode。
7. ExecutionModeSelector 判断执行模式：direct_answer / single_agent / multi_agent / deep_thinking / reject_or_confirm。
8. 如果需要 Agent，AgentCandidateCollector 从相关 Agent 子池分别召回候选 Agent。
9. AgentPolicyFilter 过滤未授权、不可见、风险不匹配、成本不允许的 Agent。
10. AgentRanker 在子池内和跨子池排序，CrossPoolAgentSubsetBuilder 裁剪出本次任务 Agent 子集。
11. 对每个被选中 Agent，ToolCandidateCollector 根据任务、Agent 能力、允许工具类别从相关工具子池召回候选工具。
12. ToolPolicyFilter 过滤未授权、高风险、不健康、超作用域工具。
13. ToolRanker 在子池内和跨子池排序，CrossPoolToolSubsetBuilder 裁剪出本次 Agent 可见工具子集。
14. RuntimeToolMountService 将工具子集转换为运行时 tools，只挂载给对应 Agent。
15. ModelGateway 从模型池和 Key 池中选择可用模型和 Key，支持管理员对 Agent 的底座模型配置。
16. ExecutionCoordinator 执行 direct/single/multi/deep 路径，Agent 间通过 A2A 协作，工具通过统一 ToolInvoker 调用。
17. AgentResultNormalizer 将不同 Agent 输出标准化。
18. ResultSynthesizer 合并结果、处理冲突、隐藏内部细节、生成最终答案。
19. RoutingObservabilityService 记录全链路决策、候选、过滤原因、成本、错误。
20. 前端通过 SSE 展示低细节进度和最终答案，管理员可在后台查看高细节日志。
```

### 5.5 Agent 子集与工具子集的核心约束

目标架构中，模型不能直接面对完整 Agent 池或完整工具池。更准确地说，系统也不应该只有一个“大池子”，而应该是多个按领域、能力和工具类型拆分的小池子。

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

这两个“跨子池动态子集”是系统可控性的核心：

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

普通用户不应看到：

- 配置中心。
- Agent 池内部。
- 工具池内部。
- 模型选择细节。
- Prompt 和工具参数。
- 路由候选和过滤细节。

### 7.3 系统

系统负责：

- 自动选择模型。
- 自动选择 Agent。
- 自动选择工具。
- 控制成本。
- 控制权限和风险。
- 汇总结果。
- 记录全链路日志。



## 8. 动态子集归集与策略过滤设计

### 8.1 为什么需要动态子集

如果主入口模型直接面对完整 Agent 池和完整工具池，会产生四类系统性问题：

1. **上下文噪声**：大量无关 Agent/工具描述会降低模型选择准确率。
2. **权限风险**：普通用户或低权限 Agent 可能通过 Prompt 注入触发敏感工具。
3. **成本风险**：简单任务可能误选强模型 Agent 或高成本工具。
4. **运维风险**：工具和 Agent 数量增长后，路由不可解释、不可调优。

因此目标架构必须把“完整池”变成“本次任务可见子集”。模型只在受控子集中做选择，而不是直接访问全量池。

### 8.2 Agent 多子池归集流程

```text
TaskContext
  -> PoolIntentResolver
  -> AgentSubPoolRegistry
  -> AgentInventory
  -> AgentCandidateCollector
  -> AgentPolicyFilter
  -> AgentRanker
  -> CrossPoolAgentSubsetBuilder
  -> AgentRouter
```

#### 8.2.1 AgentSubPoolRegistry

AgentSubPoolRegistry 管理多个 Agent 子池，而不是把所有 Agent 放进一个无差别大池。

示例子池：

| 子池 | 示例 Agent | 适用任务 |
| --- | --- | --- |
| coding | UI Agent、前端 Agent、后端 Agent、测试 Agent、DevOps Agent | 写代码、改代码、部署、排错 |
| office | P 图 Agent、文档整理 Agent、PPT Agent、表格 Agent | 办公处理、文档整理、图片处理 |
| data | 数据分析 Agent、报表 Agent、SQL Agent | 数据查询、分析、可视化 |
| research | 搜索研究 Agent、行业分析 Agent、竞品分析 Agent | 调研、报告、资料整理 |
| customer_service | 客服 Agent、工单 Agent、FAQ Agent | 用户支持、售后、知识问答 |
| internal_admin | 运维 Agent、审计 Agent、系统管理 Agent | 管理员内部维护，不对普通用户自动开放 |

PoolIntentResolver 根据任务识别相关子池。一个需求可以命中多个子池，例如“P 图 + 写代码”同时命中 office 和 coding。

#### 8.2.2 AgentInventory

AgentInventory 从相关子池读取可治理 Agent，来源包括：

- public App。
- assigned App。
- 管理员配置中心创建的 App。
- 内置轻量 Agent。
- 内置强推理 Agent。
- 深度思考 Agent。
- 外部 A2A Agent。

它不直接暴露给模型，只作为候选来源。

#### 8.2.3 AgentCandidateCollector

AgentCandidateCollector 负责按任务在相关 Agent 子池内分别召回候选 Agent。

召回信号包括：

- query 语义相似度。
- TaskClassifier 输出的 intent。
- required_capabilities。
- task_types。
- complexity。
- input_modalities。
- 用户已分配应用。
- public 应用。
- 管理员指定默认 Agent。

输出示例：

```json
{
  "task_id": "task-1",
  "raw_candidates": [
    {
      "agent_id": "agent-a",
      "source": "assigned",
      "match_reason": "capability:data_analysis",
      "semantic_score": 0.82
    },
    {
      "agent_id": "agent-b",
      "source": "public",
      "match_reason": "description_similarity",
      "semantic_score": 0.76
    }
  ]
}
```

#### 8.2.4 AgentPolicyFilter

AgentPolicyFilter 负责做硬过滤。

过滤维度包括：

| 维度 | 说明 |
| --- | --- |
| 用户权限 | 普通用户只能使用 public 或 assigned Agent |
| Agent 状态 | disabled、deleted、draft 不进入候选 |
| 风险等级 | 高风险 Agent 不对普通用户自动开放 |
| 成本策略 | 超预算 Agent 被过滤或降级 |
| 输入能力 | 不支持图片/文件/长上下文的 Agent 不能处理对应任务 |
| 工具策略 | 任务需要工具但 Agent 不允许使用工具池时过滤 |
| 管理员策略 | 管理员可调试更多 Agent，普通用户不可见 |

过滤输出必须保留原因：

```json
{
  "filtered_out": [
    {
      "agent_id": "agent-x",
      "reason": "not_assigned_to_user"
    },
    {
      "agent_id": "agent-y",
      "reason": "cost_level_exceeds_budget"
    }
  ]
}
```

#### 8.2.5 AgentRanker

AgentRanker 对过滤后的候选排序。

排序信号包括：

- 能力匹配分。
- 语义匹配分。
- 历史成功率。
- 质量评分。
- 延迟。
- 成本。
- 管理员优先级。
- 最近失败率。

建议初始公式：

```text
score = capability_score * 0.35
      + semantic_score * 0.25
      + quality_score * 0.20
      + cost_score * 0.10
      + latency_score * 0.05
      + priority_score * 0.05
```

### 8.3 跨子池 Agent 子集输出

CrossPoolAgentSubsetBuilder 输出本次任务允许使用的跨子池 Agent 子集。

```json
{
  "task_id": "task-1",
  "matched_agent_pools": ["office", "coding"],
  "max_agent_count": 3,
  "selected_agents": [
    {
      "agent_id": "agent-image-editor",
      "pool": "office",
      "role": "image_processing",
      "model_tier": "vision",
      "allowed_tool_categories": ["mcp:image", "builtin:file"],
      "selection_reason": "matches image editing subtask"
    },
    {
      "agent_id": "agent-frontend",
      "pool": "coding",
      "role": "frontend_implementation",
      "model_tier": "strong",
      "allowed_tool_categories": ["mcp:code", "builtin:file"],
      "selection_reason": "matches landing page coding subtask"
    }
  ],
  "backup_agents": [
    {
      "agent_id": "agent-general-coding",
      "pool": "coding",
      "role": "fallback",
      "selection_reason": "public coding fallback"
    }
  ]
}
```

### 8.4 工具多子池归集流程

```text
TaskContext + SelectedAgent
  -> PoolIntentResolver
  -> ToolSubPoolRegistry
  -> ToolInventory
  -> ToolCandidateCollector
  -> ToolPolicyFilter
  -> ToolRanker
  -> CrossPoolToolSubsetBuilder
  -> RuntimeToolMountService
```

#### 8.4.1 ToolSubPoolRegistry

ToolSubPoolRegistry 管理多个工具子池。MCP 只是工具子池的一种，不等同于 A2A。

示例子池：

| 子池 | 示例工具 | 适用任务 |
| --- | --- | --- |
| mcp | 搜索 MCP、图片 MCP、代码仓库 MCP、浏览器 MCP | 外部能力接入和标准化工具调用 |
| api | 企业业务 API、第三方服务 API | 业务系统集成 |
| builtin | 文件、代码执行、沙箱、格式转换 | 平台内置基础能力 |
| knowledge | 知识库检索、向量检索、文档问答 | 知识问答和资料检索 |
| workflow | 审批流、自动化流程、批处理流程 | 多步骤业务自动化 |
| sandbox_data | 临时数据库、临时文件、测试环境工具 | 用户任务沙箱内的数据操作 |
| internal_admin | 系统数据库、权限、租户、计费、运维工具 | 管理员内部维护，不对普通用户自动开放 |

#### 8.4.2 ToolInventory

ToolInventory 从相关工具子池读取可治理工具，来源包括：

- MCP Provider。
- API Tool。
- Builtin Tool。
- 知识库检索工具。
- 工作流工具。
- 沙箱数据工具。
- 内部业务工具。

ToolInventory 不直接暴露给 Agent。

#### 8.4.3 ToolCandidateCollector

ToolCandidateCollector 根据任务和 Agent 需求在相关工具子池内召回候选工具。

召回信号包括：

- task intent。
- required_capabilities。
- Agent.allowed_tool_categories。
- 工具 category。
- 工具 capabilities。
- 工具 description 语义相似度。
- 管理员推荐工具。
- 任务输入模态。

输出示例：

```json
{
  "agent_id": "agent-a",
  "raw_tool_candidates": [
    {
      "tool_id": "mcp-search-docs",
      "source": "public_mcp",
      "match_reason": "capability:document_search",
      "semantic_score": 0.88
    }
  ]
}
```

#### 8.4.4 ToolPolicyFilter

ToolPolicyFilter 是动态工具池的安全核心。

过滤维度包括：

| 维度 | 说明 |
| --- | --- |
| 用户权限 | 当前用户是否允许触发该工具 |
| Agent 权限 | 当前 Agent 是否允许使用该工具类别 |
| 工具风险 | sensitive/dangerous 默认不自动挂载 |
| 工具健康 | unhealthy/disabled 工具不挂载 |
| 成本限制 | 超预算工具不挂载 |
| 操作类型 | 写操作、外部通信、删除操作需要额外确认 |
| 数据范围 | 敏感数据工具需要更严格权限 |
| 输入 schema | 与任务输入不兼容的工具过滤 |

高风险工具处理策略：

```text
safe -> 可自动挂载
controlled -> 权限通过后可挂载，必要时要求确认
sensitive -> 默认不挂载，除非管理员策略显式允许
dangerous -> 普通用户不可自动触发
```

#### 8.4.5 ToolRanker

ToolRanker 对候选工具排序。

排序信号包括：

- 能力匹配分。
- 语义匹配分。
- 工具成功率。
- 平均延迟。
- 成本等级。
- 健康状态。
- 管理员推荐权重。
- 最近失败率。

### 8.5 跨子池工具子集输出

CrossPoolToolSubsetBuilder 输出本次 Agent 可见的跨子池工具子集。

```json
{
  "agent_id": "agent-frontend",
  "matched_tool_pools": ["mcp", "builtin"],
  "max_tool_count": 5,
  "selected_tools": [
    {
      "tool_id": "mcp-code-repo-search",
      "pool": "mcp",
      "runtime_name": "search_code_repo",
      "risk_level": "safe",
      "mount_reason": "matches frontend implementation task",
      "permission_granted_by": "public_tool_policy"
    },
    {
      "tool_id": "builtin-file-writer",
      "pool": "builtin",
      "runtime_name": "write_project_file",
      "risk_level": "controlled",
      "mount_reason": "required for sandbox/project file output",
      "permission_granted_by": "sandbox_scope_policy"
    }
  ],
  "filtered_out_tools": [
    {
      "tool_id": "internal-delete-system-record",
      "pool": "internal_admin",
      "reason": "internal_admin_tool_not_allowed_for_user_task"
    }
  ]
}
```

### 8.6 RuntimeToolMountService

RuntimeToolMountService 负责把工具子集转换成 Agent 可调用的运行时工具。

职责包括：

- 将 MCP tool 转成 LangChain tool。
- 将 API tool 转成统一 tool interface。
- 将知识库检索封装成 retrieval tool。
- 合并 App 预绑定工具和动态工具。
- 去重。
- 控制最大工具数量。
- 生成工具调用审计上下文。

运行时挂载原则：

```text
Agent 只能看到本次挂载的工具，不知道完整工具子池集合。
```

### 8.7 执行前约束与执行后校验

在 Agent 执行前，需要固化三类约束：

```text
AllowedAgents
AllowedTools
BudgetAndRiskPolicy
```

执行后需要校验：

- Agent 是否调用了授权工具。
- 工具调用是否超预算。
- 是否出现高风险输出。
- 是否有工具失败。
- 结果是否满足任务要求。
- 是否需要 fallback 或升级模型。

这意味着调度系统不是“把工具交给 Agent 后就结束”，而是必须闭环控制：

```text
规划 -> 约束 -> 执行 -> 校验 -> 汇总 -> 记录
```



## 9. Agent 池设计

### 9.1 Agent 元数据

每个 Agent 需要新增或补充以下元数据：

| 字段 | 说明 | 示例 |
| --- | --- | --- |
| capabilities | 能力标签 | `research`, `coding`, `summarization`, `data_analysis` |
| task_types | 适合任务类型 | `qa`, `analysis`, `workflow`, `tool_use` |
| complexity_level | 适合复杂度 | `simple`, `medium`, `complex` |
| model_tier | 默认模型档位 | `cheap`, `standard`, `strong` |
| cost_level | 成本等级 | `low`, `medium`, `high` |
| routing_priority | 路由优先级 | 0-100 |
| allowed_tool_categories | 可用工具类别 | `search`, `mcp`, `knowledge`, `database` |
| risk_level | Agent 风险等级 | `safe`, `controlled`, `sensitive` |
| visibility | 可见性 | `public`, `assigned`, `admin_only` |
| quality_score | 历史质量评分 | 0-1 |
| success_rate | 历史成功率 | 0-1 |
| latency_p95 | P95 延迟 | 毫秒 |
| preset_prompt | Agent 预设提示词 | 存储在 AppConfig.preset_prompt，定义 Agent 的角色、行为规范和输出要求 |

> **prompt 字段说明**：Agent 的提示词不在 AgentPoolConfig 表中，而在 AppConfig.preset_prompt 字段（Text 类型）。运行时由 app_service.py 组装到 AGENT_SYSTEM_PROMPT_TEMPLATE 模板中。池治理页面不直接编辑 prompt，但应展示 prompt 摘要供管理员理解 Agent 定位。

### 9.2 Agent 子池设计

Agent 池不是一个单独的大池，而是由多个面向领域和能力的小池组成。每个子池可以独立配置准入规则、默认模型、质量指标、工具类别和管理员负责人。

子池分类不需要第一阶段自动生成，先由管理员在配置中心手动分配和打标签。管理员创建或编辑 Agent 时，需要选择主子池，并可附加多个辅助子池标签。系统路由只读取这些结构化标签，不在早期依赖自动聚类。

推荐初始子池：

| 子池 | 说明 | 示例 Agent |
| --- | --- | --- |
| coding | 编程、工程、测试、部署 | UI、前端、后端、测试、DevOps |
| office | 办公、文档、图片、表格、PPT | P 图、文档整理、表格分析、PPT 制作 |
| data | 数据处理和分析 | SQL、报表、可视化、指标分析 |
| research | 检索、调研、分析报告 | 搜索研究、行业分析、竞品分析 |
| workflow | 多步骤业务执行 | 审批、工单、流程自动化 |
| internal_admin | 系统内部维护 | 运维、审计、租户管理、计费排查 |

internal_admin 子池默认只对管理员和系统内部流程开放，不参与普通用户自动路由。

### 9.3 Agent 来源

Agent 池第一阶段复用现有 App：

- public App。
- assigned App。
- 管理员配置中心创建的 App。

后续可以扩展：

- 专用内置 Agent。
- 工作流 Agent。
- 工具型 Agent。
- 外部 A2A Agent。

每个 Agent 必须归属至少一个子池，允许多个子池标签，但需要一个主子池用于运营统计。

质量评分和推荐权重第一阶段也先由管理员手动维护。后续当路由日志、用户反馈、成功率、失败率、耗时和成本数据积累足够后，再逐步引入自动评分或半自动建议。

### 9.4 Agent 路由策略

AgentRouter 需要综合：

- 用户问题语义。
- 任务类型。
- 复杂度。
- Agent 能力标签。
- Agent 模型档位。
- Agent 成本等级。
- 用户权限。
- 历史成功率。
- 近期健康状态。



## 10. 工具池设计

### 10.1 工具池范围与统一抽象

工具池不是一个单独的大池，而是由多个工具子池组成。核心设计原则是：**所有可被 Agent 调用的资源都应纳入工具池治理，不论其内部实现是原子工具还是组合工具。**

#### 10.1.1 工具来源类型（完整版）

基于 OpenAgent 底座已有的能力，工具来源类型扩展为以下 7 类：

| 来源类型 | 底座实现 | 治理方式 | 说明 |
| --- | --- | --- | --- |
| builtin | builtin_provider_manager + providers.yaml | 纳入 ToolSourceType | 平台内置基础能力（搜索、翻译、天气等） |
| api_tool | ApiTool + ApiToolProvider + OpenAPI 解析 | 纳入 ToolSourceType | 企业业务 API、第三方服务 API |
| mcp | McpProvider + McpToolFactory | 纳入 ToolSourceType | 外部能力接入和标准化工具调用 |
| knowledge | Dataset + Document + Segment 检索 | 纳入 ToolSourceType | 知识库检索工具 |
| workflow | WorkflowTool(BaseTool) 从已发布 Workflow 构建 | 纳入 ToolSourceType | 多步骤业务自动化，本质是组合工具 |
| skill | SkillToolFactory + SkillPackage | 纳入 ToolSourceType | 技能包，本质是组合工具 |
| agent_binding | app_service 把另一个 App 包成委派工具 | 纳入 ToolSourceType | Agent 委派调用，A2A 协作的工具化表达 |

#### 10.1.2 原子工具、工具包与组合工具

工具按内部复杂度分为三类（基于底座真实实现，非理论分类）：

**原子工具**：直接执行单个操作，不可再分，底座已通过 LangChain BaseTool 完成统一抽象。
- builtin / api_tool / mcp / knowledge 属于此类
- 每个工具独立挂载、独立治理、独立审计

**工具包（Package）**：多个原子工具的命名空间集合，**不递归引用其他工具**，由远端执行器统一调度。
- skill 属于此类：`SkillPackageVersion.manifest["tools"]` 持有多个工具定义，由 SCF 执行器远端执行
- skill 内部工具是"叶子工具"，不会嵌套调用 builtin/api_tool/mcp/knowledge
- 治理粒度：可按 skill_package_id 整体治理，也可按 manifest 内 tool_name 细粒度治理
- **注意：skill 不是"组合工具"**，它是"原子工具的打包集合"，治理上按工具包处理

**组合工具（Composite）**：由多个节点编排而成，**内部递归引用其他工具**，封装为一个可调用单元。
- workflow：由 12 种节点（LLM/代码/工具/知识库/HTTP/条件分支等）编排而成
- agent_binding：把另一个 App 包装成工具，递归加载目标 App 的全部工具

**底座真实嵌套能力（已审计）**：

| 组合工具 | 内部可引用的工具类型 | 数据来源 | 是否需扩展 |
| --- | --- | --- | --- |
| workflow | builtin_tool / api_tool（ToolNode）+ knowledge（DatasetRetrievalNode 独立节点） | `Workflow.graph["nodes"]` | 已支持 |
| workflow | mcp / skill / workflow / agent_binding | `ToolNodeData.tool_type` 当前仅 `builtin_tool/api_tool` | **需扩展 ToolNodeData** |
| agent_binding（私有 App） | builtin / api_tool / mcp / skill / knowledge / workflow / 嵌套 agent_binding | 递归调用 `_build_runtime_tools` | 已支持 |
| agent_binding（公开 App） | 不在本地解析，走 A2A 远端协议 | `PublicAgentA2AService.send_message` | 已支持（黑盒） |

组合工具的真实嵌套关系（反映底座现状）：
```text
原子工具：builtin / api_tool / mcp / knowledge
    │
    ├─→ 工具包：skill（manifest 内多个叶子工具，SCF 远端执行，不递归）
    │
    ├─→ 组合工具：workflow
    │       └─ 内部节点可引用：builtin_tool / api_tool / knowledge【底座已支持】
    │       └─ 内部节点不可引用：mcp / skill / workflow / agent_binding【需扩展 ToolNodeData】
    │
    └─→ 组合工具：agent_binding（委派工具）
            └─ 私有 App：递归加载目标 App 全部工具（含 workflow/skill/嵌套 agent_binding）【已支持】
            └─ 公开 App：A2A 黑盒委派，不在本地解析【已支持】
            └─ 循环引用检测：绑定期 `_has_agent_binding_path` + 运行期 `call_stack` 去重【已支持】
```

**关键约束**：
1. workflow 当前不能嵌套 mcp/skill/workflow/agent_binding——这是底座硬性限制，需扩展 `ToolNodeData.tool_type` 枚举才能支持
2. agent_binding 是唯一支持完整递归嵌套的组合工具（私有 App 路径）
3. skill 不是组合工具，是工具包，治理按工具包处理（整体或按内部 tool_name）
4. agent_binding 公开 App 走 A2A，内部工具不可见，治理只能在 app_id 层级

#### 10.1.3 统一工具描述符

底座已有 `RuntimeToolDescriptor`（`internal/entity/runtime_tool_entity.py` L8-19），共 10 个字段。**当前完全没有组合工具建模字段**，需扩展：

```python
@dataclass
class RuntimeToolDescriptor(SerializableMixin):
    # ─── 底座已有字段（10 个，保持不变）───
    tool_id: str           # 工具唯一标识，格式因来源而异
    runtime_name: str      # 运行时挂载名
    name: str              # 工具名称
    description: str       # 工具描述
    source_type: str       # 扩展为 7 类：builtin/api_tool/mcp/knowledge/workflow/skill/agent_binding
    provider_id: str       # 来源提供者 ID
    provider_name: str     # 来源提供者名
    input_schema: list     # 参数定义（简化字段列表）
    metadata: dict         # 治理元数据（risk_level/cost_level/health_status 等）
    audit_context: dict    # 审计上下文

    # ─── 新增字段（组合工具建模）───
    is_composite: bool = False                       # 是否为组合工具（仅 workflow/agent_binding 为 True，skill 为 False）
    composite_kind: str = ""                         # 组合类型："workflow" / "agent_binding"（skill 不是组合工具）
    composite_components: list["CompositeComponentRef"] = field(default_factory=list)  # 直接成员工具引用
    composite_root_id: str = ""                      # 递归展开时的根组合工具 id（用于审计上下文追溯）
    runtime_name_stable: bool = True                 # 运行时 name 是否稳定（见 10.5.3 稳定性说明）


@dataclass
class CompositeComponentRef(SerializableMixin):
    """组合工具的成员工具引用（不直接持有完整描述符，避免循环引用和深拷贝）"""
    tool_id: str           # 成员工具的 tool_id（格式同 RuntimeToolDescriptor.tool_id）
    source_type: str       # 成员工具来源类型
    ref_path: str          # 在组合工具中的引用路径，如 "workflow.nodes[3].tool" / "agent_binding.app_config.tools[0]"
    is_recursive: bool = False  # 成员本身是否也是组合工具（需递归展开）
```

`composite_components` 的填充规则：
- workflow：从 `Workflow.graph["nodes"]` 提取 `node_type=="tool"` 的节点（ToolNodeData），每个节点生成一个 CompositeComponentRef，ref_path 为 `workflow.nodes[{idx}].tool`
- agent_binding（私有 App）：递归加载目标 AppConfig 的全部绑定，生成 CompositeComponentRef，ref_path 为 `agent_binding.app_config.{field}[{idx}]`，is_recursive 标记嵌套组合工具
- agent_binding（公开 App）：composite_components 为空（A2A 黑盒，内部不可见），is_composite=True 但无法透传治理
- skill：is_composite=False，composite_components 为空（工具包，按整体治理）
- 原子工具：is_composite=False，composite_components 为空

tool_id 格式约定（与底座现有实现对齐）：
- builtin：`builtin:{provider}:{tool_name}`
- api_tool：`api_tool:{uuid}`
- mcp：`mcp:{provider_id}:{tool_name}`
- knowledge：`knowledge:{dataset_id}`
- workflow：`workflow:{workflow_id}`
- skill：`skill:{skill_package_id}`（整体治理）/ `skill:{skill_package_id}:{tool_name}`（细粒度治理）
- agent_binding：`agent_binding:{app_id}`

**关键设计**：CompositeComponentRef 只持有引用（tool_id + ref_path），不持有完整 RuntimeToolDescriptor。组合工具的治理透传通过 CompositeToolResolver（见 10.1.4）按需递归解析，避免一次性展开深嵌套导致内存膨胀。

#### 10.1.4 组合工具展开解析器 CompositeToolResolver

底座当前**没有统一的"组合工具 id → 递归列出原子工具"解析器**。Workflow 需遍历 `graph["nodes"]`，Skill 需读 `manifest["tools"]`，agent_binding 需递归加载目标 AppConfig——三套逻辑分散在各 Service 中。组合工具治理透传（10.2.3）依赖此解析器，是落地的前置条件。

**职责**：给定一个组合工具的 tool_id，递归解析出它直接和间接引用的所有成员工具，返回扁平化的 CompositeComponentRef 列表（含递归层级和引用路径）。

**接口设计**：

```python
@inject
@dataclass
class CompositeToolResolver:
    """组合工具展开解析器：递归解析组合工具的内部成员工具"""
    db: SQLAlchemy
    app_config_service: AppConfigService
    skill_service: SkillService

    def resolve(self, tool_id: str, *, max_depth: int = 8) -> list[CompositeComponentRef]:
        """递归解析组合工具的成员工具，返回扁平化列表。
        
        Args:
            tool_id: 组合工具 id，格式如 workflow:{id} / agent_binding:{app_id}
            max_depth: 最大递归深度，防止无限嵌套（默认 8）
        
        Returns:
            扁平化的 CompositeComponentRef 列表，含递归层级和引用路径
        """
        visited = set()  # 环检测：复用 agent_binding 的 call_stack 思路
        return self._resolve_recursive(tool_id, visited=visited, depth=0, max_depth=max_depth, root_id=tool_id)

    def _resolve_recursive(
        self, tool_id: str, *, visited: set[str], depth: int, max_depth: int, root_id: str, ref_path: str = ""
    ) -> list[CompositeComponentRef]:
        # 1. 环检测：tool_id 已访问则返回空（防止循环引用）
        if tool_id in visited or depth >= max_depth:
            return []
        visited.add(tool_id)

        # 2. 按 source_type 分发解析
        source_type, entity_id = self._parse_tool_id(tool_id)
        if source_type == "workflow":
            return self._resolve_workflow(entity_id, visited=visited, depth=depth, max_depth=max_depth, root_id=root_id)
        elif source_type == "agent_binding":
            return self._resolve_agent_binding(entity_id, visited=visited, depth=depth, max_depth=max_depth, root_id=root_id)
        else:
            # 原子工具和 skill 不递归，返回空
            return []

    def _resolve_workflow(self, workflow_id, *, visited, depth, max_depth, root_id) -> list[CompositeComponentRef]:
        """从 Workflow.graph["nodes"] 提取 ToolNodeData + DatasetRetrievalNode"""
        workflow = self.db.session.query(Workflow).filter(Workflow.id == workflow_id).one_or_none()
        if not workflow:
            return []
        components = []
        for idx, node in enumerate(workflow.graph.get("nodes", [])):
            node_type = node.get("node_type") or node.get("type", "")
            if node_type == "tool":
                # ToolNodeData：tool_type 仅 builtin_tool/api_tool（底座现状）
                tool_type = node.get("tool_type", "")
                member_tool_id = self._build_member_tool_id(tool_type, node)
                components.append(CompositeComponentRef(
                    tool_id=member_tool_id,
                    source_type=self._map_tool_type_to_source_type(tool_type),
                    ref_path=f"workflow.nodes[{idx}].tool",
                    is_recursive=False,  # builtin/api_tool 是原子工具
                ))
            elif node_type == "dataset_retrieval":
                # DatasetRetrievalNode：引用知识库
                dataset_id = node.get("dataset_id", "")
                components.append(CompositeComponentRef(
                    tool_id=f"knowledge:{dataset_id}",
                    source_type="knowledge",
                    ref_path=f"workflow.nodes[{idx}].dataset_retrieval",
                    is_recursive=False,
                ))
            # 其他节点类型（LLM/CODE/HTTP/IF_ELSE 等）不引用工具，跳过
        return components

    def _resolve_agent_binding(self, app_id, *, visited, depth, max_depth, root_id) -> list[CompositeComponentRef]:
        """递归加载目标 App 的 AppConfig 绑定"""
        target_app = self.db.session.query(App).filter(App.id == app_id).one_or_none()
        if not target_app or not target_app.app_config:
            return []
        # 公开 App 走 A2A，内部不可见，返回空（治理只能在 app_id 层级）
        if target_app.is_public:
            return []
        config = target_app.app_config
        components = []
        # 遍历 AppConfig 的 6 类工具绑定字段
        for field_name, source_type in [
            ("tools", "builtin_or_api"),     # tools 字段含 builtin + api_tool
            ("mcp_bindings", "mcp"),
            ("skills", "skill"),
            ("datasets", "knowledge"),
            ("workflows", "workflow"),
            ("agent_bindings", "agent_binding"),
        ]:
            for idx, item in enumerate(getattr(config, field_name, []) or []):
                member_tool_id = self._build_agent_binding_member_id(field_name, source_type, item)
                is_recursive = source_type in ("workflow", "agent_binding")
                components.append(CompositeComponentRef(
                    tool_id=member_tool_id,
                    source_type=source_type,
                    ref_path=f"agent_binding.app_config.{field_name}[{idx}]",
                    is_recursive=is_recursive,
                ))
                # 递归展开嵌套组合工具
                if is_recursive:
                    components.extend(self._resolve_recursive(
                        member_tool_id, visited=visited, depth=depth + 1, max_depth=max_depth, root_id=root_id,
                    ))
        return components
```

**关键设计点**：

1. **环检测复用底座机制**：visited 集合复用 agent_binding 运行期 `call_stack` 去重思路（`app_service.py` L1244-1247），防止组合工具循环引用导致无限递归
2. **深度限制**：max_depth=8，与 agent_binding 绑定期 `_has_agent_binding_path` 的 max_depth=12 保持同量级
3. **公开 App 不展开**：agent_binding 的公开 App 走 A2A，内部不可见，返回空列表，治理只能在 app_id 层级
4. **Workflow 节点类型过滤**：只处理 `node_type=="tool"`（ToolNodeData）和 `node_type=="dataset_retrieval"`，其他节点（LLM/CODE/HTTP 等）不引用工具
5. **按需递归**：只有 `is_recursive=True` 的成员（workflow/agent_binding）才递归展开，原子工具和 skill 不递归

**使用场景**：
- 治理透传（10.2.3）：组合工具的有效风险等级 = max(成员工具风险等级)
- 审计日志：记录组合工具调用的内部成员链路
- 确认卡片：展示组合工具影响范围时列出内部敏感工具
- 路由日志：记录组合工具治理决策的完整上下文

**性能考量**：
- 解析结果可缓存（key 为 tool_id + Workflow.updated_at + AppConfig.updated_at）
- 单次解析深度限制 8 层，最坏情况 8^N 但实际场景成员数有限
- CompositeToolResolver 是无状态服务，可注入到 ToolPolicyFilter 和 RuntimeToolMountService

### 10.2 工具元数据与治理映射

每个工具需要结构化治理元数据。底座已通过 `normalize_tool_metadata` 提供默认值，治理层在此基础上覆盖。

#### 10.2.1 工具治理元数据字段

| 字段 | 说明 | 默认值来源 |
| --- | --- | --- |
| tool_pool | 工具子池归属 | 按 source_type 自动赋值 |
| risk_level | 风险等级（safe/controlled/sensitive/dangerous） | 默认 safe，管理员可覆盖 |
| permission_scope | 权限范围（system/user/tenant/public） | 按 source_type 默认值 |
| cost_level | 成本等级（low/medium/high） | 默认 low |
| health_status | 健康状态（healthy/degraded/offline/unknown） | 运行时动态更新 |
| enabled | 是否启用 | 默认 true |
| requires_confirmation | 是否需要用户确认 | 按 risk_level 推导 |
| allowed_agent_pools | 允许使用的 Agent 子池列表 | 默认全部，管理员可限制 |
| max_invocations_per_request | 单次请求最大调用数 | 默认 5 |
| cooldown_seconds | 冷却秒数 | 默认 0 |
| success_rate | 成功率 | 运行时统计 |
| avg_latency | 平均耗时 | 运行时统计 |

#### 10.2.2 治理策略与底座绑定的关系

治理策略不替代 AppConfig 绑定，而是在绑定基础上做过滤校验：

```text
管理员配置阶段：
  AppConfig.tools/mcp_bindings/skills/workflows/agent_bindings → 定义"Agent 能用什么"
  ToolGovernancePolicy → 定义"这些工具的风险/权限/配额约束"

运行时挂载阶段：
  AppConfig 绑定的工具列表（底座已有）
    → 查询 ToolGovernancePolicy 获取每个工具的治理元数据
    → ToolPolicyFilter 按风险/权限/健康/成本过滤
    → 生成最终挂载的 BaseTool 列表
```

关键原则：**AppConfig 绑定决定“能用什么”，ToolGovernancePolicy 决定“在什么约束下用”。** 两者不是替代关系，而是叠加关系。

#### 10.2.3 组合工具与工具包的治理透传

不同工具类型的治理粒度不同（基于 10.1.2 分类）：

| 工具类型 | 治理粒度 | 透传方式 | 依赖 |
| --- | --- | --- | --- |
| 原子工具（builtin/api/mcp/knowledge） | 单工具治理 | 无需透传 | ToolGovernancePolicy.tool_id 直接绑定 |
| 工具包（skill） | 整体或按内部 tool_name 治理 | 不递归，按包治理 | skill_package_id 或 skill_package_id:tool_name |
| 组合工具（workflow） | 整体治理 + 成员透传 | 递归解析 ToolNode + DatasetRetrievalNode | CompositeToolResolver |
| 组合工具（agent_binding 私有） | 整体治理 + 成员透传 | 递归解析目标 AppConfig | CompositeToolResolver |
| 组合工具（agent_binding 公开） | 仅 app_id 层级治理 | 不展开（A2A 黑盒） | ToolGovernancePolicy.tool_id = agent_binding:{app_id} |

**组合工具的有效风险等级计算**：

```text
workflow / agent_binding 被治理时：
  → CompositeToolResolver.resolve(tool_id) 递归解析所有成员工具
  → 查询每个成员的 ToolGovernancePolicy.risk_level
  → 有效风险等级 = max(成员工具风险等级)  # safe < controlled < sensitive < dangerous
  → 缓存结果（key: tool_id + Workflow.updated_at + AppConfig.updated_at）
```

**部分阻断策略**（成员工具被阻断时的处理）：

| 场景 | 策略 | 说明 |
| --- | --- | --- |
| 成员中存在 dangerous 工具 | 组合工具整体阻断 | dangerous 工具不可自动触发，组合工具也不应自动触发 |
| 成员中存在 sensitive 工具 | 组合工具需用户确认 | 触发统一确认卡片，展示内部 sensitive 工具清单 |
| 成员中存在 disabled 工具 | 组合工具整体阻断 | 任一成员工具 disabled 则组合工具不可用 |
| 成员中存在 unhealthy 工具 | 组合工具降级或阻断 | 按业务策略：可降级（移除该成员节点）或整体阻断 |
| 成员全部 safe/controlled | 组合工具正常放行 | 有效风险等级 = max(safe/controlled) = controlled |

**治理策略绑定层**：

ToolGovernancePolicy.tool_id 的绑定策略：
1. **优先绑定组合工具层级**：`tool_id = workflow:{workflow_id}` 或 `agent_binding:{app_id}`——管理员可直接为整个组合工具配置治理策略
2. **成员工具层级策略透传**：组合工具未配置治理策略时，通过 CompositeToolResolver 解析成员，按成员策略计算有效风险等级
3. **双层叠加**：组合工具层级策略和成员工具层级策略同时存在时，取更严格的（max 风险等级）

**关键约束**：
1. skill 不是组合工具，不递归透传。skill 的治理按工具包处理：`skill:{skill_package_id}` 整体治理，或 `skill:{skill_package_id}:{tool_name}` 细粒度治理
2. agent_binding 公开 App 走 A2A，内部不可见，治理只能在 `agent_binding:{app_id}` 层级，无法透传
3. 组合工具的 tool_id 稳定性见 10.5.3，workflow_id 和 app_id 稳定，治理策略长期有效

### 10.3 工具风险等级

| 风险等级 | 说明 | 执行策略 |
| --- | --- | --- |
| safe | 只读、无敏感数据 | 可自动执行 |
| controlled | 有业务影响但可控，例如写入沙箱文件、修改临时文档 | 需权限过滤，必要时确认 |
| sensitive | 涉及敏感数据、外部通信、正式业务写入 | 默认不自动执行，需审批或管理员授权 |
| dangerous | 删除、支付、权限变更、系统数据库增删改查 | 禁止普通用户自动触发 |

高风险工具不应被理解为“普通用户经常需要查询平台核心数据”。普通用户没有合理动机查询 OpenAgent 自身的系统数据库、租户权限、计费账户、模型 Key 或生产运维数据，这类平台系统工具原则上不进入普通用户可触发工具池。

高风险工具需要按数据和系统归属拆分：

| 归属 | 例子 | 普通用户是否可触发 | 策略 |
| --- | --- | --- | --- |
| 平台自身系统 | OpenAgent 系统数据库、模型 Key、计费账户、租户权限、平台审计日志 | 不可触发 | 仅管理员或内部自动化流程可用 |
| 用户自己的系统 | 用户接入的 CRM、ERP、订单库、客服系统、代码仓库、网站后台 | 可在授权范围内触发 | 需要租户授权、作用域控制、审计、用户确认和操作说明 |
| 用户任务沙箱 | 临时数据库、临时文件、测试容器、临时代码执行环境 | 可触发 | 限定在沙箱作用域，任务结束可清理，执行前说明影响范围 |
| 测试 / 预发环境 | 用户自己的测试库、测试 API、预发站点 | 可触发 | 标记环境，禁止误连生产，执行前说明目标环境 |

普通用户会合理使用高风险工具的场景，通常不是为了操作平台系统，而是为了完成他自己业务系统里的任务：

| 工具 | 做什么事情 | 为什么涉及安全层面 | 普通用户为什么需要 |
| --- | --- | --- | --- |
| CRM 客户更新工具 | 修改客户标签、跟进状态、负责人 | 会写入用户企业的客户数据 | 用户要求“把本周高意向客户标记出来并分配给销售” |
| 订单退款工具 | 对用户店铺订单发起退款或售后 | 涉及资金、订单状态和外部通知 | 用户要求“帮我批量处理这些符合规则的退款申请” |
| ERP 库存调整工具 | 修改库存数量、锁库存、释放库存 | 会影响真实库存和履约 | 用户要求“根据盘点表修正仓库库存” |
| 代码仓库写入工具 | 创建分支、提交代码、发起 PR | 会改变用户代码资产 | 用户要求“帮我修复这个 bug 并提交 PR” |
| 网站后台发布工具 | 发布页面、上下架商品、修改配置 | 会影响线上站点展示或交易 | 用户要求“把这批商品详情页更新上线” |
| 邮件 / IM 发送工具 | 给客户、员工或供应商发送消息 | 会产生外部通信和合规风险 | 用户要求“给这些客户发送续费提醒” |
| 用户数据库 SQL 写入工具 | 在用户授权数据库中插入、更新、删除数据 | 会修改用户业务数据 | 用户要求“把这份表格同步到我的业务数据库” |
| 沙箱数据库工具 | 创建表、写入测试数据、删除临时数据 | 有写操作但只影响临时环境 | 用户要求“用临时数据库帮我验证这个数据处理流程” |

因此高风险工具的判断标准不是“工具本身永远不能给用户用”，而是：

1. 是否操作 OpenAgent 平台自身系统。
2. 是否操作用户自己明确接入和授权的系统。
3. 是否限制在用户租户、项目、沙箱或测试环境内。
4. 是否有清晰的审计记录和可回滚策略。
5. 是否需要用户二次确认或管理员审批。

高风险工具触发前必须经过授权校验和用户确认：

```text
ToolPolicyFilter
  -> 校验工具是否属于用户授权系统
  -> 校验租户 / 项目 / 环境 / 数据范围
  -> 生成风险说明和执行摘要
  -> 前端展示确认卡片
  -> 用户选择执行或取消
  -> ToolInvoker 只在用户确认后执行
```

高风险工具需要使用统一确认 UI，不能每个工具单独实现一套弹窗。

统一确认 UI 至少包含：

| 区域 | 字段 | 说明 |
| --- | --- | --- |
| 标题区 | 风险等级 | controlled / sensitive / dangerous |
| 标题区 | 工具名称 | 即将调用的工具 |
| 标题区 | 所属系统 | 用户系统、沙箱、测试环境或平台系统 |
| 操作说明区 | 操作类型 | 读取、写入、删除、发送、发布、支付、权限变更等 |
| 操作说明区 | 执行摘要 | 用自然语言解释系统准备做什么 |
| 影响范围区 | 影响对象 | 会影响哪些数据、文件、客户、订单、仓库、代码或页面 |
| 影响范围区 | 目标环境 | 生产、测试、预发、沙箱、本地临时环境 |
| 影响范围区 | 是否可回滚 | 可回滚、部分可回滚、不可回滚 |
| 成本区 | 工具成本 | 如果工具调用本身有费用，需要说明 |
| 成本区 | 当前任务已消耗 | 展示当前已发生积分 / token，不预测最终成本 |
| 安全区 | 授权状态 | 是否已通过用户系统授权和作用域校验 |
| 安全区 | 审计记录 | 告知用户本次操作会被记录 |
| 操作区 | 用户选择 | 执行 / 取消 |

统一确认 UI 的数据结构建议：

```json
{
  "confirmation_id": "confirm_xxx",
  "risk_level": "sensitive",
  "tool_id": "crm_update_customer",
  "tool_name": "CRM 客户更新工具",
  "target_system": "用户 CRM 系统",
  "target_environment": "production",
  "operation_type": "write",
  "execution_summary": "将 18 个高意向客户标记为重点跟进，并分配给对应销售负责人。",
  "impact_scope": ["customer_tags", "customer_owner"],
  "rollback_policy": "partially_reversible",
  "authorization_status": "granted",
  "audit_notice": "本次操作会记录工具、操作者、目标系统、输入参数摘要和执行结果。",
  "current_consumed_credits": 128,
  "actions": ["confirm", "cancel"]
}
```

交互要求：

1. 默认按钮焦点不能落在“执行”上，避免误触。
2. dangerous 类型工具必须要求用户主动点击确认，不能自动执行。
3. 不允许模型绕过确认 UI 直接调用高风险工具。
4. 用户取消后，任务应回到 ResultSynthesizer，由主入口说明已取消该操作，并尽量给出不执行工具的替代建议。
5. 如果工具已经进入不可中断的外部写操作，UI 必须提示可能已经生效，并在审计日志中记录。

PRD 中的高风险工具策略应以“平台系统默认不可触发、用户系统授权可触发、执行前说明、用户自主确认、沙箱优先、生产慎用、全程审计、统一确认 UI”为原则。

### 10.4 动态工具检索原则

Agent 执行时不装载完整工具子池集合，而是：

```text
任务 -> 识别相关工具子池 -> ToolRetriever 召回候选工具 -> ToolPolicy 过滤 -> 运行时挂载少量工具
```

默认每次最多挂载工具数量建议：

```text
3-8 个
```

避免工具过多导致模型选择混乱。

### 10.5 池治理与运行时打通

池治理不能是配置孤岛，必须在运行时调用链中实际生效。以下设计解决“配置能写进去但运行时不会读”的问题。

#### 10.5.1 Agent 池治理打通

**问题**：AgentPoolConfig 表存储了 App 的路由元数据（primary_pool/secondary_pools/risk_level/model_tier/routing_priority），但 AgentCandidateCollector 直接查 App 表，不读 AgentPoolConfig。

**打通方案**：AgentPoolConfig 作为 App 的路由元数据扩展表，AgentCandidateCollector 在收集候选时 JOIN 读取。

```text
AgentCandidateCollector.collect(account_id)
  → 查询 App 表（public + assigned + own）  [底座已有]
  → LEFT JOIN AgentPoolConfig ON app_id      [新增]
  → 读取 primary_pool / secondary_pools / risk_level / model_tier / routing_priority
  → 合并到 Agent 元数据中
  → AgentPolicyFilter 按这些字段做过滤       [底座已有，需接入]
```

AgentPoolConfig 不存在时降级为默认值（primary_pool=general, risk_level=safe, model_tier=standard）。

#### 10.5.2 工具治理打通

**问题**：AppConfig 绑定的工具走 LangChain BaseTool 通道，不经过 ToolCandidateCollector 和 ToolPolicyFilter。底座的工具构建入口是 `AppService._build_runtime_tools_for_config`（`app_service.py` L990-1059，静态方法），**不是** `AppConfigService`。

**打通方案**：在 `AppService._build_runtime_tools_for_config` 的 return 前注入治理过滤层。

**底座现状（已审计）**：

`_build_runtime_tools_for_config` 按 6 类工具固定顺序构建，全部追加到同一 `list[Any]` 返回：
```text
① tools（builtin + api_tool）  → get_langchain_tools_by_tools_config
② mcp_bindings + mcp_tool_snapshots → get_langchain_tools_by_mcp_bindings
③ skills                       → skill_service.get_langchain_tools_by_skill_bindings
④ datasets（知识库检索，单工具）→ retrieval_service.create_langchain_tool_from_search
⑤ workflows                    → get_langchain_tools_by_workflow_ids
⑥ agent_bindings               → get_langchain_tools_by_agent_bindings
return tools  ← 【天然治理注入点】当前直接返回裸 BaseTool 列表
```

**注入方案**：

```text
AppService._build_runtime_tools_for_config(config)  [底座已有，静态方法]
  → 构建 BaseTool 列表（6 类工具按固定顺序）         [底座已有]
  → 【新增】RuntimeToolGovernanceGate.apply(tools, account, app_id)
      │
      ├─ 1. 为每个 BaseTool 解析 RuntimeToolDescriptor
      │     - 从 BaseTool.metadata 或 name 反解析 source_type / tool_id
      │     - 组合工具（workflow/agent_binding）调用 CompositeToolResolver 填充 composite_components
      │
      ├─ 2. 查询 ToolGovernancePolicy 获取治理元数据
      │     - 按 tool_id 查询，不存在则按 source_type 默认值降级
      │     - 组合工具计算有效风险等级（max 成员风险等级）
      │
      ├─ 3. ToolPolicyFilter 按风险/权限/健康/成本过滤
      │     - 阶段1：只记录过滤决策到路由日志，不实际阻断
      │     - 阶段2：sensitive/dangerous 阻断，safe/controlled 放行
      │     - 阶段3：全量过滤
      │
      ├─ 4. 敏感工具触发用户确认卡片
      │     - 通过 OrchestrationFeatureFlag 控制是否触发
      │     - 底座已有 ToolConfirmationCard 机制
      │
      └─ 5. 返回过滤后的 BaseTool 列表 + 治理决策审计上下文
```

**关键约束**：
1. **静态方法注入策略**：`_build_runtime_tools_for_config` 是静态方法，治理服务通过参数传入或改为实例方法。建议增加可选参数 `governance_gate: RuntimeToolGovernanceGate | None = None`，向后兼容
2. **ToolPolicyFilter 是同步阻塞的**，在工具挂载前完成，不阻塞 SSE 流
3. **过滤结果记录到路由日志**：哪些工具被过滤、过滤原因、组合工具成员链路
4. **组合工具特殊处理**：workflow/agent_binding 先调 CompositeToolResolver 解析成员，再计算有效风险等级，避免对组合工具"裸挂载"
5. **agent_binding 公开 App 不展开**：A2A 黑盒，治理只在 app_id 层级，ToolPolicyFilter 直接按 `agent_binding:{app_id}` 查询策略

#### 10.5.3 治理策略的运行时读取路径

ToolGovernancePolicy 表的 tool_id 与运行时工具的映射关系：

| source_type | tool_id 格式 | 数据来源 | id 稳定性 | runtime_name 稳定性 |
| --- | --- | --- | --- | --- |
| builtin | builtin:{provider}:{tool_name} | builtin_provider_manager | 稳定（provider+tool_name） | 稳定 |
| api_tool | api_tool:{uuid} | ApiTool.id | 稳定（UUID 主键） | 稳定 |
| mcp | mcp:{provider_id}:{tool_name} | McpProvider.id + tool_name | 稳定（UUID + 名字） | 稳定 |
| knowledge | knowledge:{dataset_id} | Dataset.id | 稳定（UUID 主键） | 稳定 |
| workflow | workflow:{workflow_id} | Workflow.id | **稳定**（UUID，graph 变化 id 不变） | **不稳定**（wf_{tool_call_name}，tool_call_name 可编辑） |
| skill | skill:{skill_package_id} | SkillPackage.id | **稳定**（UUID 主键） | **不稳定**（skill__{source_key}__{tool_name}，跨版本 tool_name 可能漂移） |
| agent_binding | agent_binding:{app_id} | App.id | **稳定**（UUID 主键） | **稳定**（agent_app_{app_id 去横线}，纯 id 派生） |

**稳定性说明**：
- tool_id 用于 ToolGovernancePolicy 治理策略绑定，**全部稳定**（基于 UUID 主键或稳定标识符），治理策略长期有效
- runtime_name 用于 LangChain 工具调用，**workflow/skill 的 runtime_name 不稳定**：workflow 的 `tool_call_name` 可编辑，skill 跨版本 `tool_name` 可能漂移
- 治理层只依赖 tool_id（稳定），不依赖 runtime_name（不稳定）。RuntimeToolDescriptor.runtime_name_stable 字段标记稳定性，供审计和调试使用
- workflow 内部 graph 变化时（增删节点、改工具引用），tool_id 不变但成员链路变化，治理策略需要通过 CompositeToolResolver 重新解析成员

ToolPolicyFilter 通过此映射在运行时查询对应工具的治理策略。不存在治理策略记录时，按 source_type 默认值降级处理。

#### 10.5.4 渐进式启用策略

为避免一次性打通导致存量 App 工具被误过滤，采用渐进式启用：

```text
阶段 1：只观测不阻断
  → ToolPolicyFilter 记录过滤决策到路由日志
  → 不实际阻断工具挂载
  → 管理员在路由日志中观察"如果启用阻断会发生什么"

阶段 2：敏感工具阻断
  → 只对 risk_level=sensitive/dangerous 的工具阻断
  → safe/controlled 工具继续放行

阶段 3：全量启用
  → 所有工具按治理策略过滤
  → 管理员可按 source_type / tool_pool 灰度启用
```

渐进式启用通过 OrchestrationFeatureFlag 控制（底座已有此机制）。



## 11. 知识库双层设计

知识库需要区分系统级知识库和用户个人知识库。两者都可以进入检索工具体系，但定位、权限、数据来源和使用方式不同。

### 11.1 系统级知识库

管理员端的知识库应改名和定位为系统级知识库。它存放的是底层知识、系统性知识、通用操作经验和 Agent 执行规范，用于优化 Agent 的操作体验和执行质量。

系统级知识库内容包括：

- 平台使用说明。
- Agent 操作规范。
- 工具调用说明。
- 通用行业知识。
- 通用办公模板。
- 通用代码规范。
- 常见错误处理经验。
- 系统推荐工作流。
- 管理员沉淀的最佳实践。

系统级知识库的特点：

| 维度 | 策略 |
| --- | --- |
| 维护者 | 管理员 |
| 作用对象 | Agent、Orchestrator、工具选择、结果汇总 |
| 可见性 | 普通用户不直接管理，必要时可引用公开内容 |
| 用途 | 提升系统基础能力，让 Agent 更会用工具、更懂平台规则 |
| 权限 | 平台级或租户级权限控制 |

系统级知识库不应记录某个用户的私人偏好，也不应混入用户个人资料。

### 11.2 管理员身份与知识库归属边界

当前系统中，管理员也是用户：管理员账号会绑定一个普通 `Account`，管理员登录后既有管理员身份，也会获得用户端身份。因此知识库归属不能只按“创建人是不是管理员”判断，而必须按“操作上下文 + 知识库作用域”判断。

核心原则：

```text
同一个自然人
  -> 以普通用户上下文操作：写入用户个人知识库
  -> 以管理员配置中心上下文操作，并显式选择系统级作用域：写入系统级知识库
```

也就是说，管理员的知识库不天然等于系统级知识库。管理员也可以有自己的用户长期记忆库和用户资料内容库；只有当管理员在配置中心以管理行为创建、维护、发布的知识，才属于系统级知识库。

判定矩阵：

| 操作人 | 操作入口 | 操作上下文 | knowledge_scope | 归属 |
| --- | --- | --- | --- | --- |
| 普通用户 | /home 或用户知识库页面 | user | user_memory | 用户长期记忆库 |
| 普通用户 | /home 或用户知识库页面 | user | user_content | 用户资料内容库 |
| 管理员 | /home 普通问答 | user | user_memory | 管理员自己的长期记忆库 |
| 管理员 | /home 普通问答 | user | user_content | 管理员自己的资料内容库 |
| 管理员 | 配置中心 / 系统知识库管理 | admin | system | 系统级知识库 |
| 管理员 | 配置中心 / 租户知识库管理 | admin | tenant | 租户级知识库 |
| 管理员 | 配置中心 / 项目知识库管理 | admin | project | 项目级知识库 |

因此需要在知识库数据模型中增加或明确以下字段：

| 字段 | 说明 |
| --- | --- |
| owner_account_id | 资源实际归属的用户账号，兼容现有 account_id |
| owner_admin_user_id | 如果由管理员在管理上下文创建，记录管理员身份 |
| operation_context | user / admin / system_job，表示创建或修改时的操作上下文 |
| knowledge_scope | system / tenant / project / user_memory / user_content |
| visibility_scope | private / team / tenant / public / internal |
| target_tenant_id | 租户级知识库归属 |
| target_project_id | 项目级知识库归属 |
| created_from | manual_upload / conversation_memory / admin_config / workflow_import / external_sync |

边界规则：

1. 管理员在 `/home` 的普通提问和回答中产生的长期记忆，默认进入管理员自己的用户长期记忆库。
2. 管理员在用户资料页面上传的文档、图片、视频、音频，默认进入管理员自己的用户资料内容库。
3. 管理员在配置中心创建的知识库，只有显式选择 `system`、`tenant` 或 `project` 作用域时，才进入对应管理级知识库。
4. 系统级知识库必须要求管理员权限，并记录 `owner_admin_user_id`、操作日志和发布状态。
5. 系统级知识库的内容可以被普通用户任务检索引用，但普通用户不能直接写入或管理。
6. 用户个人知识库默认只服务该用户本人，不能因为用户拥有管理员身份而自动变成系统知识。
7. 当同一条知识既可能是个人偏好又可能是系统规范时，必须让管理员明确选择保存到“个人长期记忆”还是“系统级知识库”。

### 11.3 用户个人知识库

用户应该拥有自己的个人知识库，但需要进一步拆成两类：

1. **用户长期记忆库**：基于用户提问、回答反馈、反复表达的偏好和习惯形成的长期记忆。
2. **用户资料内容库**：用户主动上传的文档、图片、视频、音频等资料内容，用于任务检索和上下文增强。

这两类都属于用户个人知识体系，但数据来源、存储结构、确认方式和调用方式不同。

#### 11.3.1 用户长期记忆库

长期记忆库用于沉淀用户偏好、习惯、常用表达、工作方式和个性化规则，让系统越用越懂用户。

长期记忆来源包括：

- 用户反复表达的回答风格偏好。
- 用户明确纠正过的术语、格式和口径。
- 用户经常使用的项目背景和业务上下文。
- 用户在对话中明确说“以后都这样”“记住这个偏好”的内容。
- Agent 从用户提问和反馈中识别出的稳定习惯。

长期记忆不能静默写入。系统可以从用户的提问和回答反馈中自动抓取候选记忆，但默认需要达到高置信度后才询问用户是否需要存入长期习惯。

第一阶段推荐触发规则：

```text
同一类偏好或习惯
  -> 连续或累计出现 3 次
  -> 语义一致性达到高置信阈值
  -> 未被用户明确拒绝
  -> 才弹出长期记忆确认
```

推荐流程：

```text
用户对话
  -> MemoryCandidateExtractor 识别可能的长期偏好或习惯
  -> MemoryConfidenceTracker 聚合同类候选并累计出现次数
  -> 达到 3 次高置信触发条件
  -> 生成候选记忆和保存理由
  -> 前端询问用户是否保存
  -> 用户选择保存 / 编辑后保存 / 本次忽略 / 后续自动保存 / 永不保存和提醒
  -> UserMemoryService 根据用户选择写入或更新长期记忆策略
```

用户确认卡片至少包含：

| 字段 | 说明 |
| --- | --- |
| 候选记忆 | 系统建议保存的偏好或习惯 |
| 触发依据 | 已连续或累计出现 3 次的相似行为或表达 |
| 来源 | 来自哪些提问、回答或用户反馈 |
| 保存理由 | 为什么认为它是长期偏好 |
| 作用范围 | 全局、某个项目、某类任务、某个 Agent |
| 操作 | 保存、编辑后保存、本次忽略、后续自动保存、永不保存和提醒 |

用户设置中需要提供长期记忆开关：

| 设置项 | 说明 |
| --- | --- |
| 长期记忆建议 | 是否允许系统根据对话提出长期记忆候选 |
| 自动保存长期记忆 | 用户勾选后，后续高置信候选可自动保存不再弹窗 |
| 永不保存和提醒 | 用户开启后，不再提取或提示长期记忆候选 |
| 记忆确认阈值 | 第一阶段默认 3 次高置信触发，后续可做高级设置 |
| 记忆管理入口 | 查看、编辑、删除、启用 / 禁用已保存记忆 |

长期记忆需要支持用户手动管理：

- 查看。
- 新增。
- 编辑。
- 删除。
- 启用 / 禁用。
- 设置作用范围。
- 查看来源。

#### 11.3.2 用户资料内容库

用户资料内容库用于存储用户主动上传、授权接入或从外部数据源同步的资料内容。它更接近现有 Dataset / Document / Segment 知识库能力。

资料内容包括：

- 文档：md、doc、docx、txt、pdf、csv、xlsx、xls、html 等。
- 外部数据源：飞书、Notion、网盘、GitHub、企业知识库、业务系统导出的资料等。
- 其他结构化或半结构化业务资料。
- 图片：jpg、jpeg、png、webp、gif、svg 等，第一阶段先后置深度解析。
- 视频：产品演示、会议录像、课程视频等，第一阶段先后置深度解析。
- 音频：会议录音、访谈、播客、语音备忘等，第一阶段先后置深度解析。

资料内容库需要支持：

| 能力 | 说明 |
| --- | --- |
| 上传 | 用户主动上传文件 |
| 外部数据源连接 | 用户授权连接飞书、Notion、网盘、GitHub、企业知识库等外部数据源 |
| 同步 | 支持手动同步和后续扩展定时同步 |
| 解析 | 第一阶段优先处理文本和结构化资料；图片、视频、音频深度解析后置 |
| 分段 | 将长内容切分为可检索片段 |
| 索引 | 建立向量、全文和关键词索引 |
| 检索 | 按任务动态召回相关资料 |
| 权限 | 用户级、项目级、团队级隔离 |
| 管理 | 用户可删除、禁用、重命名、重新索引 |

#### 11.3.3 两类个人知识库的差异

| 维度 | 用户长期记忆库 | 用户资料内容库 |
| --- | --- | --- |
| 来源 | 对话、反馈、用户确认保存 | 用户上传或连接的数据源 |
| 内容 | 偏好、习惯、口径、长期规则 | 文档、图片、视频、音频、业务资料 |
| 写入方式 | 系统提出候选，用户确认后保存；也可手动新增 | 用户主动上传或授权同步 |
| 调用方式 | 优先影响回答风格、默认偏好和任务策略 | 作为任务资料被检索引用 |
| 风险 | 错误记忆、过度个性化、隐私偏好泄露 | 私有文件泄露、跨用户检索、解析失败 |
| 管理方式 | 用户管理记忆条目 | 用户管理文件、文档、片段和索引 |

用户个人知识库的整体特点：

| 维度 | 策略 |
| --- | --- |
| 维护者 | 用户本人，管理员可按合规策略管理存储和配额 |
| 作用对象 | 主入口回答、个性化 Agent、用户任务上下文 |
| 可见性 | 默认仅用户本人和授权范围可见 |
| 用途 | 个性化、长期偏好、私有业务上下文、资料检索 |
| 权限 | 用户级、团队级、项目级权限控制 |

### 11.4 检索优先级与隔离策略

执行任务时，知识检索应按作用域分层：

```text
任务上下文
  -> 用户个人知识库
  -> 用户团队 / 项目知识库
  -> 租户级知识库
  -> 系统级知识库
  -> 公共知识源
```

检索策略：

1. 用户个性化问题优先检索用户个人知识库。
2. 工具使用、Agent 操作、平台规则优先检索系统级知识库。
3. 两类知识库可以同时参与，但必须在结果中保留来源作用域。
4. 用户个人知识库不得污染系统级知识库。
5. 系统级知识库不得泄露管理员内部敏感信息给普通用户。
6. ResultSynthesizer 需要区分“系统规则”和“用户偏好”，冲突时系统规则优先，表达风格可尊重用户偏好。

### 11.5 现有知识库能力评估

当前系统已经有一套 Dataset / Document / Segment 体系，适合演进为“用户资料内容库”的基础，但还不能完整满足“用户长期记忆库”和多媒体资料库需求。

已具备能力：

| 能力 | 现有实现 |
| --- | --- |
| 知识库管理 | `Dataset` 模型、创建、更新、删除、分页、搜索 |
| 文档管理 | `Document` 模型、上传后创建文档、启用 / 禁用、删除、重命名 |
| 片段管理 | `Segment` 模型、片段增删改查、启用 / 禁用、命中次数 |
| 文件上传 | 通过 `UploadFile` 关联文档 |
| 文档处理 | 支持 automatic / custom 处理规则、分段规则、chunk_size、chunk_overlap |
| 索引状态 | waiting、parsing、splitting、indexing、completed、error |
| 检索策略 | semantic、full_text、hybrid |
| 检索工具 | `dataset_retrieval` 可作为 LangChain Tool 被 Agent / Workflow 调用 |
| 召回测试 | `/datasets/<id>/hit` 支持召回测试和最近查询记录 |
| App 绑定 | `AppDatasetJoin`、`AppConfig.datasets` 支持应用绑定知识库 |
| Workflow 绑定 | dataset_retrieval workflow node 支持工作流检索知识库 |

**代码审计修正（v4.0）**：

上述"已具备能力"中，检索策略 semantic/full_text/hybrid 和 dataset_retrieval 工具在代码层面存在但生产链路不完整。knowledge_base_service.py 仅有基础 CRUD（create/get/delete），未见完整的 RAG 检索管线：缺失向量索引构建、chunk 切分执行、embedding 生成、相似度召回、rerank 等核心环节。App 绑定知识库的 AppDatasetJoin 存在，但 Agent 执行时是否真正调用知识库检索需要验证。

现有 TokenBufferMemory 仅是会话短期上下文裁剪（trim_messages strategy="last" max_tokens=2000），不是跨会话长期记忆。long_term_memory_service.py 的 MemoryCandidateExtractor 硬编码只识别"中文"语言偏好，不提取通用事实/偏好/关系，与本 PRD 11.3.1 描述的完整记忆流程存在严重差距。

当前支持较好的资料类型：

| 类型 | 当前情况 |
| --- | --- |
| 文档 | 已支持 md、doc、docx、txt、pdf、csv、xlsx、xls、html 等 |
| 图片 | 上传层允许 jpg、jpeg、png、webp、gif、svg；第一阶段不要求完整 OCR / 视觉理解入库，深度解析后置 |
| 视频 | 第一阶段不要求视频解析、抽帧、字幕提取、ASR 入库，深度解析后置 |
| 音频 | 第一阶段不要求音频 ASR、说话人切分、转写入库，深度解析后置 |

明确缺口：

1. 现有 Dataset 更像“用户上传资料型知识库”，不是自动长期习惯记忆。
2. 现有 `TokenBufferMemory` 只是会话短期上下文裁剪，不是跨会话长期记忆。
3. 现有知识库缺少 `knowledge_scope`，无法区分系统级知识库、用户长期记忆库、用户资料内容库、团队知识库。
4. 现有知识库主要使用 `account_id` 做归属判断，但管理员账号也绑定普通 `Account`，因此仅靠 `account_id` 无法区分“管理员自己的个人知识库”和“管理员维护的系统级知识库”。
5. 现有知识库缺少 `operation_context`、`owner_admin_user_id`、`visibility_scope` 等字段，无法表达管理上下文和发布范围。
6. 现有知识库缺少长期记忆候选提取、用户确认、编辑后保存、忽略、作用范围管理。
7. 现有资料库主要覆盖文本类文档，多媒体资料的 OCR、ASR、视频抽帧、视觉摘要、音视频转写等处理链路后置，不阻塞第一阶段。
8. 现有知识库缺少外部数据源连接和同步能力，后续需要支持飞书、Notion、网盘、GitHub、企业知识库等来源。
9. 现有检索只按 account_id 做基础隔离，后续需要扩展用户级、团队级、项目级、租户级作用域。
10. 现有 App 绑定知识库是预绑定模式，后续需要接入动态知识检索工具子池。

由于当前系统没有必须保留的旧数据，数据库模型可以按目标架构直接重构，不需要为了兼容历史数据做复杂迁移策略。实施时可以优先保证新模型清晰，而不是维持旧字段语义。

建议演进方式：

```text
现有 Dataset / Document / Segment
  -> 直接重构为带 knowledge_scope、owner_scope、visibility_scope 的知识库模型
  -> 增加 operation_context 与 owner_admin_user_id
  -> 先承载用户资料内容库
  -> 新增 UserMemory 独立模型承载长期记忆
  -> 新增系统级知识库管理入口和发布状态
  -> 再统一接入 knowledge tool pool
```

数据模型策略：

| 模型方向 | 策略 |
| --- | --- |
| Dataset | 可直接扩展或重命名为 KnowledgeBase，不需要保留旧数据兼容逻辑 |
| Document / Segment | 可按资料内容库重新设计字段，第一阶段优先文本和结构化资料，多媒体解析字段预留但能力后置 |
| UserMemory | 新增独立模型，不建议复用 Dataset 承载长期习惯 |
| ExternalDataSource | 新增外部数据源连接模型，记录来源类型、授权状态、同步状态和作用域 |
| KnowledgeScope | 作为核心枚举字段设计，不作为后补字段 |
| Owner / Visibility | 初始模型就纳入 owner_account_id、owner_admin_user_id、visibility_scope |
| 迁移脚本 | 只需要建新表或重建表，不需要历史数据迁移和兼容转换 |

### 11.6 与工具池的关系

知识库不是单纯的文档页面，而应作为知识检索工具子池进入 ToolPool：

```text
knowledge tool pool
  -> system_knowledge_retriever
  -> user_memory_retriever
  -> user_content_retriever
  -> tenant_knowledge_retriever
  -> project_knowledge_retriever
```

Agent 不直接访问全部知识库，而是通过 ToolPolicyFilter 获取本次任务允许访问的知识检索工具子集。



## 12. 模型路由、模型池、Key 池与成本控制

### 12.1 模型档位

| 档位 | 适用任务 | 示例策略 |
| --- | --- | --- |
| cheap | 简单问答、改写、摘要、分类 | 默认优先使用 |
| standard | 中等复杂任务、普通工具调用 | 常规执行模型 |
| strong | 复杂推理、规划、多 Agent 汇总、代码/研究 | 按需升级 |
| vision | 图片理解 | 有图片输入或视觉任务时使用 |
| long_context | 长文档任务 | 长上下文场景使用 |

### 12.1.1 模型池与 Key 池

后台需要统一模型池和 Key 池管理，否则多个 Agent 难以稳定流转。

模型池需要管理：

- 供应商。
- 模型名称。
- 模型档位。
- 支持模态。
- 上下文长度。
- 输入 / 输出价格。
- 速率限制。
- 健康状态。
- 默认 fallback 模型。

Key 池需要管理：

- 供应商 Key。
- Key 归属租户或系统。
- 可用额度。
- 并发限制。
- 失败次数。
- 熔断状态。
- 轮询和权重。
- 到期时间。

管理员需要可以为每个 Agent 手动配置底座模型，也可以选择“跟随系统策略”。系统策略负责在 Key 不可用、限流、余额不足或模型故障时自动切换。

### 12.2 复杂度判断

`simple / medium / complex` 初始规则不是给用户看的产品概念，而是给 Orchestrator 使用的调度规则。它决定：

- 用哪个模型档位。
- 是否进入 Agent 子池。
- 是否需要工具子集。
- 是否允许多 Agent。
- 是否开启深度思考。
- 单次最多挂载多少工具。
- 最终如何计费和记录成本。

推荐初始规则：

| 复杂度 | 判断信号 | 默认执行 |
| --- | --- | --- |
| simple | 单轮问答、常识解释、轻量改写、无需外部工具、无需多步骤推理 | cheap 模型 direct_answer |
| medium | 明确垂直任务、需要一个 Agent、需要少量工具、需要读取资料或生成结构化内容 | standard 模型 single_agent 或 single_agent_with_tools |
| complex | 多目标、多领域、多文件、长上下文、需要规划、需要多个 Agent、需要质量校验 | strong 模型 deep_thinking 或 multi_agent |

补充判断规则：

| 信号 | 复杂度影响 |
| --- | --- |
| 用户上传图片 | 至少需要 vision 能力，不必然 complex |
| 用户上传长文档 | 可能升级到 long_context 或 medium/complex |
| 任务涉及两个以上领域 | 倾向 multi_agent，复杂度至少 medium |
| 需要写代码并解释方案 | 倾向 complex |
| 需要外部工具查询 | 至少 medium |
| 需要修改生产数据或外部发送 | 风险升级，不等同于复杂度升级 |
| 用户显式要求深度思考 | 可开启 deep_thinking，并按实际 token 计费 |

TaskClassifier 输出：

```json
{
  "intent": "analysis",
  "complexity": "medium",
  "needs_agent": true,
  "needs_tools": true,
  "needs_multi_agent": false,
  "needs_deep_thinking": false,
  "risk_level": "safe",
  "recommended_model_tier": "standard"
}
```

### 12.3 成本策略

CostPolicyService 负责：

- 根据用户会员、token 余额或积分余额判断是否可执行。
- 控制强模型使用条件。
- 控制多 Agent 最大数量。
- 控制工具最大调用次数。
- 失败时决定是否升级模型。
- 预算不足时降级或提示用户。
- 将内部成本明细聚合成用户侧统一扣费。

现阶段允许普通用户开启 deep thinking，不设置系统侧固定预算上限，因为用户通过会员和 token / 积分承担成本。后续可以按套餐、会员等级、企业策略或后台权限再增加不同上限。

成本展示需要分两层：

| 层级 | 展示方式 |
| --- | --- |
| 管理员后台 | 按用户、Agent、工具、模型、Key、供应商、时间拆分统计 |
| 普通用户 | 聚合成一次请求消耗的积分 / token，不暴露内部 Agent 和工具成本细节 |

### 12.3.1 实时计费与手动终止

长任务、deep thinking、多 Agent 和多工具调用必须支持执行中实时计费。用户不应等任务完全结束后才知道成本，而应在执行过程中持续看到当前已经发生的消耗，并可以手动终止止损。第一阶段只展示已发生消耗，不展示预估最终成本，避免预估不准造成误导。

实时计费目标：

1. 用户能看到当前任务已消耗的积分 / token。
2. 用户能看到大致成本来源，例如模型推理、工具调用、deep thinking、多 Agent 执行。
3. 用户可以在前端点击“停止任务”终止后续执行。
4. 系统只扣除已实际发生的成本，不扣未执行部分。
5. 终止后仍返回已完成的部分结果、执行摘要和已扣费明细。

推荐执行链路：

```text
ExecutionCoordinator
  -> ModelGateway / ToolInvoker / A2AClient 持续上报 usage_delta
  -> BillingMetering 汇总增量成本
  -> SSE 推送 billing_delta / billing_summary
  -> 用户可触发 cancel_request
  -> ExecutionCoordinator 停止未开始子任务并尝试中断可中断任务
  -> ResultSynthesizer 汇总已完成结果
```

统一计费事件：

| 事件 | 触发时机 | 用途 |
| --- | --- | --- |
| billing_started | 任务开始执行时 | 初始化前端计费状态 |
| billing_delta | 每次模型、工具、Agent、A2A 产生增量消耗时 | 增量更新当前已发生消耗 |
| billing_summary | 阶段完成或关键节点完成时 | 展示当前阶段累计消耗 |
| billing_cancelled | 用户手动终止时 | 告知任务停止和最终已发生成本 |
| billing_final | 任务正常结束时 | 展示最终已发生成本 |

`billing_delta` 建议结构：

```json
{
  "event": "billing_delta",
  "request_id": "req_xxx",
  "conversation_id": "conv_xxx",
  "source_type": "model",
  "source_id": "agent-frontend",
  "stage": "frontend_implementation",
  "delta_tokens": 320,
  "delta_credits": 12,
  "total_tokens": 1840,
  "total_credits": 68,
  "display_text": "当前已消耗 68 积分",
  "created_at": 1710000000
}
```

用户侧统一计费 UI：

| UI 元素 | 说明 |
| --- | --- |
| 当前已消耗 | 固定展示当前已发生积分 / token |
| 当前执行阶段 | 正在思考、正在调用工具、正在等待 Agent、正在汇总 |
| 成本来源简述 | 模型推理、工具调用、Agent 协作、deep thinking |
| 停止按钮 | 用户可随时终止后续执行 |
| 终止后摘要 | 展示已完成内容、已发生成本和未执行阶段 |
| 不展示内容 | 第一阶段不展示预估最终成本 |

UI 展示原则：

1. 只展示当前已发生消耗，不预测最终成本。
2. 所有消耗增量必须来自统一 `billing_delta`，前端不自行估算。
3. 停止按钮在任务运行期间常驻可见。
4. 用户停止后，UI 切换为“已停止”，并展示最终已发生消耗。
5. 高风险工具确认 UI 中也应嵌入当前已消耗，保持成本认知一致。

终止策略：

| 状态 | 处理方式 |
| --- | --- |
| 未开始的 Agent 子任务 | 直接取消，不计费 |
| 正在流式推理的模型 | 尽量中断，按已生成 token 或供应商账单计费 |
| 正在执行的工具 | 如果工具支持取消则取消；不支持则等待返回并标记为用户终止期间完成 |
| 已完成的工具 / Agent | 保留结果并计费 |
| 已进入外部系统写操作 | 不强制中断，必须记录审计并提示用户可能已生效 |

### 12.4 模型升级策略

推荐顺序：

```text
cheap -> standard -> strong
```

升级条件：

- 分类不确定。
- 用户明确要求高质量。
- 任务高复杂度。
- cheap/standard 执行失败。
- 结果校验未通过。



## 13. Orchestrator 执行模式

### 13.1 执行模式

| 模式 | 说明 | 适用场景 |
| --- | --- | --- |
| direct_answer | 主入口直接回答 | 简单问答 |
| single_agent | 单 Agent 执行 | 明确垂直任务 |
| single_agent_with_tools | 单 Agent + 工具 | 需要查询/操作 |
| multi_agent_parallel | 多 Agent 并行 | 多角度分析 |
| multi_agent_sequential | 多 Agent 串行 | 前后依赖任务 |
| deep_thinking | 深度思考执行 | 复杂产物、长任务 |
| reject_or_confirm | 拒绝或请求确认 | 高风险任务 |

### 13.2 快速路径

为了控制延迟和成本，需要保留快速路径：

```text
简单问题 -> cheap model direct_answer -> SSE 直接返回
```

不进入 Agent 池和工具池。

### 13.3 复杂路径

复杂任务进入：

```text
TaskClassifier -> AgentRouter -> ToolRetriever -> ExecutionCoordinator -> ResultSynthesizer
```



## 14. ResultSynthesizer 设计

### 14.1 输入

```json
{
  "original_query": "...",
  "task_plan": [],
  "agent_results": [
    {
      "agent_id": "...",
      "answer": "...",
      "confidence": 0.8,
      "tool_calls": [],
      "warnings": [],
      "cost": {}
    }
  ],
  "errors": [],
  "cost_summary": {}
}
```

### 14.2 输出

```json
{
  "final_answer": "...",
  "summary": "...",
  "confidence": 0.82,
  "visible_sources": [],
  "user_warnings": [],
  "internal_notes": []
}
```

### 14.3 职责

- 合并多个 Agent 结果。
- 去重。
- 消除冲突。
- 标注不确定性。
- 统一格式。
- 面向用户重写。
- 隐藏内部配置细节。

即使不同 Agent 职责不同，仍可能出现冲突或重复，因此需要 ResultSynthesizer。

典型例子：

| 场景 | 可能问题 | 汇总策略 |
| --- | --- | --- |
| UI Agent 和前端 Agent 同时处理页面方案 | UI 建议动画很复杂，前端判断实现成本过高 | 标注取舍，生成可落地版本 |
| 数据 Agent 和研究 Agent 同时分析市场 | 一个用内部数据，一个用外部资料，结论不一致 | 标注数据来源和置信度 |
| 后端 Agent 和安全 Agent 评审接口 | 后端建议开放接口，安全 Agent 判断权限不足 | 以安全约束为硬边界 |
| 文档 Agent 和代码 Agent 生成交付物 | 文档描述的功能与代码实现细节不一致 | 统一术语和最终交付说明 |
| 多个工具返回相似资料 | 内容重复或来源冲突 | 去重、引用更可信来源 |

因此用户侧默认只展示主入口汇总后的最终结果，管理员后台可查看各 Agent 原始输出和合并过程。



## 15. 可观测性与审计

### 15.1 必须记录的事件

| 事件 | 内容 |
| --- | --- |
| routing_started | 用户、query、conversation_id |
| task_classified | intent、complexity、needs_tools、model_tier |
| model_selected | 模型档位、模型名称、选择原因 |
| agent_candidates_found | 候选 Agent、评分、过滤原因 |
| agent_selected | 选中 Agent、原因 |
| tool_candidates_found | 候选工具、评分、过滤原因 |
| tool_selected | 选中工具、权限、风险等级 |
| tool_invoked | 输入摘要、耗时、状态 |
| agent_completed | 输出摘要、耗时、token、成本 |
| synthesis_started | 汇总开始 |
| synthesis_completed | 最终答案、置信度 |
| fallback_triggered | fallback 原因 |
| routing_failed | 错误类型和原因 |

### 15.2 管理员可见信息

管理员可以查看：

- 路由链路。
- 模型选择原因。
- Agent 子池命中情况。
- Agent 候选和选中原因。
- 工具子池命中情况。
- 工具候选和过滤原因。
- 成本明细。
- 用户侧扣费记录。
- 失败原因。
- fallback 记录。

普通用户只能看到简化进度和聚合后的扣费结果。

### 15.3 日志保留与脱敏策略

路由日志只暴露给管理员。日志保留周期应支持后台配置；如果第一阶段实现配置较复杂，默认保留一个月。

当前阶段暂不强制脱敏，但日志结构需要预留脱敏字段和策略开关，方便后续按合规要求启用。



## 18. 社交社区架构设计（v4.0 新增）

> 产品愿景核心差异化：AI 通用助手 + 社交社区一体。AI 助手产生优质内容，社区承载内容流转，形成 UGC 闭环。

### 18.1 社区架构分层

```text
┌────────────────────────────────────────────────────────────┐
│ 1. 内容生产层                                                │
│ - AI 对话产生精彩问答                                       │
│ - 用户点赞触发"设为公开案例"流程                              │
│ - 用户主动创作（AI 辅助写作）                                │
└──────────────────────────────┬─────────────────────────────┘
                               │
                               ▼
┌────────────────────────────────────────────────────────────┐
│ 2. 内容审核层                                                │
│ - showcase 已实现：用户提交→管理员审核→公开                  │
│ - 后续扩展：社区公约自动检测 + 人工审核结合                   │
│ - 内容分类：案例/教程/创作/问答                               │
└──────────────────────────────┬─────────────────────────────┘
                               │
                               ▼
┌────────────────────────────────────────────────────────────┐
│ 3. 内容展示层                                                │
│ - /showcase 公开案例展示（已实现）                           │
│ - 用户主页：展示精选内容 + 个人画像                           │
│ - 内容流：基于兴趣推荐 + 关注关系                            │
│ - 标签体系：技术/生活/创意/学习                              │
└──────────────────────────────┬─────────────────────────────┘
                               │
                               ▼
┌────────────────────────────────────────────────────────────┐
│ 4. 社交互动层                                                │
│ - 点赞/收藏/评论                                            │
│ - 关注/粉丝关系                                             │
│ - 分享/导出（Markdown/长图/PDF）                            │
│ - AI 辅助社交：帮写内容/帮回复/帮找同好                      │
└────────────────────────────────────────────────────────────┘
```

### 18.2 会话分享与导出

**目标**：让用户能将精彩对话分享到社区。

**功能范围**：

- 生成分享链接：指定对话片段生成公开链接
- 生成分享卡片：对话内容 + AI 回答 + 用户评价，渲染为图片卡片
- 导出格式：Markdown / PDF / 长图
- 分享权限：公开 / 仅关注者 / 私密链接
- 扩展 showcase 流程：从"管理员精选"升级为"人人可发布"

### 18.3 用户主页与内容流

**目标**：每个用户有公开主页，展示个人画像和精选内容。

**数据模型**：

| 模型 | 字段 | 说明 |
| --- | --- | --- |
| UserProfile | user_id, display_name, avatar, bio, tags, social_links | 用户公开画像 |
| UserShowcase | user_id, showcase_case_ids, pinned_ids | 用户精选内容列表 |
| Follow | follower_id, followee_id, created_at | 关注关系 |
| ContentFeed | user_id, feed_items[], generated_at | 个性化内容流 |

**内容流推荐策略**：

1. 关注的人的新内容（权重最高）
2. 同标签/同兴趣的热门内容
3. 基于用户记忆画像的语义推荐（与 Phase F 联动）
4. 全站热门内容（兜底）

### 18.4 AI 辅助社交

**目标**：AI 不只是回答问题，还辅助社区互动。

**能力**：

- AI 帮写社区内容：基于用户对话历史，生成可发布的教程/案例/创作
- AI 帮找同好：基于用户记忆画像 + 关注关系，推荐兴趣相投的用户
- AI 帮回复评论：在用户主页评论区，AI 辅助生成回复建议
- AI 内容摘要：长内容自动生成摘要，用于内容流展示

### 18.5 隐私与安全边界

| 内容类型 | 默认可见性 | 用户可控 |
| --- | --- | --- |
| AI 对话历史 | 仅用户本人 | 可分享指定片段 |
| 长期记忆 | 仅用户本人 | 不可公开，不进入社区 |
| 个人知识库文档 | 仅用户本人 | 不可公开 |
| showcase 案例内容 | 公开（审核后） | 可删除/下架 |
| 用户主页画像 | 公开 | 可编辑/隐藏 |

**核心原则**：记忆和知识库是用户私有能力，绝不进入社区；只有用户主动提交并审核通过的案例内容才公开展示。

---



## 20. 安全要求

### 20.1 权限边界

- 普通用户不可访问配置中心。
- 普通用户不可创建 Agent。
- 普通用户不可直接调用敏感工具。
- 普通用户不可查看路由日志。
- Agent 不可绕过 ToolPolicy 调用工具。
- 前端状态不能作为安全依据。

### 20.2 Prompt 注入防护

必须覆盖：

- 要求忽略规则。
- 要求调用敏感工具。
- 要求导出内部数据。
- 要求显示隐藏 Prompt。
- 要求绕过模型和工具策略。

### 20.3 高风险工具策略

高风险工具默认：

- 不进入普通用户候选。
- 不自动执行。
- 需要管理员授权。
- 必要时需要二次确认。



## 21. 关键风险与应对

| 风险 | 描述 | 应对 |
| --- | --- | --- |
| 成本失控 | 多 Agent、强模型、工具调用叠加 | CostPolicy、预算、调用上限、快速路径 |
| 路由不稳 | Agent/工具元数据不足 | 结构化元数据、评分、人工调优 |
| 工具误用 | Agent 选错工具或参数错误 | ToolPolicy、schema 校验、风险等级 |
| 安全越权 | Prompt 注入或工具权限绕过 | 后端权限、策略过滤、审计 |
| 响应变慢 | 调度链路过长 | direct_answer 快速路径、异步执行、流式反馈 |
| 结果冲突 | 多 Agent 输出不一致 | ResultSynthesizer、置信度、来源记录 |
| 过度设计 | 一次性做全平台 | 分阶段上线，保留兼容路径 |
| 破坏现有功能 | 改动 AssistantAgentService 影响旧链路 | Feature Flag、回归测试、fallback 到旧流程 |



## 22. Feature Flag 与回滚策略

每个阶段都必须通过开关控制。

建议开关：

| 开关 | 作用 |
| --- | --- |
| ENABLE_ORCHESTRATOR | 是否启用 Orchestrator |
| ENABLE_AGENT_METADATA_ROUTING | 是否启用元数据路由 |
| ENABLE_TOOL_POOL_RETRIEVAL | 是否启用动态工具池检索 |
| ENABLE_COST_MODEL_ROUTING | 是否启用成本模型路由 |
| ENABLE_MULTI_AGENT_EXECUTION | 是否启用多 Agent 执行 |
| ENABLE_RESULT_SYNTHESIZER | 是否启用显式汇总器 |
| ENABLE_ROUTING_LOGS | 是否启用路由日志 |

回滚原则：

```text
任意阶段异常 -> 关闭对应开关 -> 回退到旧 Assistant Agent 流程
```



## 23. 成功指标

### 23.1 产品指标

- 用户首页任务完成率提升。
- 普通用户进入配置页面次数下降。
- 用户追问修正率下降。
- 用户满意度提升。

### 23.2 成本指标

- strong 模型调用占比可控。
- 简单任务 cheap 模型命中率提升。
- 单次请求平均成本下降或保持稳定。
- 超预算请求比例可控。

### 23.3 路由指标

- Agent 路由命中率。
- 工具检索命中率。
- fallback 率。
- 多 Agent 调用成功率。
- 工具调用成功率。

### 23.4 工程指标

- `/assistant-agent/chat` 回归测试通过。
- 配置中心回归通过。
- My AI 回归通过。
- 后台应用分配回归通过。
- 安全测试通过。



## 26. 已确认决策与后续讨论点

### 26.1 已确认决策

1. 普通用户不需要理解 public Agent、assigned Agent、MCP 或工具池，只需要在主入口提出问题。
2. Agent 和工具都采用“多个子池 + 动态跨池归集”架构，而不是一个大池里临时捞子集。
3. MCP 属于工具池维度；A2A 属于 Agent 协作维度，两者不是同一种特性。
4. 动态分配的核心是先识别任务涉及哪些子池，再从相关子池中召回 Agent 和工具。例如任务同时涉及 P 图和写代码时，应同时从 office / image 子池和 coding 子池召回 Agent，再通过 A2A 协作。
5. 系统级高风险工具，例如系统数据库增删改查、权限变更、计费 Key 管理，不对普通用户自动开放。
6. 普通用户可以开启 deep thinking，初期不设置固定预算上限，成本由会员、token 或积分体系承担。
7. `simple / medium / complex` 是调度规则，用于决定模型档位、执行模式、Agent 数量、工具数量、是否深度思考和计费方式。
8. 管理员需要能为每个 Agent 手动配置底座模型；后台需要统一模型池和 Key 池管理。
9. 多 Agent 结果需要由主入口统一汇总、整理、冲突处理后再展示给用户。
10. 路由日志只暴露给管理员；保留时长应可配置，若第一阶段配置复杂则默认保留一个月；当前暂不要求脱敏。
11. 成本统计在管理员后台按用户、Agent、工具、模型、Key 等维度拆分；用户侧统一聚合为积分 / token 扣费。
12. 动态工具改造应先设计通用 ToolPool 抽象，再用 MCP 作为第一类适配器试点，后续扩展 API、Builtin、知识库和 Workflow。
13. 高风险工具按系统归属隔离：涉及 OpenAgent 平台自身系统的工具普通用户不可触发；涉及用户自己系统、用户授权业务系统、沙箱或测试环境的高风险工具，可以在授权、作用域、审计和必要确认下触发。
14. 执行过程需要实时计费，前端持续展示已消耗积分 / token，用户可在成本过高时手动终止任务止损；系统只扣已实际发生的成本。
15. 子池分类第一阶段由管理员手动分配和打标签，不依赖自动分类。
16. Agent 和工具质量评分第一阶段先由管理员手动维护，后续再基于成功率、反馈、耗时和成本数据做自动或半自动评分。
17. 知识库分为系统级知识库和用户个人知识库：系统级知识库由管理员维护，用于提升 Agent 操作体验和系统基础能力；用户个人知识库进一步拆分为用户长期记忆库和用户资料内容库。
18. 高风险工具第一阶段不做复杂审批流，但必须做授权校验、风险说明、执行摘要和用户二次确认；用户可以选择执行或取消。
19. 用户侧实时计费第一阶段只展示当前已发生消耗，不展示预估最终成本。
20. 用户长期记忆支持从用户提问、回答反馈和稳定习惯中自动提取候选，但必须询问用户是否保存；用户也可以手动新增、编辑、删除和禁用长期记忆。
21. 用户资料内容库用于用户上传或授权接入的文档、图片、视频、音频等资料；现有 Dataset / Document / Segment 可作为文档资料库基础，但需要扩展多媒体解析和作用域管理。
22. 管理员也是用户，因此知识库归属不能只按创建人身份判断；管理员在普通用户上下文产生的是个人知识库，只有在配置中心管理上下文并显式选择 system / tenant / project 作用域时，才写入系统级或管理级知识库。
23. 当前系统没有必须保留的旧数据，数据库模型可以按目标架构直接重构，不需要复杂历史数据迁移兼容。
24. 长期记忆候选第一阶段采用“三次高置信触发”策略：同类偏好或习惯连续或累计出现 3 次且语义一致性高，才询问用户是否保存。
25. 用户可在长期记忆确认弹窗中选择“后续自动保存不再提醒”或“永不保存和提醒”，并可在用户设置中管理长期记忆建议、自动保存和禁用开关。
26. 高风险工具必须使用统一确认 UI，所有工具共享同一套确认卡片、字段结构和执行 / 取消交互，不允许模型绕过确认 UI 直接调用。
27. 计费成本必须使用统一事件设计，至少包括 billing_started、billing_delta、billing_summary、billing_cancelled、billing_final；用户侧只展示当前已发生消耗。
28. 用户资料内容库需要支持外部数据源接入和同步，包括飞书、Notion、网盘、GitHub、企业知识库等来源；第一阶段优先支持授权连接、手动同步和文本 / 结构化资料检索。
29. 图片、视频、音频等媒体内容的深度解析后置；第一阶段不要求 OCR、ASR、视频抽帧、视觉理解、音视频转写等能力完成入库。
30. 前端新增页面、按钮、导航、提示语、表单字段、空状态、错误提示和管理后台文案必须遵循现有 i18n 规范：组件中只能引用 `ui/src/i18n/messages/*` 中的语义化 key，不允许直接硬编码中文或英文；修改业务命名时必须同步 zh-CN 与 en-US 字典，并优先保留原 key 做兼容映射，避免旧入口残留或多语言缺 key。

### 26.2 设计决策与未解决问题

已确认设计决策：

1. **Dataset 命名策略**：保留 Dataset 现有命名，新增知识归属字段（`knowledge_scope`、`owner_account_id`、`owner_admin_user_id`、`target_tenant_id`、`target_project_id`），不做破坏性重构，保持与现有代码命名一致。
2. **用户长期记忆生效范围**：全局作用域，匹配当前系统用户级粒度。
3. **自动保存确认策略**：用户选择“后续自动保存长期记忆”后直接保存，不需要二次确认；仅在首次推荐用户开启自动保存时说明作用范围和影响。
4. **系统知识库状态管理**：只做简单 CRUD，不需要发布 / 草稿 / 下线状态，简化实现。
5. **外部数据源试点范围**：第一阶段优先支持飞书和本地文件夹，技术债清理阶段已补全 Notion / GitHub 真实连接器，当前共支持四种真实连接器。
6. **高风险确认 UI 复用**：确认 UI 做成全局通用组件，支持工具执行、外部消息发送、发布操作等所有高风险操作复用。

### Knowledge Convergence Note

- 短期后台继续以 datasets 为知识资源入口
- knowledge_base 作为中期统一语义层推进
- 在 datasets 深层后台链路补齐之前，不进行入口替换
- Document / Segment 短期继续归属 Dataset 管理
- user_memory 不并入 Dataset 深层后台

没有阻塞性未解决问题，可以开始 Phase 10 实现。



## 27. 总结

本 PRD 建议将 OpenAgent 的演进方向定义为“通用 Agent 调度平台”。系统不应推倒重来，而应复用现有 Assistant Agent、PublicAgentA2AService、McpProvider、AppConfig、AppAssignment、SSE、Dataset / Document / Segment 等基础能力，在其上逐步增加 Orchestrator、多 Agent 子池、多工具子池、系统级知识库、用户长期记忆库、用户资料内容库、模型池、Key 池、实时计费、Cost Policy、Execution Coordinator、Result Synthesizer 和 Routing Observability。

当前路径已经完成：

```text
调度骨架 -> Agent 元数据和子池标签 -> 工具治理 -> 动态工具检索 -> 成本路由 -> 多 Agent 编排 -> 结果汇总 -> 可观测性 -> 发布回滚 -> 质量反馈闭环 -> 知识库分层与长期记忆 -> 高风险工具统一确认 -> 用户侧实时计费与任务终止 -> 外部数据源同步 -> 调优建议采纳与策略变更 -> 架构审计技术债清理
```

后续推荐路径调整为：

```text
多媒体资料深度解析 -> 企业级租户 / 团队 / 项目权限矩阵 -> 长期记忆与质量评分自动化 -> 跨子池 A2A 多 Agent 协作增强
```

这样可以在已有调度平台控制面之上，继续补齐长期上下文、安全执行和用户成本控制能力，让系统从"会调度"进一步演进为"可长期理解用户、可安全执行任务、可持续运营优化"的 Agent 平台。

---




