# 模型路由、编排执行、结果汇总与可观测性

> 本文档为主架构文档的子模块，包含模型路由/模型池与提供商体系/成本控制、编排执行（Conductor + ExecutionCoordinatorService）、ResultSynthesizer 设计和可观测性与审计的完整内容。
>
> **主文档**: [architecture-design.md](../architecture-design.md)
> **相关模块**: [01-agent-tool-pool.md](./01-agent-tool-pool.md) | [02-knowledge-base.md](./02-knowledge-base.md)
>
> **定位与现状**：本模块的编排主导权已由旧 Orchestrator 串行决策移交至 **Conductor（指挥官）+ ExecutionCoordinatorService（执行编排）** 主导的现状。OrchestratorService 仍保留为旧链路（规则决策），并在 `ENABLE_CONDUCTOR` 开启时委托 Conductor、失败回退旧链路（见 [architecture-design.md](../architecture-design.md) 与 [execution-roadmap.md](../execution-roadmap.md) 2026-08-26 记录）。早期叙事中的 DAGEngine（`dag_entity` / `dag_engine_service` / `agent_instance_pool` / `test_dag_engine`）已删除，统一为 `TaskPlan + ExecutionCoordinatorService`。模型 Key 管理已并入**模型池/提供商体系**（`RuntimeModelPoolService` 管理模型池与 Key 池），独立 `ModelPoolService`/`KeyPoolService` 空壳已物理删除。

---

## 12. 模型路由、模型池、提供商体系与成本控制

### 12.1 模型档位

| 档位 | 适用任务 | 示例策略 |
| --- | --- | --- |
| cheap | 简单问答、改写、摘要、分类 | 默认优先使用 |
| standard | 中等复杂任务、普通工具调用 | 常规执行模型 |
| strong | 复杂推理、规划、多 Agent 汇总、代码/研究 | 按需升级 |
| vision | 图片理解 | 有图片输入或视觉任务时使用 |
| long_context | 长文档任务 | 长上下文场景使用 |

### 12.1.1 模型池与提供商体系

后台需要统一模型池与提供商体系，否则多个 Agent 难以稳定流转。

> **现状说明**：模型 Key 管理已并入模型池/提供商体系。独立空壳 `ModelPoolService` / `KeyPoolService` 已删除；真实实体为 `ModelPoolConfig` / `ModelKeyConfig` / `ModelTierPolicy`（`internal/model/model_pool_entity.py`）+ `ModelProviderConfig`（`model_provider_entity.py`），运行服务为 `RuntimeModelPoolService`（`internal/service/runtime_model_pool_service.py`），提供按档位/类型选择模型、按模型轮询 Key、Key 失败熔断计数等能力。Admin 侧由 `admin_model_pool_service.py` / `admin_model_provider_service.py` 管理。

模型池管理：

- 供应商（provider）。
- 模型名称。
- 模型档位（tier）。
- 模型类型（model_type，含上下文无关/长上下文等分类）。
- 支持模态。
- 上下文长度。
- 输入 / 输出价格。
- 速率限制。
- 健康状态。
- 优先级与默认 fallback。

Key 池管理（并入模型池体系，`ModelKeyConfig`）：

- 供应商 Key。
- Key 归属模型或供应商（`model_id` 为空时归属 provider）。
- 可用额度。
- 并发限制。
- 失败次数。
- 熔断状态。
- 轮询和权重（按优先级/权重轮询选取，`select_key`）。
- 到期时间。

运行时模型选择链路：`ModelGatewayService`（`internal/service/model_gateway_service.py`）依据编排决策（`RoutingDecision`）与上下文解析模型档位；`RuntimeModelPoolService.select_model_with_fallback` 在模型池内按 tier + 成本参考 + 优先级选取并支持 fallback；`RuntimeModelPoolService.select_key` 为选定模型选取可用 Key 并维护失败计数。管理员可为每个 Agent 配置底座模型，也可以选择"跟随系统策略"。系统策略负责在 Key 不可用、限流、余额不足或模型故障时自动切换。

