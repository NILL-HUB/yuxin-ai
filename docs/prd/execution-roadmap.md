# 钰心AI 演进任务与执行路线

> **文档信息**
>
> | 项 | 值 |
> |---|---|
> | 文档名称 | 钰心AI 通用 Agent 调度平台 — 演进任务与执行路线 |
> | 版本 | v2.1 |
> | 日期 | 2026-06-30 |
> | 定位 | 分阶段任务清单和跟踪状态 |
> | 配套文档 | architecture-design.md（架构与模块设计） |

---

## 1. 已完成状态总览

以下阶段均已开发完成、测试通过：

| Phase | 主题 | 完成状态 |
| --- | --- | --- |
| Phase 0 | 配置中心管理员可见/普通用户 403 | ✅ 完成 |
| Phase 1 | OrchestratorService/TaskClassifier/RoutingDecision | ✅ 完成 |
| Phase 2 | AgentSubPoolRegistry/AgentPoolEntity/PoolIntentResolver | ✅ 完成 |
| Phase 3 | ToolSubPoolRegistry/ToolPoolEntity/ToolPolicyFilter | ✅ 完成 |
| Phase 4 | ToolCandidateCollector/ToolRanker/ToolSubsetBuilder/RuntimeToolMountService | ✅ 完成 |
| Phase 5 | ModelAssignmentPolicy/CostPolicyService/RuntimeModelPoolService | ✅ 完成 |
| Phase 6 | ExecutionCoordinatorService/ResultSynthesizerService | ✅ 完成 |
| Phase 7 | RoutingLogService/RoutingObservabilityService | ✅ 完成 |
| Phase 8 | OrchestrationFeatureFlag 9 个开关 | ✅ 完成 |
| Phase 9 | 路由质量反馈与调优建议 | ✅ 完成 |
| Phase 10 | MemoryCandidate/UserMemory 作用域 | ✅ 完成 |
| Phase 11 | ToolConfirmation/ToolInvocationAuditService | ✅ 完成 |
| Phase 12 | BillingMetering/CancelToken | ✅ 完成 |
| Phase 13 | 外部数据源连接 | ✅ 完成 |
| Phase 14 | 调优建议采纳与策略变更 | ✅ 完成 |

### 第三轮并行修复（P0-P3 全部完成）

| 任务 | 优先级 | 状态 |
| --- | --- | --- |
| 统一执行入口（5种模式走 ExecutionCoordinator） | P0 | ✅ |
| debug_chat 接入治理架构（默认关闭，逐步上线） | P0 | ✅ |
| 废弃空壳 ModelPoolService/KeyPoolService | P0 | ✅（已物理删除） |
| 补齐 billing_summary SSE 推送 + multi/single delta | P0 | ✅ |
| 实现 EscalationPolicy | P0 | ✅（已存在完整实现） |
| 统一 Tier 命名（前端 balanced→standard） | P0 | ✅ |
| Prompt 注入防护加固（PromptInjectionDetector） | P1 | ✅ |
| 接入 ToolConfirmationCard（4 个聊天页面） | P1 | ✅ |
| 管理员/用户身份隔离 | P1 | ✅ |
| 子池定义动态注册 | P1 | ✅ |
| 6 个管理页 i18n 补齐（实际完成8个） | P2/P3 | ✅ |
| 模型类型定义集中化（orchestration.ts） | P3 | ✅ |
| SSE 事件枚举补齐 | P2 | ✅ |
| 路由守卫修复 | P1 | ✅ |

---

## 2. 待修复差异清单

### 差异 2：模型档位命名不一致（✅ 已修复）

`CostPolicyService` 使用 `cheap/standard/strong`，`TaskClassifierService` 已统一为 `standard`。

### 差异 3：PoolIntentResolver 纯关键词匹配（中优先级）

`PoolIntentResolver.resolve()` 接收 `classifier_result` 参数但未使用，仅靠 query 文本关键词匹配 6 个子池。

### 差异 5：ResultSynthesizerService 多 Agent 路径被绕过（✅ 已修复）

多 Agent 路径已接入 `ResultSynthesizerService`，`synthesis_meta` 嵌入 SSE 推送。

### 差异 6：user_memory.scope 字段未生效（✅ 已修复）

`recall_relevant_memories` 已按 `owner_account_id`、`status` 和 `scope` 过滤。`memory_candidate` 表已添加 `scope` 字段。

---

## 3. 最新任务清单

