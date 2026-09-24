# Agent 池与工具池设计

> 本文档为主架构文档的子模块，包含动态子集归集、Agent 池设计和工具池设计的完整内容。
>
> **主文档**: [architecture-design.md](../architecture-design.md)
> **相关模块**: [02-knowledge-base.md](./02-knowledge-base.md) | [03-orchestration-infra.md](./03-orchestration-infra.md)
>
> **定位说明**：编排主导权已由旧 Orchestrator 串行链路移交至 Conductor（指挥官）+ ExecutionCoordinatorService（见 [03-orchestration-infra.md](./03-orchestration-infra.md)）。本文档描述的 Agent 池/工具池组件（候选收集、策略过滤、排序、跨池子集构建、运行时挂载）是**被 Conductor / Orchestrator / ExecutionCoordinatorService 消费的候选收集与排序层**，不再包含主入口侧的路由/意图决策职责。池组件自身按确定性策略运行，不承担 LLM 编排决策。

---

## 8. 动态子集归集与策略过滤设计

### 8.1 为什么需要动态子集

编排决策层（Conductor/Orchestrator）或执行器为本次任务选定执行 Agent 时，如果直接面对完整 Agent 池和完整工具池，会产生四类系统性问题：

1. **上下文噪声**：大量无关 Agent/工具描述会降低模型选择准确率。
2. **权限风险**：普通用户或低权限 Agent 可能通过 Prompt 注入触发敏感工具。
3. **成本风险**：简单任务可能误选强模型 Agent 或高成本工具。
4. **运维风险**：工具和 Agent 数量增长后，路由不可解释、不可调优。

因此目标架构必须把“完整池”变成“本次任务可见子集”。编排层与执行器只在受控子集中做选择，而不是直接访问全量池。

> **实现备注**：真实实现中，动态子集归集由 `agent_pool_service.py` 承载——`AgentCandidateCollector`（候选收集）、`AgentPolicyFilter`（策略过滤）、`AgentRanker`（排序）、`CrossPoolAgentSubsetBuilder`（跨子池子集构建）均已实现；候选来源**已纳入 forked（含 draft 状态）Apps**（`agent_pool_service.py` `collect()`，`allow_draft=True`）。`AgentSubPoolRegistry`（`internal/entity/agent_pool_entity.py`）与 `AgentInventory`（`internal/service/agent_pool_aggregate_service.py`）**已作为独立实现落地**；仅 `AgentRouter` 未作为独立类存在——真实链路以"子池定义（`sub_pool_definition`）+ 候选收集/过滤/排序/裁剪"为骨架。

### 8.2 Agent 多子池归集流程

```text
Conductor / Orchestrator / ExecutionCoordinatorService（编排决策层）
  -> TaskContext（含 task_id / required_capabilities / agent_pool / model_tier 等）
  -> AgentCandidateCollector
  -> AgentPolicyFilter
  -> AgentRanker
  -> CrossPoolAgentSubsetBuilder
  -> 选定 Agent 交执行器（SingleAgentExecutor / MultiAgentExecutor）
```

> **编排层与池层边界**：流程起点是编排决策层的输出（如 `ConductorPlan` / `RoutingDecision` / `TaskPlan` 中的子任务），而非主入口内嵌的 `PoolIntentResolver → AgentSubPoolRegistry → AgentInventory` 串行。`agent_pool_service.py` 暴露给编排层的入口为 `CrossPoolAgentSubsetBuilder.build/build_subset`，内部完成候选收集 → 过滤 → 排序 → 裁剪。`PoolIntentResolver` 的实时调用仅残留在 `home_service.py`（`/home` 意图摘要路径，见 [03-orchestration-infra.md](./03-orchestration-infra.md) 13.6），不属于主入口调度主链路。

#### 8.2.1 Agent 子池注册与管理

编排层按子池元数据（`sub_pool_definition` 表，字段为 `pool_type`/`name`/`label`/`description`/`visible_to_user`/`default_enabled`/`default_capabilities`/`task_keywords`/`is_system`/`sort_order`/`enabled`）与任务信号选取子池范围，而不是先经独立 `AgentSubPoolRegistry` 归集再路由。

管理多个 Agent 子池，而不是把所有 Agent 放进一个无差别大池。示例子池：