### 12.2 复杂度判断

> **v5.2 变更**：原 `TaskClassifier` 模块已被指挥官 `ConductorService` 替代。复杂度判断不再是独立模块的输出，而是指挥官单次 LLM `structured_output` 输出的 `ConductorPlan.complexity` 字段。下表的判断规则现在作为指挥官 prompt 的参考规则，由 LLM 在推理时应用。

`simple / medium / complex` 初始规则不是给用户看的产品概念，而是给指挥官使用的调度规则。它决定：

- 用哪个模型档位。
- 是否进入 Agent 子池。
- 是否需要工具子集。
- 是否允许多 Agent。
- 是否开启深度思考。
- 单次最多挂载多少工具。
- 最终如何计费和记录成本。

推荐初始规则（已融入指挥官 prompt）：

| 复杂度 | 判断信号 | 默认执行 |
| --- | --- | --- |
| simple | 单轮问答、常识解释、轻量改写、无需外部工具、无需多步骤推理 | cheap 模型 direct_answer |
| medium | 明确垂直任务、需要一个 Agent、需要少量工具、需要读取资料或生成结构化内容 | standard 模型 single_agent 或 single_agent_with_tools |
| complex | 多目标、多领域、多文件、长上下文、需要规划、需要多个 Agent、需要质量校验 | strong 模型 deep_thinking 或 multi_agent |

补充判断规则（已融入指挥官 prompt）：

| 信号 | 复杂度影响 |
| --- | --- |
| 用户上传图片 | 至少需要 vision 能力，不必然 complex |
| 用户上传长文档 | 可能升级到 long_context 或 medium/complex |
| 任务涉及两个以上领域 | 倾向 multi_agent，复杂度至少 medium |
| 需要写代码并解释方案 | 倾向 complex |
| 需要外部工具查询 | 至少 medium |
| 需要修改生产数据或外部发送 | 风险升级，不等同于复杂度升级 |
| 用户显式要求深度思考 | 可开启 deep_thinking，并按实际 token 计费 |

指挥官输出（取代原 TaskClassifier 输出）：