### P0（已完成）

| 任务 | 文件 | 状态 |
| --- | --- | --- |
| **开通 debug_chat 编排开关** | `app_service.py` | ✅ 已开通并监控 |

### P1（已完成）

| 任务 | 文件 | 状态 |
| --- | --- | --- |
| **删除死代码 KnowledgeRetrievalOrchestrator** | `knowledge_retrieval_orchestrator.py` | ✅ 已删除 |
| **后端 Tier 命名统一** | `task_classifier_service.py` | ✅ 代码已正确使用 `standard`，无需修改 |
| **修复 UserMemory.scope 硬编码** | `scoped_knowledge_service.py` + migration | ✅ scope 参数+过滤+memory_candidate 字段 |
| **接入 ResultSynthesizer 到多 Agent 路径** | `multi_agent_executor.py` | ✅ 已注入，synthesis_meta 嵌入 SSE |

### P2（已完成）

| 任务 | 文件 | 状态 |
| --- | --- | --- |
| **pgvector scope 过滤增强** | `knowledge_vector_service.py` + `retrieval_service.py` | ✅ KnowledgeVectorService.search() 和 search_in_knowledge_base() 支持 knowledge_scope 过滤 |
| **打通记忆确认对话推送** | `assistant_agent_service.py` + `chat-stream.ts` + `HomeView.vue` | ✅ MemoryConfirmationCard 接入对话 SSE 流 |

### P3（已完成）

| 任务 | 文件 | 状态 |
| --- | --- | --- |
| **多 Agent DAG 重写** | `dag_entity.py`, `dag_engine_service.py`, `agent_instance_pool.py`, `multi_agent_executor.py`, `execution_coordinator_service.py`, `task_decomposer.py`, `test_dag_engine.py`, 共 7 个新/改文件 | ⏳ 第一阶段完成（实体+引擎+池+Executor重构+TaskDecomposer增强+DAG测试 37 passed） |

### P3（远期待实施）

| 任务 | 描述 |
| --- | --- |
| 多 Agent DAG 可视化（前端） | DAG 执行过程前端可视化 |
| 生活场景工具扩展（邮件/日历/任务管理） | |
| 多模态输入输出（语音/文档/图片） | |
| 社交社区深化 | |
| PoolIntentResolver 语义升级 | 接入 LLM 意图识别替代纯关键词匹配 |

---

## 3.1 池治理打通与工具统一

### 背景与依赖关系

基于架构审计（详见 architecture-design.md 4.3/10.1/10.2/10.5 节），池治理模块是"配置孤岛"——治理策略表不被运行时调用链读取。组合工具（workflow/agent_binding）的治理透传依赖三个前置：数据结构扩展 → CompositeToolResolver → RuntimeToolGovernanceGate → 注入挂载点。任务必须按依赖顺序执行。

```text
依赖链：
P0-1 数据结构扩展（ToolSourceType + RuntimeToolDescriptor + CompositeComponentRef）
  ↓
P0-2 CompositeToolResolver（依赖 P0-1 的 CompositeComponentRef）
  ↓
P0-3 RuntimeToolGovernanceGate（依赖 P0-2 的 CompositeToolResolver）
  ↓
P0-4 注入 AppService._build_runtime_tools_for_config（依赖 P0-3）
  ↓
P1-1 组合工具治理透传（依赖 P0-2 + P0-3）
P1-2 渐进式启用机制（依赖 P0-4，可与 P1-1 并行）
P1-3 skill 工具包治理（独立，可并行）
P1-4 WorkflowTool 纳入治理（独立，可并行）
P1-5 AgentBinding 委派工具纳入治理（依赖 P0-3，可并行）
P0-5 AgentPoolConfig 接入 AgentCandidateCollector（完全独立，可并行）
P0-6 统一 tool_id 格式映射（完全独立，可并行）
```

### P0：数据结构与解析器（前置）