| 子池 | 示例 Agent | 适用任务 |
| --- | --- | --- |
| coding | UI Agent、前端 Agent、后端 Agent、测试 Agent、DevOps Agent | 写代码、改代码、部署、排错 |
| office | P 图 Agent、文档整理 Agent、PPT Agent、表格 Agent | 办公处理、文档整理、图片处理 |
| data | 数据分析 Agent、报表 Agent、SQL Agent | 数据查询、分析、可视化 |
| research | 搜索研究 Agent、行业分析 Agent、竞品分析 Agent | 调研、报告、资料整理 |
| customer_service | 客服 Agent、工单 Agent、FAQ Agent | 用户支持、售后、知识问答 |
| internal_admin | 运维 Agent、审计 Agent、系统管理 Agent | 管理员内部维护，不对普通用户自动开放 |

子池命中由编排层（Conductor 的 `agent_pool` 字段 / 旧链路 `PoolIntentResolver` 的输出）或 `AgentCandidateCollector.collect_by_pools` 的任务信号决定。一个需求可以命中多个子池，例如"P 图 + 写代码"同时命中 office 和 coding。

#### 8.2.2 AgentInventory

AgentInventory 负责从相关子池读取可治理 Agent 清单（作为候选收集的数据视图），来源包括：

- public App。
- 本人自建 App（`App.account_id = 当前账号`）。
- forked（含 draft 状态）App。
- 内置轻量 Agent。
- 内置强推理 Agent。
- 深度思考 Agent。
- 外部 A2A Agent。

> 管理员在配置中心创建的 App 其 `account_id` 为 `NULL`（平台级资源，见迁移 `e0a1b2c3d4e5`），因此**只在 `is_public=True` 时**才作为候选被收集，不会因"管理员创建"而自动进入某个账号的候选集。

它不直接暴露给模型，只作为候选来源。

#### 8.2.3 AgentCandidateCollector

AgentCandidateCollector 负责按任务在相关 Agent 子池内分别召回候选 Agent。

召回信号包括：

- query 语义相似度。
- 编排层（Conductor / 旧链路 TaskClassifier）输出的 intent。
- required_capabilities。
- task_types。
- complexity。
- input_modalities。
- 用户已分配应用。
- public 应用。
- 管理员指定默认 Agent。

> **实现备注**：`AgentCandidateCollector.collect()`（`agent_pool_service.py`）真实实现按 `public + own + forked` 三类来源收集，`forked` 来源调用 `_append_app_candidate(..., allow_draft=True)` 允许 draft 状态 App 进入候选。另提供 `collect_by_pools()`（按子池元数据收集）供上层使用。
>
> **`collect_raw()` 是治理链路的承重件（不可退化为 `collect()` 转发）**：它返回**保留 `app` ORM 对象**的候选（无 `app` 键的仅有内置 Agent），`AgentPolicyFilter` 依赖 `candidate["app"]` 读取 `app.status` / `app.is_public` 等字段执行硬过滤。其过滤循环开头是 `if app is None: accepted.append(candidate)`——一旦 `collect_raw()` 退化成 `collect()` 的序列化转发（序列化结果不含 `app`），**全部候选会被无条件放行**，`pool_not_visible` / `agent_disabled` / `risk_level_requires_confirmation` / `cost_level_exceeds_budget` 等规则集体静默失效。历史上 `collect_raw()` 曾被同类的第二个定义覆盖而长期失效，回归防护见 `test/internal/service/test_pool_governance_fixes.py::test_collect_raw_must_preserve_app_object`（刻意使用**真实 collector** 而非桩，避免再次被掩盖）。

输出示例：