```json
{
  "execution_mode": "single_agent",
  "intent": "analysis",
  "complexity": "medium",
  "reason": "用户需要数据分析，单个 Agent 即可完成",
  "agents": [
    {
      "task_id": "t1",
      "title": "数据分析",
      "description": "...",
      "agent_pool": "data",
      "required_capabilities": ["data_analysis"],
      "model_tier": "2",
      "depends_on": [],
      "risk_level": "safe"
    }
  ]
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



## 13. 编排执行：Conductor + ExecutionCoordinatorService

> **现状说明（取代原 v5.2 注记）**：原 Orchestrator 多模块串行（TaskClassifier → TaskPlanner → PoolIntentResolver → ExecutionModeSelector）已被 ConductorService 替代。现状链路为：
> - 编排决策：`ENABLE_CONDUCTOR` 开启时，`assistant_agent_service.py` / `orchestrator_service.py` 委托 **ConductorService.plan()** 单次 LLM `structured_output` 输出 `ConductorPlan`；OrchestratorService 在 Conductor 决策异常时回退旧规则链路（`orchestrator_service.py` 日志"Conductor 决策失败，回退旧 Orchestrator"）。
> - 执行编排：`ConductorPlan` 经 `to_task_plan()` 转为 `TaskPlan`，由 **ExecutionCoordinatorService** 按并行/波次/串行分派执行；执行失败经 `repair_plan()` 修复（`_build_plan_repairer`，见 `assistant_agent_service.py`）。
> - 执行器真实现位于 `internal/service/executors/`：`single_agent_executor.py` / `multi_agent_executor.py` / `direct_answer_executor.py`，其中 `agent_task_executor.py` 的 `AgentTaskExecutor` 负责具体子任务执行，并在 `_resolve_query` 中把上游子任务结果（`upstream_results`）拼进 query。
> - DAGEngine 时代遗留（`dag_entity` / `dag_engine_service` / `agent_instance_pool` / `test_dag_engine`）已于 2026-08-26 删除，统一为 `TaskPlan + ExecutionCoordinatorService`。

### 13.1 执行模式

编排决策层输出 `execution_mode`（Conductor 侧为 `ConductorPlan.execution_mode`；旧链路为 `RoutingDecision.execution_mode`）：

| 模式 | 说明 | 适用场景 | 计费方式 |
| --- | --- | --- | --- |
| direct_answer | 直接回答 | 简单问答 | 系统承担，不扣用户额度 |
| single_agent | 单 Agent 执行 | 明确垂直任务 | 用户承担 |
| single_agent_with_tools | 单 Agent + 工具 | 需要查询/操作 | 用户承担 |
| multi_agent_parallel | 多 Agent 并行 | 多角度分析 | 用户承担 |
| multi_agent_sequential | 多 Agent 串行 | 前后依赖任务 | 用户承担 |
| deep_thinking | 深度思考执行 | 复杂产物、长任务 | 用户承担 |
| reject_or_confirm | 拒绝或请求确认 | 高风险任务 | 不计费 |

### 13.2 快速路径（direct_answer）

指挥官判定为简单问题时，直接在 `ConductorPlan.direct_answer` 字段中给出完整回复，不经 Agent 执行：

```text
用户请求 -> 指挥官 LLM（direct_answer）-> BillingUsageAggregator -> SSE 直接返回
```

不进入 Agent 池和工具池。指挥官 LLM 成本由系统承担，不扣用户额度，避免双重计费。

### 13.3 复杂路径

指挥官判定需要 Agent 时，输出 `agents[]` 子任务列表，`to_task_plan()` 转为 `TaskPlan` 后进入：

```text
ConductorService.plan
  -> ConductorPlanValidator.validate（失败回退 single_agent）
  -> ExecutionCoordinatorService.execute(plan)
      -> 按 TaskPlan 执行模式分派
          -> AgentCandidateCollector（Agent 池候选收集，见 01 模块 8.2）
          -> ToolCandidateCollector / RuntimeToolMountService（工具候选与挂载，见 01 模块 8.4/10.5）
          -> AgentTaskExecutor（子任务执行，上游结果拼接进 query）
          -> 失败子任务 -> ConductorService.repair_plan 修复（可选，经 plan_repairer 注入）
  -> ResultSynthesizer 汇总