| 任务 | 文件 | 状态 | 说明 |
| --- | --- | --- | --- |
| **P0-1 扩展 ToolSourceType + RuntimeToolDescriptor + CompositeComponentRef** | tool_inventory_entity.py, runtime_tool_entity.py | ✅ 已完成 | ToolSourceType 新增 WORKFLOW/SKILL/AGENT_BINDING；RuntimeToolDescriptor 新增 is_composite/composite_kind/composite_components/composite_root_id/runtime_name_stable；新增 CompositeComponentRef dataclass |
| **P0-2 实现 CompositeToolResolver** | 新增 composite_tool_resolver.py | ✅ 已完成 | 递归解析组合工具成员工具，复用 agent_binding 环检测思路，max_depth=8；workflow 解析 graph["nodes"]，agent_binding 递归加载目标 AppConfig，公开 App 不展开；20 测试通过，覆盖率 83% |
| **P0-3 实现 RuntimeToolGovernanceGate** | 新增 runtime_tool_governance_gate.py | ✅ 已完成 | 治理注入门：BaseTool → RuntimeToolDescriptor → 查询 ToolGovernancePolicy → ToolPolicyFilter 过滤 → 返回过滤后列表 + 审计上下文；组合工具调 CompositeToolResolver 计算有效风险等级 |
| **P0-4 注入 AppService._build_runtime_tools_for_config** | app_service.py, module.py | ✅ 已完成 | 在 return 前增加可选参数 governance_gate，向后兼容；DI 注册 CompositeToolResolver + RuntimeToolGovernanceGate；governance_gate=None 时行为不变 |
| **P0-5 AgentPoolConfig 接入 AgentCandidateCollector** | agent_pool_service.py | ✅ 已完成 | AgentCandidateCollector.collect() 查 App 时 LEFT JOIN AgentPoolConfig，读取 primary_pool/risk_level/model_tier/routing_priority；21 测试通过 |
| **P0-6 统一 tool_id 格式映射** | tool_inventory_service.py | ✅ 已完成 | 统一 tool_id 格式（builtin:{provider}:{tool} 等 7 种），新增 build_tool_id/parse_tool_id 辅助函数；16 测试通过 |

### P1：组合工具治理透传与渐进式启用

| 任务 | 文件 | 状态 | 说明 |
| --- | --- | --- | --- |
| **P1-1 组合工具治理透传** | runtime_tool_governance_gate.py | ✅ 已完成 | 部分阻断策略（dangerous/disabled/unhealthy 整体阻断，sensitive 需确认）；治理策略双层叠加（组合工具层级 + 成员层级取严）；28 测试通过 |
| **P1-2 渐进式启用机制** | governance_mode_resolver.py, orchestration_feature_flag_entity.py, runtime_tool_governance_gate.py, app_service.py, module.py | ✅ 已完成 | 三阶段开关（ENABLE_POOL_GOVERNANCE_OBSERVE_ONLY/BLOCK_SENSITIVE/BLOCK_ALL）；GovernanceModeResolver 解析当前模式；block_sensitive_only 参数；160 测试通过 |
| **P1-3 skill 工具包治理** | tool_inventory_service.py | ✅ 已完成 | ToolCandidateCollector 新增 _collect_skill_tools，skill:{skill_package_id} 整体治理；5 测试通过 |
| **P1-4 WorkflowTool 纳入治理** | tool_inventory_service.py | ✅ 已完成 | ToolCandidateCollector 新增 _collect_workflow_tools，workflow:{workflow_id} 整体治理；6 测试通过 |
| **P1-5 AgentBinding 委派工具纳入治理** | runtime_tool_governance_gate.py | ✅ 已完成 | agent_binding:{app_id} 治理；私有 App 递归解析成员，公开 App 黑盒不展开；4 测试通过 |

### P2：管理界面与远期扩展

| 任务 | 文件 | 状态 | 说明 |
| --- | --- | --- | --- |
| **P2-1 Agent 元数据补充 prompt 摘要展示** | AgentPoolView.vue, admin_agent_pool_service.py | ✅ 已完成 | 池治理页面展示 AppConfig.preset_prompt 摘要（只读，tooltip+truncate，批量预取避免 N+1） |
| **P2-2 工具治理页面扩展来源类型筛选** | ToolGovernanceView.vue, admin_tool_governance_schema.py, admin_tool_governance_service.py | ✅ 已完成 | SOURCE_TYPES 从 4 项扩展为 7 项（api_tool/mcp/skill/builtin/knowledge/workflow/agent_binding），同步更新 schema 校验和 service stats 初始化 |
| **P2-3 Workflow ToolNode 扩展（远期）** | tool_entity.py, tool_node.py, composite_tool_resolver.py | ✅ 已完成 | ToolNodeData.tool_type 从 2 种扩展为 7 种（+mcp/knowledge/skill/workflow/agent_binding）；execute 按 tool_type 分发复用底座 service；workflow/agent_binding 嵌套含环检测（max_depth=8，call_stack 传递）；CompositeToolResolver._resolve_workflow 支持解析 7 种节点类型；22+7 测试通过 |

