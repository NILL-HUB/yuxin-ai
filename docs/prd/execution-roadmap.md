# OpenAgent 演进任务与执行路线

> **文档信息**
>
> | 项 | 值 |
> |---|---|
> | 文档名称 | OpenAgent 通用 Agent 调度平台 — 演进任务与执行路线 |
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
| **Weaviate scope 过滤增强** | `knowledge_vector_service.py` + `retrieval_service.py` | ✅ KnowledgeVectorService.search() 和 search_in_knowledge_base() 支持 knowledge_scope 过滤 |
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
P0-5 AgentPoolConfig 接入 AgentCandidateCollector（独立，可并行）
  ↓
P1-1 组合工具治理透传（依赖 P0-2 + P0-4）
  ↓
P1-2 渐进式启用机制（依赖 P0-4 + P1-1）
```

### P0：数据结构与解析器（前置）

| 任务 | 文件 | 状态 | 说明 |
| --- | --- | --- | --- |
| **P0-1 扩展 ToolSourceType + RuntimeToolDescriptor + CompositeComponentRef** | tool_inventory_entity.py, runtime_tool_entity.py | ⬜ 待开始 | ToolSourceType 新增 WORKFLOW/SKILL/AGENT_BINDING；RuntimeToolDescriptor 新增 is_composite/composite_kind/composite_components/composite_root_id/runtime_name_stable；新增 CompositeComponentRef dataclass |
| **P0-2 实现 CompositeToolResolver** | 新增 composite_tool_resolver.py | ⬜ 待开始 | 递归解析组合工具成员工具，复用 agent_binding 环检测思路，max_depth=8；workflow 解析 graph["nodes"]，agent_binding 递归加载目标 AppConfig，公开 App 不展开 |
| **P0-3 实现 RuntimeToolGovernanceGate** | 新增 runtime_tool_governance_gate.py | ⬜ 待开始 | 治理注入门：BaseTool → RuntimeToolDescriptor → 查询 ToolGovernancePolicy → ToolPolicyFilter 过滤 → 返回过滤后列表 + 审计上下文；组合工具调 CompositeToolResolver 计算有效风险等级 |
| **P0-4 注入 AppService._build_runtime_tools_for_config** | app_service.py L990-1059 | ⬜ 待开始 | 在 return 前增加可选参数 governance_gate，向后兼容；静态方法通过参数传入治理服务，不破坏现有调用方 |
| **P0-5 AgentPoolConfig 接入 AgentCandidateCollector** | agent_pool_service.py | ✅ 已完成 | AgentCandidateCollector.collect() 查 App 时 LEFT JOIN AgentPoolConfig，读取 primary_pool/risk_level/model_tier/routing_priority 做过滤；独立于 P0-1~P0-4，可并行 |
| **P0-6 统一 tool_id 格式映射** | tool_inventory_service.py | ⬜ 待开始 | 统一 tool_id 格式（builtin:{provider}:{tool} 等 7 种），建立治理表与运行时工具的强映射；tool_id 全部稳定（基于 UUID），见架构文档 10.5.3 |

### P1：组合工具治理透传与渐进式启用

| 任务 | 文件 | 状态 | 说明 |
| --- | --- | --- | --- |
| **P1-1 组合工具治理透传** | tool_inventory_service.py, admin_tool_governance_service.py | ⬜ 待开始 | 依赖 P0-2 + P0-4。workflow/agent_binding 有效风险等级 = max(成员风险等级)；部分阻断策略（dangerous 整体阻断，sensitive 需确认，disabled 整体阻断）；治理策略双层叠加（组合工具层级 + 成员层级取严） |
| **P1-2 渐进式启用机制** | OrchestrationFeatureFlag | ⬜ 待开始 | 依赖 P0-4 + P1-1。三阶段：阶段1只观测不阻断 → 阶段2敏感工具阻断 → 阶段3全量启用，通过特性开关控制 |
| **P1-3 skill 工具包治理** | skill_service.py, tool_inventory_service.py | ⬜ 待开始 | skill 不是组合工具，按工具包治理：skill:{skill_package_id} 整体治理，或 skill:{skill_package_id}:{tool_name} 细粒度治理；SkillToolFactory 构建时查询治理策略 |
| **P1-4 WorkflowTool 纳入治理** | tool_inventory_service.py, app_config_service.py | ⬜ 待开始 | WorkflowTool 构建时查询治理策略，受 ToolPolicyFilter 约束；workflow:{workflow_id} 作为 tool_id |
| **P1-5 AgentBinding 委派工具纳入治理** | app_service.py | ⬜ 待开始 | agent_binding:{app_id} 作为 tool_id；私有 App 通过 CompositeToolResolver 透传成员治理；公开 App 仅 app_id 层级治理 |

### P2：管理界面与远期扩展

| 任务 | 文件 | 状态 | 说明 |
| --- | --- | --- | --- |
| **P2-1 Agent 元数据补充 prompt 摘要展示** | AgentPoolView.vue, admin_agent_pool_service.py | ⬜ 待开始 | 池治理页面展示 AppConfig.preset_prompt 摘要（只读，不在此编辑） |
| **P2-2 工具治理页面扩展来源类型筛选** | ToolGovernanceView.vue, admin_tool_governance_schema.py | ⬜ 待开始 | source_type 筛选项增加 workflow/skill/agent_binding |
| **P2-3 Workflow ToolNode 扩展（远期）** | tool_entity.py, tool_node.py | ⬜ 待开始 | 扩展 ToolNodeData.tool_type 支持 mcp/skill/workflow/agent_binding，使 workflow 能嵌套所有工具类型；当前底座仅支持 builtin_tool/api_tool |

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
| 拆分 app_service.py（~2368 行） | P3 | 🟡 部分完成 | AppIconService 已抽取；AppDebugService 因 debug 方法与 AppService 深度耦合暂缓 |
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