```

**执行失败与修复**：`ExecutionCoordinatorService.execute()` 支持：
- `resume=True` 时读取子任务快照（`subtask_registry.snapshot(request_id)`，由 `SubtaskRegistryService` 注册计划），跳过已完成子任务、标记 `resumed:completed` / `resumed:failed`。
- 注入的 `plan_repairer`（`Callable[[str, list[dict]], TaskPlan | None]`）在存在失败子任务时基于失败信息调用 `ConductorService.repair_plan`（把失败反馈拼入 query 重新 `plan()`），再以 `_run_plan` 重跑修复后的计划；修复器返回空则保留原结果。
- 升级/降级策略由 `cost_policy_service.EscalationPolicyService` 承担（读取 `billing_config` 的 `escalation_enabled`，经 `resolve_escalation_policy_service()` 注入）。

**子任务上下文**：`ExecutionCoordinatorService._build_upstream_context` 为每个子任务构建上游结果上下文；`AgentTaskExecutor._resolve_query` 在存在 `upstream_results` 时，将上游子任务输出拼接到 `item.description`（或原始 query）之后，实现串行链路的信息传递。

### 13.4 硬约束校验与回退

指挥官输出后经 `ConductorPlanValidator.validate()` 校验，失败时回退 `single_agent` 模式：

| 约束 | 校验内容 |
| --- | --- |
| execution_mode 合法 | 必须是枚举值之一 |
| direct_answer 一致性 | direct_answer 模式下 agents 必须为空 |
| agent 数量限制 | ≤ MAX_AGENTS_PER_PLAN |
| model_tier 合法 | 必须是 1/2/3 之一 |
| 并行依赖约束 | multi_agent_parallel 模式下 depends_on 必须为空 |

### 13.5 Feature Flag 与编排切换

编排链路受 `orchestration_feature_flag_service` 控制（开关定义见 [architecture-design.md §22](../architecture-design.md#22-feature-flag-与回滚策略)）。与本节直接相关的开关：

| 开关 | 作用 |
| --- | --- |
| ENABLE_ORCHESTRATOR | 是否启用编排路由（默认开，关闭时直接回退 `direct_answer`） |
| ENABLE_CONDUCTOR | 是否启用 Conductor（LLM 指挥官）替代规则编排（默认关，fallback=orchestrator 旧链路） |
| ENABLE_MULTI_AGENT_EXECUTION | 是否允许多 Agent 规划（执行层按 TaskPlan 跑并行/串行子 Agent） |
| ENABLE_AUTO_DEEP_THINKING | 是否由 LLM 意图检测自动触发 deep thinking |
| ENABLE_RESULT_SYNTHESIZER | 任务计划明细开关（结果合成执行未接线，见实体描述） |

> 注：Feature Flag 的真实实体见 [orchestration_feature_flag_entity.py](../../../api/internal/entity/orchestration_feature_flag_entity.py)，共 14 个编排开关 + `list_flags` 附加的 3 个 `AUTH_*` 认证开关（`auth_switch_service.AUTH_CODES`），详见 [architecture-design.md §22](../architecture-design.md#22-feature-flag-与回滚策略)。

### 13.6 Orchestrator 旧链路的保留形态

`OrchestratorService` 仍保留为旧规则链路（`ENABLE_CONDUCTOR` 关闭时的默认路径），其 `decide()` 内部：先做 `task_classifier_service.classify()`（规则分类）→ 意图识别/成本策略/执行模式选择等规则决策；`ENABLE_CONDUCTOR` 开启时在分类前委托 `conductor_service.decide()` 输出 `RoutingDecision`，异常时回退到分类链路。`PoolIntentResolver`（`pool_intent_resolver_service.py`）不再位于主入口调度主链路，仅被 `home_service.py`（`/home` 意图摘要路径，`PoolIntentResolver().resolve(...)`）等轻量场景引用。



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

### 14.4 与记忆系统的集成

ResultSynthesizer 在合成最终回答时，需要融合两类记忆上下文：

1. **Memory Digest 注入（System 1 路径）**：当 Orchestrator 判定为简单查询时，ResultSynthesizer 直接从 [第 16 章](#16-脑启发记忆系统v50-新增) 定义的 Memory Digest 获取用户画像、活跃技能和近期事件摘要，作为上下文注入 LLM prompt，无需触发完整检索。

2. **记忆检索结果融合（System 2 路径）**：当 Orchestrator 判定为复杂查询时，System 2 的 MemoryRetriever 返回记忆片段（带 tier/scope 标签），与 layered_search 返回的知识库片段（带 knowledge_scope 标签）在 ResultSynthesizer 中统一处理：
   - 知识库片段按 knowledge_scope 分类（system → 系统规则区，user_content → 用户资料区）
   - 记忆片段按 tier 和 memory_type 分类（preference → 用户偏好区，secret/event/project → 用户事实区）
   - SystemRulePriorityResolver 确保系统规则优先级高于用户偏好

3. **巩固引擎反馈**：ResultSynthesizer 合成的最终回答可作为巩固引擎的输入信号——回答中引用了哪些记忆片段，这些片段的访问次数+1，影响 HebbianDecay 的权重计算（复述强化因子）。



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