### 渐进式启用路线图

```text
阶段 1（观测期，2 周）：
  → RuntimeToolGovernanceGate 记录过滤决策到路由日志
  → 不实际阻断工具挂载
  → 管理员观察"如果启用阻断会发生什么"
  → 目标：验证治理策略覆盖率、tool_id 映射准确性、CompositeToolResolver 解析正确性
  → 验收：路由日志中工具治理决策覆盖率 ≥ 95%，组合工具成员链路完整

阶段 2（敏感工具阻断，2 周）：
  → 只对 risk_level=sensitive/dangerous 的工具阻断（含组合工具的有效风险等级）
  → safe/controlled 工具继续放行
  → 组合工具按部分阻断策略处理（见架构文档 10.2.3）
  → 目标：验证阻断机制可靠性，收集误过滤案例

阶段 3（全量启用）：
  → 所有工具按治理策略过滤
  → 管理员可按 source_type / tool_pool 灰度启用
  → 目标：池治理完全生效
```

### 验收标准

| 指标 | 目标 |
| --- | --- |
| AgentPoolConfig 读取率 | AgentCandidateCollector 100% 读取 AgentPoolConfig 路由元数据 |
| ToolGovernancePolicy 读取率 | AppService._build_runtime_tools_for_config 100% 经过 RuntimeToolGovernanceGate |
| 工具来源类型覆盖 | 7 种来源类型全部纳入 ToolSourceType（builtin/api_tool/mcp/knowledge/workflow/skill/agent_binding） |
| 治理策略命中率 | 路由日志中工具治理决策覆盖率 ≥ 95% |
| 组合工具治理透传 | workflow/agent_binding（私有）通过 CompositeToolResolver 递归解析成员，有效风险等级 = max(成员风险等级) |
| tool_id 稳定性 | 治理层只依赖 tool_id（全部稳定），不依赖 runtime_name（workflow/skill 不稳定） |
| 组合工具部分阻断 | dangerous 整体阻断、sensitive 需确认、disabled 整体阻断、unhealthy 降级或阻断 |
| CompositeToolResolver 环检测 | 循环引用不导致无限递归，max_depth=8 |

---

## 4. 技术债清理

| 任务 | 优先级 | 状态 | 说明 |
| --- | --- | --- | --- |
| ilike 转义 | P1 | ✅ 已完成 | 22 个 service 文件全覆盖 |
| 抽取统一 to_dict 基类（SerializableMixin） | P1 | ✅ 完成 | 12 类/6 文件迁移完成 |
| OrchestratorService DI 改造 | P2 | ✅ 完成 | 6 处 or X() 兜底已移除，None 检查替代 |
| 反转 core→service 反向依赖 | P2 | ✅ 完成 | UserMemoryServicePort/ObjectStoragePort 已落地 |
| 拆分 deep_thinking_agent.py（~2410 行） | P3 | ✅ 完成 | 17 个纯函数抽取到 deep_thinking_utils.py |
| 拆分 app_service.py（~2368 行） | P3 | 🟡 部分完成 | AppIconService 已抽取；AppDebugService 经评估确认深度耦合（debug_chat 依赖 `_build_runtime_tools`/`_create_runtime_agent`/`_stream_agent_events` 等共享私有方法，同时被子应用 A2A 调用 `_invoke_agent_binding_target` 与 `prompt_compare_chat` 共用），强行抽取会破坏封装或引入 AppService↔AppDebugService 循环依赖，已改用 `#region AppDebug` 标记 5 处 debug 方法块（会话管理/长期记忆快照/调试主流程/停止调试/消息分页）便于定位与折叠，维持内聚 |
| ExecutionModeSelector | P4 | ✅ 已完成 | |
| 执行链路接通（5 种模式全量） | P4 | ✅ 已完成 | |
| 废弃空壳 ModelPoolService/KeyPoolService | P5 | ✅ 已完成 | 物理删除 |
| 补齐 billing_summary SSE | P5 | ✅ 已完成 | 全路径推送+delta 补全 |
| 实现 EscalationPolicy | P5 | ✅ 已完成 | 完整实现+测试覆盖 |
| 统一 Tier 命名（前端） | P5 | ✅ 已完成 | |
| 统一 Tier 命名（后端） | P5 | ✅ 完成 | TaskClassifierService 已使用 standard |
| 删除 KnowledgeRetrievalOrchestrator | P5 | ✅ 完成 | |
| 修复 UserMemory.scope | P5 | ✅ 完成 | scope 参数+过滤+字段 |
| 接入 ToolConfirmationCard | P5 | ✅ 已完成 | 4 个聊天页面 |
| Prompt 注入防护加固 | P5 | ✅ 已完成 | PromptInjectionDetector |

