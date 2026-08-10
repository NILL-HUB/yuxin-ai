# Agent 池与工具池设计

> 本文档为主架构文档的子模块，包含动态子集归集、Agent 池设计和工具池设计的完整内容。
>
> **主文档**: [architecture-design.md](../architecture-design.md)
> **相关模块**: [02-knowledge-base.md](./02-knowledge-base.md) | [03-orchestration-infra.md](./03-orchestration-infra.md)

---

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

基于 钰心AI 底座已有的能力，工具来源类型扩展为以下 7 类：

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

高风险工具不应被理解为“普通用户经常需要查询平台核心数据”。普通用户没有合理动机查询 钰心AI 自身的系统数据库、租户权限、计费账户、模型 Key 或生产运维数据，这类平台系统工具原则上不进入普通用户可触发工具池。

高风险工具需要按数据和系统归属拆分：

| 归属 | 例子 | 普通用户是否可触发 | 策略 |
| --- | --- | --- | --- |
| 平台自身系统 | 钰心AI 系统数据库、模型 Key、计费账户、租户权限、平台审计日志 | 不可触发 | 仅管理员或内部自动化流程可用 |
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

1. 是否操作 钰心AI 平台自身系统。
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