```json
{
  "task_id": "task-1",
  "raw_candidates": [
    {
      "agent_id": "agent-a",
      "source": "own",
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

| 维度 | 说明 | 拒绝原因（代码实际取值） |
| --- | --- | --- |
| 来源授权 | 仅 `public` / `own` / `forked` 三种来源可进入候选 | `app_not_authorized` |
| 发布状态 | 非 `published` 不进入（`forked` 来源的 draft App 例外） | `app_not_published` |
| 子池可见性 | `internal_admin` 池不对普通用户可见 | `pool_not_visible` |
| 启用开关 | `metadata.enabled=False` 不进入候选 | `agent_disabled` |
| 风险等级 | 高风险 Agent 需确认流程才放行 | `risk_level_requires_confirmation` |
| 成本策略 | 超预算 Agent 被过滤 | `cost_level_exceeds_budget` |
| 输入能力 | 不支持图片/文件/长上下文的 Agent 不能处理对应任务 | `input_modality_not_supported` |
| 工具策略 | 任务需要工具但 Agent 不允许该工具类别时过滤 | `tool_category_not_allowed` |

**候选收集必须 fail closed**：`CrossPoolAgentSubsetBuilder.build()` 收集候选抛异常时，必须退化为**空候选**，不得回退到 `AgentPoolService.list_agents()` 这类"直读子池清单、不过滤、不按 account 隔离"的路径——那等于在异常时静默放行全部 Agent，使上表全部规则集体失效。该行为与工具侧 `_build_tool_subset` 一致（异常即空候选），回归防护见 `test/internal/service/test_orchestrator_service.py::test_agent_candidate_collection_failure_fails_closed`。

过滤输出必须保留原因：

```json
{
  "filtered_out": [
    {
      "agent_id": "agent-x",
      "reason": "app_not_authorized"
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

> **实现备注**：`CrossPoolAgentSubsetBuilder`（`agent_pool_service.py`）对外入口为 `build(account_id, *, primary_pool=None)` 与 `build_subset(...)` / `build_subset_from_candidates(...)`，供 Conductor / Orchestrator / 执行器在拿到编排决策后调用，产出结果再送入 ExecutionCoordinatorService 分派执行。

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
编排决策层（Conductor / Orchestrator / 执行器）
  + TaskContext + SelectedAgent
  -> ToolCandidateCollector（tool_selector_service / tool_inventory_service）
  -> ToolPolicyFilter
  -> ToolRanker
  -> CrossPoolToolSubsetBuilder
  -> RuntimeToolMountService
```

> **实现备注**：真实实现中，工具候选侧由 `tool_selector_service.py`（ToolCandidateCollector）与 `tool_inventory_service.py` 承载，治理过滤由 [10.5.2](#1052-工具治理打通) 的 `RuntimeToolGovernanceGate` + `ToolPolicyFilter` 注入 `AppRuntimeService.build_runtime_tools_for_config`；`ToolSubPoolRegistry`（`internal/entity/tool_pool_entity.py`，已在 DI 容器注册）**已作为独立实现落地**；`AgentRouter` 未作为独立类存在。旧文档列出的 `PoolIntentResolver → ToolSubPoolRegistry → ToolInventory` 串行已不再是主链路。

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

高风险工具处理策略（取值与 `internal/entity/tool_inventory_entity.py` 的 `RiskLevel` 一致）：

```text
safe / low / medium -> 可自动挂载
high -> 需权限过滤；requires_confirmation=True 时须经用户确认（allow_confirmation=False 则不挂载）
sensitive -> 默认不挂载，除非管理员策略显式允许（阶段2/3 阻断）
dangerous -> 一律不自动挂载（ToolPolicyFilter 直接拒绝；阶段2/3 阻断）
```

> **枚举说明**：运行时工具风险等级为 6 值 `safe/low/medium/high/sensitive/dangerous`
> （`RiskLevel`，唯一事实源 `RISK_LEVEL_VALUES`）；管理端页面下拉、
> `admin_tool_governance_schema` 校验与 `get_governance_stats` 分桶共用该常量。
> **Agent 风险等级不同**，仅 3 值 `safe/medium/high`（`AgentRiskLevel`），两者不可混用。

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
      "risk_level": "medium",
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

这意味着调度系统不是"把工具交给 Agent 后就结束"，而是必须闭环控制（执行闭环由 [ExecutionCoordinatorService](./03-orchestration-infra.md) 承担）：

```text
编排规划 -> 约束 -> 执行 -> 校验 -> 汇总 -> 记录
```

其中"校验"包含 ExecutionCoordinatorService 的执行快照（`subtask_registry.snapshot`）、失败子任务收集与 `plan_repairer` 修复（Conductor `repair_plan`），"汇总"由 ResultSynthesizer 承担。



## 9. Agent 池设计

### 9.1 Agent 元数据

每个 Agent 需要新增或补充以下元数据：

| 字段 | 说明 | 示例 |
| --- | --- | --- |
| capabilities | 能力标签 | `research`, `coding`, `summarization`, `data_analysis` |
| task_types | 适合任务类型 | `qa`, `analysis`, `workflow`, `tool_use` |
| complexity_level | 适合复杂度 | `simple`, `medium`, `complex` |
| model_tier | 默认模型档位 | 模型池档位码 `1`, `2`, `3`（见 03-orchestration-infra.md §12.1） |
| cost_level | 成本等级 | `low`, `medium`, `high` |
| routing_priority | 路由优先级 | 0-100 |
| allowed_tool_categories | 可用工具类别 | `search`, `mcp`, `knowledge`, `database` |
| risk_level | Agent 风险等级 | `safe`, `medium`, `high` |
| enabled | 是否启用 | `true` / `false`（`false` 时被过滤为 `agent_disabled`） |
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

> **`internal_admin` 池的消费方（2026-09 已接线）**：该子池此前为"预留未接线"。P1b 起，管理端 Agent 治理链路（`api/internal/service/admin_agent_execution_service.py`）是其消费方——它经 `AdminAgentPrincipal` 携带管理端身份执行板块动作。与用户端 Agent 候选收集（`AgentCandidateCollector`）是**两条互不交叉的链路**：用户端链路按 `account_id` 隔离、走 `AgentPolicyFilter`；管理端链路按 `admin_user_id` 隔离、走板块动作注册表（`api/internal/core/admin_agent_boards.py`）。两条链路的候选/授权来源不同，不可互相替代。

> **P2 起对话链路也是消费方（2026-09-17）**：管理端 Agent 的**对话式入口**
> （`api/internal/service/admin_agent_chat_service.py`）同样装配白名单式板块工具
> （`admin_agent_chat_tools.build_board_tools`，每板块一个工具），复用同一条执行层
> （`AdminAgentExecutionService.run`）与同一套板块动作注册表。它仍属**管理端链路**，
> 按 `admin_user_id` 隔离，**不进入**用户端候选收集（`AgentCandidateCollector`）。
>
> 另注：P2 的**预置 Agent 不落 Agent 池**——池成员是用户端 `app`（`agent_pool_config.app_id`
> 非空）且无授权字段，而治理 Agent 的授权（`granted_permissions` / `automation_policy`）
> 挂在 `admin_agent` 表；塞进池只能伪造 `app` 行，正好落进用户端候选域。故预置落
> `admin_agent`（`builtin_key` 幂等键），池继续只做用户端 App 的候选/可见性路由。

### 9.3 Agent 来源

Agent 池第一阶段复用现有 App：

- public App。
- 本人自建 App。
- 本人从应用商店添加（fork）的 App。

> `visibility` 并非 `agent_metadata` 的输入字段，而是 `AgentPolicyFilter` 序列化候选时的**派生输出**：`app.is_public` 为真则 `"public"`，否则 `"private"`（取值只有这两个）。历史上的 `assigned` 来源随 `AppAssignment` 表一并下线，不再存在。

后续可以扩展：

- 专用内置 Agent。
- 工作流 Agent。
- 工具型 Agent。
- 外部 A2A Agent。

每个 Agent 必须归属至少一个子池，允许多个子池标签，但需要一个主子池用于运营统计。

质量评分和推荐权重第一阶段也先由管理员手动维护。后续当路由日志、用户反馈、成功率、失败率、耗时和成本数据积累足够后，再逐步引入自动评分或半自动建议。

### 9.4 Agent 路由/选择策略

> **现状说明**：本文档早期版本设想的独立 `AgentRouter` 模块已被替代。真实链路中，Agent 的最终选定由编排决策层完成：Conductor（指挥官，`ENABLE_CONDUCTOR` 开启时）通过单次 LLM `ConductorPlan` 输出每个子任务的 `agent_pool` / `required_capabilities` / `model_tier` 等字段；旧 Orchestrator 链路则基于规则决策；两者产出的子任务约束再交给本文第 8 章的池层组件做候选收集/过滤/排序/裁剪。因此"路由策略"实际由两层协作完成，需要综合的信号包括：

- 用户问题语义。
- 编排层给出的任务类型（intent）。
- 复杂度（ConductorPlan.complexity / 旧链路 TaskClassifier 输出）。
- Agent 能力标签。
- Agent 模型档位。
- Agent 成本等级。
- 用户权限。
- 历史成功率。
- 近期健康状态。

确定性排序公式见 8.2.5 `AgentRanker`，硬过滤见 8.2.4 `AgentPolicyFilter`。需要说明：真实实现中 `AgentRanker`/`AgentPolicyFilter` 与早期设计同构但并入 `agent_pool_service.py` 统一管理（见 8.2），并非独立分散的服务文件。



## 10. 工具池设计

### 10.1 工具池范围与统一抽象

工具池不是一个单独的大池，而是由多个工具子池组成。核心设计原则是：**所有可被 Agent 调用的资源都应纳入工具池治理，不论其内部实现是原子工具还是组合工具。**

#### 10.1.1 工具来源类型（完整版）

基于 钰见我 底座已有的能力，工具来源类型扩展为以下 7 类：

| 来源类型 | 底座实现 | 治理方式 | 说明 |
| --- | --- | --- | --- |
| builtin | builtin_provider_manager + providers.yaml | 纳入 ToolSourceType | 平台内置基础能力（搜索、翻译、天气等） |
| api_tool | ApiTool + ApiToolProvider + OpenAPI 解析 | 纳入 ToolSourceType | 企业业务 API、第三方服务 API |
| mcp | McpProvider + McpToolFactory | 纳入 ToolSourceType | 外部能力接入和标准化工具调用 |
| knowledge | KnowledgeBase + KnowledgeDocument + KnowledgeSegment 检索 | 纳入 ToolSourceType | 知识库检索工具 |
| workflow | WorkflowToolAdapter(BaseTool) 从已发布 Workflow 构建 | 纳入 ToolSourceType | 多步骤业务自动化，本质是组合工具 |
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
- workflow：由 15 种节点（LLM/代码/工具/知识库/HTTP/条件分支/循环/子流程/意图分类等）编排而成
- agent_binding：把另一个 App 包装成工具，递归加载目标 App 的全部工具

**底座真实嵌套能力（已审计）**：

| 组合工具 | 内部可引用的工具类型 | 数据来源 | 是否需扩展 |
| --- | --- | --- | --- |
| workflow | builtin_tool / api_tool（ToolNode）+ knowledge（DatasetRetrievalNode 独立节点） | `Workflow.graph["nodes"]` | 已支持 |
| workflow | mcp / skill / workflow / agent_binding | `ToolNodeData.tool_type` 已扩展为 7 种（含上述四类） | **已支持** |
| agent_binding（私有 App） | builtin / api_tool / mcp / skill / knowledge / workflow / 嵌套 agent_binding | 递归调用 `_build_runtime_tools` | 已支持 |
| agent_binding（公开 App） | 不在本地解析，走 A2A 远端协议 | `PublicAgentA2AService.send_message` | 已支持（黑盒） |

组合工具的真实嵌套关系（反映底座现状）：
```text
原子工具：builtin / api_tool / mcp / knowledge
    │
    ├─→ 工具包：skill（manifest 内多个叶子工具，SCF 远端执行，不递归）
    │
    ├─→ 组合工具：workflow
    │       └─ 内部节点可引用：builtin_tool / api_tool / knowledge / mcp / skill / workflow / agent_binding【已支持】
    │
    └─→ 组合工具：agent_binding（委派工具）
            └─ 私有 App：递归加载目标 App 全部工具（含 workflow/skill/嵌套 agent_binding）【已支持】
            └─ 公开 App：A2A 黑盒委派，不在本地解析【已支持】
            └─ 循环引用检测：绑定期 `_has_agent_binding_path` + 运行期 `call_stack` 去重【已支持】
```

**关键约束**：
1. workflow 已可嵌套 mcp/skill/workflow/agent_binding——`ToolNodeData.tool_type` 枚举已扩展为 7 种，由 `CompositeToolResolver._build_workflow_tool_ref` 统一解析
2. agent_binding 是唯一支持完整递归嵌套的组合工具（私有 App 路径）
3. skill 不是组合工具，是工具包，治理按工具包处理（整体或按内部 tool_name）
4. agent_binding 公开 App 走 A2A，内部工具不可见，治理只能在 app_id 层级

#### 10.1.3 统一工具描述符

底座已有 `RuntimeToolDescriptor`（`internal/entity/runtime_tool_entity.py` L17-32），共 **15 个字段**，其中组合工具建模字段（`is_composite` / `composite_kind` / `composite_components` / `composite_root_id` / `runtime_name_stable`）**已落地**；配套 `CompositeComponentRef`（L8-13）：

```python
@dataclass
class RuntimeToolDescriptor(SerializableMixin):
    # ─── 底座基础字段（10 个）───
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

    # ─── 组合工具建模字段（已落地）───
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

底座已实现统一的"组合工具 id → 递归列出原子工具"解析器 `CompositeToolResolver`（`internal/service/composite_tool_resolver.py`，已在 DI 容器注册，由 `RuntimeToolGovernanceGate` 消费）。Workflow 遍历 `graph["nodes"]`，Skill 读 `manifest["tools"]`，agent_binding 递归加载目标 AppConfig——三类来源统一收敛在该解析器内。组合工具治理透传（10.2.3）依赖此解析器。

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
                # DatasetRetrievalNode：引用知识库（实际字段为 dataset_ids 复数 list）
                for dataset_id in node.get("dataset_ids", []) or []:
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
| risk_level | 风险等级（safe/low/medium/high/sensitive/dangerous） | 默认 medium，管理员可覆盖 |
| permission_scope | 权限范围（system/user/tenant/public） | 按 source_type 默认值 |
| cost_level | 成本等级（low/medium/high） | 默认 medium |
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
  → 有效风险等级 = max(成员工具风险等级)  # safe < low < medium < high < sensitive < dangerous
  → 缓存结果（key: tool_id + Workflow.updated_at + AppConfig.updated_at）
```

**部分阻断策略**（成员工具被阻断时的处理）：

| 场景 | 策略 | 说明 |
| --- | --- | --- |
| 成员中存在 dangerous 工具 | 组合工具整体阻断 | dangerous 工具不可自动触发，组合工具也不应自动触发 |
| 成员中存在 sensitive 工具 | 组合工具需用户确认 | 触发统一确认卡片，展示内部 sensitive 工具清单 |
| 成员中存在 disabled 工具 | 组合工具整体阻断 | 任一成员工具 disabled 则组合工具不可用 |
| 成员中存在 unhealthy 工具 | 组合工具整体阻断 | 当前实现取保守策略：`block_reason="member_unhealthy"` 直接整体阻断 |
| 成员全部 safe/low/medium/high | 组合工具正常放行 | 有效风险等级 = max(成员风险等级)，如全为 safe/medium 则为 medium |

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
| low | 影响面很小的操作 | 可自动执行 |
| medium | 有业务影响但可控，例如写入沙箱文件、修改临时文档 | 可自动执行 |
| high | 有明确业务影响，需要用前确认 | 需权限过滤；requires_confirmation=True 且未获确认时不挂载 |
| sensitive | 涉及敏感数据、外部通信、正式业务写入 | 默认不自动执行，需审批或管理员授权 |
| dangerous | 删除、支付、权限变更、系统数据库增删改查 | 禁止自动挂载（ToolPolicyFilter 直接拒绝） |

高风险工具不应被理解为“普通用户经常需要查询平台核心数据”。普通用户没有合理动机查询 钰见我 自身的系统数据库、租户权限、计费账户、模型 Key 或生产运维数据，这类平台系统工具原则上不进入普通用户可触发工具池。

高风险工具需要按数据和系统归属拆分：

| 归属 | 例子 | 普通用户是否可触发 | 策略 |
| --- | --- | --- | --- |
| 平台自身系统 | 钰见我 系统数据库、模型 Key、计费账户、租户权限、平台审计日志 | 不可触发 | 仅管理员或内部自动化流程可用 |
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

1. 是否操作 钰见我 平台自身系统。
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
| 标题区 | 风险等级 | high / sensitive / dangerous |
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

**打通方案**：Agent 路由元数据统一由 `App.agent_metadata`（JSONB）承载，`AgentCandidateCollector` 在收集候选时读取。

```text
AgentCandidateCollector.collect(account_id)
  → 查询 App 表（public + own）              [底座已有]
  → outerjoin AgentPoolConfig ON app_id      [底座已有]
  → 读取 App.agent_metadata 中的
    primary_pool / secondary_pools / risk_level / model_tier / routing_priority
  → 合并到 Agent 元数据中
  → AgentPolicyFilter 按这些字段做过滤       [底座已有]
```

AgentPoolConfig 不存在时降级为 `_DEFAULT_POOL_CONFIG = {}`（空配置，仅保留 `enabled` / `health_status` 默认值）。

> **历史注记**：早期版本称需"新增 LEFT JOIN 打通"并降级为 `primary_pool=general, risk_level=safe, model_tier=standard`——这些字段已由迁移 `i4d5e6f7a8b9` 从 `agent_pool_config` 表移除并迁至 `App.agent_metadata`，JOIN 与降级逻辑均已是底座现状。

#### 10.5.2 工具治理打通

**问题**：AppConfig 绑定的工具走 LangChain BaseTool 通道，不经过 ToolCandidateCollector 和 ToolPolicyFilter。底座的工具构建入口是 `AppRuntimeService.build_runtime_tools_for_config`（`app_runtime_service.py`），**不是** `AppConfigService`。
>
> **历史注记**：早期版本记为 `AppService._build_runtime_tools_for_config`（静态方法）——该方法在当前 `app_service.py` 中已不存在，实现已迁至 `AppRuntimeService`。

**打通方案**：在 `AppRuntimeService.build_runtime_tools_for_config` 的工具构建流程中注入治理过滤层（已落地，含 `governance_gate` 参数）。

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
      │     - 阶段2：sensitive/dangerous 阻断，safe/low/medium/high 放行
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
  → safe/low/medium/high 工具继续放行

阶段 3：全量启用
  → 所有工具按治理策略过滤
  → 管理员可按 source_type / tool_pool 灰度启用
```

渐进式启用通过 OrchestrationFeatureFlag 控制（底座已有此机制）。

### 10.6 凭证与 Key 池的分区判据

判据**不是**「模型 vs 工具」，而是**「该凭证是否需要在多个候选之间路由」**：

| 维度 | 可路由池（`model_key_config`） | 具名凭证（env + 统一入口） |
| --- | --- | --- |
| 归属 | 多个 Key 为一个 provider/模型提供服务 | 一把部署一把 Key，一一对应 |
| 是否需要轮换 | 是（按 `used_credits`/`created_at` 排序轮换） | 否 |
| 是否需要配额 | 是（`tenant_quota`，用尽转 `disabled`） | 否 |
| 是否需要熔断 | 是（`failure_count` → `circuit_open`，冷却恢复） | 否 |
| 存储 | DB（`model_key_config.key_value_encrypted`，Fernet 加密） | env（**不入库**） |
| 读取入口 | `RuntimeModelPoolService.get_keys_for_model()` → `FallbackLLMWrapper` | `internal/service/tool_credential_resolver.get_tool_credential()` |

- `model_key_config.model_id IS NULL` 表示 **provider 级共享 Key**（该 provider 下所有模型可用）；
  非空表示绑定到具体模型。此语义由 `get_keys_for_model` 的过滤条件实现，勿改成「模型专属才可用」。
- 工具凭证（gaode/newsapi/github/stability/github/xai/baidu/tavily 等 builtin provider）
  一律走 env + `get_tool_credential()`；**不给工具凭证加熔断/配额**——无轮换需求，加了是过度设计。
- 新增「可路由」需求时，扩展 `model_key_config` 与 `RuntimeModelPoolService`，
  **不要**新建第二套 Key 表或第二个解析器（AGENTS.md「禁止新建平行机制」）。

---

## 11. 内置工具：知识库板块创建（create_knowledge_base）

`create_knowledge_base` 是 builtin 来源的原子工具，供首页助手（小钰）在对话内为用户创建知识库板块。产品侧需求见 [knowledge-base-product-form-design.md](../knowledge-base-product-form-design.md) §7.4。

### 11.1 落点与注册

| 项 | 值 |
| --- | --- |
| provider | `knowledge_base_tools` |
| 目录 | `api/internal/core/tools/builtin_tools/providers/knowledge_base_tools/` |
| 文件 | `__init__.py`（导出同名工厂函数）、`create_knowledge_base.py`、`create_knowledge_base.yaml`、`positions.yaml` |
| providers.yaml 登记 | `category: tool`（`categories.yaml` 中不存在 `knowledge` 分类，故复用既有 `tool`） |
| tool_id | `builtin:knowledge_base_tools:create_knowledge_base` |
| DB 同步 | 启动时由 `BuiltinToolSyncService.sync_yaml_to_db()` 以 `source=catalog` 写入镜像表 |

### 11.2 参数与校验

工具 `args_schema` 为 Pydantic 模型（`CreateKnowledgeBaseInput`），四个参数：

| 参数 | 必填 | 取值 | 说明 |
| --- | --- | --- | --- |
| `name` | ✅ | 非空字符串 | 板块名称 |
| `base_type` | | `document`/`image`/`video`/`audio`/`mixed` | 默认 `mixed`，取值源自 `KnowledgeBaseType` |
| `partition_mode` | | `none`/`date_month`/`date_day`/`custom` | 默认 `none`，取值源自 `PartitionMode` |
| `description` | | 字符串 | 默认空 |

工具内**先做枚举校验再落库**：非法 `base_type` / `partition_mode`、空 `name`、缺失 account，均返回 `{"ok": false, "error": "..."}` 的可读文本，不抛 500、不进入服务层。YAML 中两个枚举参数声明为 `select`，附 `options`，与既有 provider 的元数据表达一致。

### 11.3 下游调用

校验通过后调用 `KnowledgeBaseService.create_user_content_base(name=..., account=..., operation_context="user", description=..., base_type=..., partition_mode=...)`，仅创建当前用户私有的用户资料库（`knowledge_scope=user_content`、`visibility_scope=private`）。服务层仍有二次枚举与重名校验，非法值抛 `ValidateErrorException`，工具捕获后转成可读错误返回。

### 11.4 账号注入方式（builtin 工具的通用范式）

builtin 工具没有全局 `g.account`，账号通过**运行时挂载点的工厂参数**透传，这与 `computer_control` / `host_os` 的 `requester` 是同一注入点：

```text
AssistantAgentService._build_assistant_runtime_tools(account_id)
  → builtin_provider_manager.get_tool("knowledge_base_tools", "create_knowledge_base")
  → tool_factory(account_id=str(account_id))     # 绑定到工具实例字段
  → 工具 _run 内调用 AccountService.get_account(uuid) 加载真实 Account
  → KnowledgeBaseService.create_user_content_base(account=..., operation_context="user")
```

工具内部不做上下文穿透，而是用工厂参数绑定 `account_id`，再用 `AccountService` 换取 `Account` 实例（服务层内部依赖 `account.id`）；account 无法解析或不存在时返回明确错误。该方式与既有 OS/computer 工具一致，且可在单测中直接构造工具实例验证，无需 app 上下文。

### 11.5 测试

`api/test/internal/core/tools/test_create_knowledge_base_tool.py` 覆盖：合法参数透传（name/base_type/partition_mode/description/operation_context/account）、默认值、非法 `base_type`、非法 `partition_mode`、空名称、缺失 account、账号不存在、服务异常降级为可读错误、工厂绑定。

---

## 12. 知识库检索工具 `search_knowledge_base` 的过滤入参（P3 已落地）

运行时名为 `search_knowledge_base`（常量 `KNOWLEDGE_RETRIEVAL_TOOL_NAME`）的检索工具由 `RetrievalService.create_knowledge_retrieval_tool(...)` 构造，其 `args_schema`（`KnowledgeRetrievalInput`）在 P3 新增 4 个**可选**过滤字段：

| 入参 | 类型 | 说明 |
| --- | --- | --- |
| `query` | `str` | 检索语句（原有，必填） |
| `partition_id` | `str \| None` | 限定在某分区内检索，传分区 ID；非法 UUID 记 warning 并忽略该过滤 |
| `media_types` | `list[str] \| None` | 限定素材类型，取值 `image` / `video` / `audio` / `document` |
| `tags` | `list[str] \| None` | 按素材标签名过滤，多个标签取**并集** |
| `score_threshold` | `float \| None` | 相似度下限（0~1），低于该值的结果不返回 |

入参组装由 `RetrievalService._build_retrieval_filter(...)` 完成，产出 `RetrievalFilter` 传给 `layered_search`：四个入参全为空时返回 `None`（不过滤）；有标签名但解析不到任何标签时返回**空 `tag_ids`** 的 filter，由检索层 **fail closed**（返回空结果），**不得退化成"不过滤"**。过滤语义与 SQL 下推位置详见 [02-knowledge-base.md §11.9](./02-knowledge-base.md#119-检索过滤参数p3-已落地)。

> 注意：工具入参名为 `media_types`（复数列表），与产品设计稿中早期写的单数 `media_type` 不同，以代码为准。