---

## 5. 管理端五板块 UX 治理

### 背景

管理端五个板块（资源编排 / 资源运营 / 池治理 / 编排控制 / 观测中心）的职责分离逻辑清晰，但实现完整度不足：资源运营是空壳、资源编排半成品、数据所有权混乱、跨板块导航断裂。经全面调研发现 5 类重叠、7 项缺陷，需分阶段修复。

### 已完成（UX 快速修复）

| 任务 | 文件 | 状态 | 说明 |
| --- | --- | --- | --- |
| i18n 标签修复 | zh-CN.ts, en-US.ts | ✅ 已完成 | 资源编排 tools 标签 API工具治理→API工具管理，消除与池治理板块命名冲突 |
| 治理模式状态栏 | GovernanceModeBanner.vue（新建）, AgentPoolView.vue, ToolGovernanceView.vue | ✅ 已完成 | 池治理页面顶部显示当前治理模式（观测期/敏感阻断/全量），含切换模式+查看决策日志链接 |
| 编排控制开关分组 | OrchestrationFlagsView.vue | ✅ 已完成 | 按域分组（池治理开关/其他），池治理组含三阶段优先级提示 |
| 观测中心跨板块跳转 | RoutingLogsView.vue | ✅ 已完成 | agent_pool/tool_pool 列加跳转链接到池治理配置页 |

### 待修复任务

| 任务 | 优先级 | 状态 | 说明 |
| --- | --- | --- | --- |
| **UX-1 ToolsView 改造为真正的工具管理** | P1 | ⏳ 待开始 | 当前只读展示 ToolPolicy，与 ToolGovernanceView 严重重叠。改为管理工具本身（创建/编辑/删除 API Tool Provider），与 ToolGovernanceView 职责分离 |
| **UX-2 AppsView 重写 + 数据所有权统一** | P1 | ⏳ 待开始 | 裸 HTML 重写为 Arco Design 风格；primary_pool/risk_level/routing_priority 只在 AgentPoolView 编辑，AppsView 只读展示 |
| **UX-3 资源运营补充上架/下架操作** | P2 | ⏳ 待开始 | 每个商店页面加管理员视角的上架/下架按钮，而非仅复用公共商店组件 |
| **UX-4 AdminWorkflowsView toggle-public 移到资源运营** | P2 | ⏳ 待开始 | 上架是运营动作，不应在编排页面。移到资源运营的工作流商店页 |
| **UX-5 AdminDatasetsView/MCP/Skills 补充 CRUD** | P2 | ⏳ 待开始 | 资源编排 3 个只读页面补充创建/编辑/删除，使"编排"名副其实 |
| **UX-6 ModelsView 成本策略移到计费运营** | P3 | ⏳ 待开始 | 成本策略（maxCostPerRequest/billingMode）是计费策略，应从池治理移到计费运营板块 |
| **UX-7 审计日志加跳转** | P3 | ⏳ 待开始 | AuditLogsView 的 resourceType/resourceId 可点击跳转到对应资源管理页 |
| **UX-8 商店预览模式** | P3 | ⏳ 待开始 | 资源运营上架操作旁加"预览商店效果"按钮，让管理员看到用户视角 |

### 板块职责定义（架构文档对齐）

| 板块 | 职责 | 管什么 | 不管什么 |
| --- | --- | --- | --- |
| 资源编排 | 资源实体 CRUD | 资源存在不存在、长什么样 | 上架到商店、使用规则、开关 |
| 资源运营 | 上下架到商店 | 用户能不能看到、能不能安装 | 资源本身定义、使用规则 |
| 池治理 | 使用规则策略 | 风险等级、路由优先级、可见性、限流 | 资源本身、规则是否生效 |
| 编排控制 | 运行时开关 | 策略启用/灰度/回滚/熔断 | 规则定义、事后观测 |
| 观测中心 | 事后观测反馈 | 决策记录、质量反馈、审计 | 规则定义、开关控制 |
