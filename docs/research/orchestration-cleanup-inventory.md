# Agent 编排层清理审计清单

> 审计日期：2026-08-26
> 范围：钰心 Agent 编排层（Conductor / Orchestrator / ExecutionCoordinator / Executors / AgentQueueManager / 工作流引擎）
> 方法：设计文档、执行路线图、运行时代码引用、残留文件四层对账
> 基线：编排相关后端测试当前共 69 项通过；`npm run build` 通过
>
> 状态总表：[orchestration-cleanup-status.csv](./orchestration-cleanup-status.csv)

## 1. 结论速览

架构设计本身完整且方向正确，主要问题集中在实现层与文档状态脱节：

| 类别 | 数量 | 严重度 |
| --- | --- | --- |
| 设计已定义但未接入运行时 | 2 | P0 |
| 半成品实现或只存在于编译缓存 | 2 | P0/P1 |
| 新旧路径并存 | 2 | P1 |
| 执行层可靠性缺口 | 3 | P1/P2 |
| 兼容/胶水/遗留标记 | 321 处源码命中 | P2 |

## 2. 问题清单

### 2.1 P0：ResultSynthesizer 未接入主链路

| 项目 | 内容 |
| --- | --- |
| 设计声明 | `docs/prd/execution-roadmap.md` 标注“多 Agent 路径已接入 ResultSynthesizerService，已修复” |
| 代码实际 | `multi_agent_executor.py` 未导入/调用 `ResultSynthesizerService`，使用自带的 `_aggregate` + `_llm_summarize` |
| 证据 | `assistant_agent_service.py` 只注入字段，无调用点；`result_synthesizer_service.py` 仅被 DI 注册和单元测试引用 |
| 风险 | 两套汇总逻辑并存，设计中的冲突检测、质量校验、审计事件不会在主链路产生 |

### 2.2 P0：多 Agent DAG 重写是半成品

| 项目 | 内容 |
| --- | --- |
| 设计声明 | `docs/prd/execution-roadmap.md` 标注“多 Agent DAG 重写第一阶段完成，37 passed” |
| 代码实际 | `DAGEngine` / `DAGGraph` / `AgentInstancePool` 存在并有测试，但没有任何运行时代码引用；运行时仍走 `TaskPlan + ExecutionCoordinatorService` |
| 处置 | 2026-08-26 已删除 `dag_entity.py` / `dag_engine_service.py` / `agent_instance_pool.py` / `test_dag_engine.py`，多 Agent 执行模型确定为 `TaskPlan + ExecutionCoordinatorService` |
| 残留 | `api/internal/service/executors/__pycache__/task_decomposer.*.pyc` 存在，但源文件缺失 |

### 2.3 P1：Conductor 与旧 Orchestrator 双路径并存

| 入口 | 路径 |
| --- | --- |
| 首页助手 | 优先 Conductor，失败回退旧 Orchestrator |
| 应用调试 / OpenAPI / Web App / 微信 | 走旧 Orchestrator；旧 Orchestrator 在 `ENABLE_CONDUCTOR` 开启时委托 Conductor |

设计文档明确 Conductor 替代旧 Orchestrator 串行链路；目前旧 Orchestrator 已可作为 Conductor 的兼容门面。

### 2.4 P1：三套图执行模型并存

| 引擎 | 位置 | 状态 |
| --- | --- | --- |
| LangGraph StateGraph | `BaseAgent` / `FunctionCallAgent` / `DeepThinkingAgent` | Agent 运行时在用 |
| GraphEngine | `api/internal/core/workflow/graph_engine.py` | 工作流运行时在用 |
| DAGEngine | `api/internal/service/dag_engine_service.py` | 未被运行时引用 |

`orchestration-system-roadmap.md` 规划统一到 GraphEngine，但 Agent 层和 DAGEngine 均未收敛。

### 2.5 P1：TaskPlan 缺少数据依赖契约

`depends_on` 原本只控制执行顺序，不传递上游结果。`_SubtaskTaskExecutor` 给每个子任务传入原始 `query` / `history`，上游 Agent 的答案不会成为下游 Agent 的输入。

已修复：`ExecutionCoordinatorService` 现在通过 `upstream_results` 上下文把依赖任务结果传给下游，`AgentTaskExecutor` 会将其拼入下游任务指令。

### 2.6 P1：执行层缺少 timeout / retry / resume

`TaskPlanItem.timeout_seconds` 原未被 `ExecutionCoordinatorService` 消费；`CancelToken` 只能在任务间检查，不能中断正在执行的 LLM/工具；无进程级 checkpoint。

已补：`timeout_seconds` 已作为软超时生效，超时任务标记 `agent_execution_timeout` 后协调器继续；重试也已在 5.5 中实现。

### 2.7 P2：线程 + 内存队列不是生产级执行通道

`SingleAgentExecutor` 使用 `threading.Thread + queue.Queue`，`AgentQueueManager` 的事件队列是进程内字典；进程重启、客户端断线、多 worker 场景下执行状态会丢失。

### 2.8 P2：兼容/胶水/遗留标记

`api/internal` 与 `api/app` 下命中 `legacy / compat / 兼容 / 临时 / 占位 / 半成品` 等标记共 321 处。分类结果：`TODO / FIXME / HACK` 0 处；260 处为存量兼容/兼容协议标记，属于有意保留；其余为临时文件、占位符 URL、沙箱等业务描述，不属于技术债。

命中最多的文件：

| 文件 | 命中数 |
| --- | --- |
| `api/internal/service/account_service.py` | 24 |
| `api/internal/server/http.py` | 9 |
| `api/internal/service/assistant_agent_service.py` | 9 |
| `api/internal/service/notification_service.py` | 8 |
| `api/internal/service/tool_credential_encryptor.py` | 7 |
| `api/internal/service/completion_app_service.py` | 7 |
| `api/internal/core/agent/backends/baidu_cfc_sandbox_backend.py` | 6 |
| `api/internal/service/app_service.py` | 6 |
| `api/internal/core/skills/skill_executor.py` | 5 |
| `api/internal/service/conversation_service.py` | 5 |
| `api/internal/service/api_key_service.py` | 5 |

### 2.9 P2：前端构建通过但运行时协议风险存在

`npm run build` 成功。风险不在编译，而在事件结构：`orchestrator_routing`、`subtask_started`、`agent_message` 的载荷由 Conductor / 旧 Orchestrator / MultiAgentExecutor 各自生成，字段一致性缺少统一校验。

## 3. 清理计划

### 阶段 1：低风险清理（可立即执行）

- 删除 `task_decomposer` 无源码 pyc 残留。
- 清理全仓 `__pycache__` / `.pytest_cache` 等生成物。
- 修复 `ExecutionCoordinatorService` 的失败依赖传播：上游失败时下游应标记 skipped，而不是继续执行。
- 补充对应单元测试。

### 阶段 2：收敛编排路径

- 统一首页助手、应用调试、OpenAPI、Web App、微信的决策入口到 Conductor。
- 将旧 Orchestrator 降级为兼容适配器或直接删除。
- 确定多 Agent 执行模型：选择 `TaskPlan + ExecutionCoordinator` 或 `DAGEngine`，二选一并删除另一套。

### 阶段 3：补齐设计缺口

- 为 `TaskPlanItem` 增加输入/输出契约与上游结果注入。
- 为 `ConductorPlan` 增加执行中 replan / repair 闭环。
- 为 Agent Run 增加持久化状态、checkpoint、resume。

### 阶段 4：接入 ResultSynthesizer

- 将 `ResultSynthesizerService` 接入多 Agent 主链路，保留执行策略（concat / summarize / best_of）作为前置策略，再进入质量合成层。
- 删除 `MultiAgentExecutor` 内联重复逻辑，或将其收敛为策略函数。

## 4. 验收口径

| 项 | 验收 |
| --- | --- |
| 死代码 | 无“有设计声明但运行时不引用”的编排模块 |
| 双路径 | 所有入口使用同一决策层 |
| 数据依赖 | 串行任务能拿到上游输出 |
| 可靠性 | timeout、retry、checkpoint 有可测试实现 |
| 前端 | 构建通过，SSE 事件结构有后端单测覆盖 |
| 测试 | 相关编排测试全绿 |

## 5. 已执行修正

### 5.1 失败依赖传播（已完成）

`ExecutionCoordinatorService` 现在会记录失败任务，并在并行/串行执行中跳过依赖失败的下游任务，而不是继续执行。

- 新增 `dependency_failed` 结果与对应测试。
- 相关测试：`test_execution_coordinator_service.py` 新增 2 项，当前共 20 项通过。

### 5.2 ResultSynthesizer 接入多 Agent 主链路（已完成）

`ResultSynthesizerService` 增加 `aggregation_strategy` 与 `llm` 参数，支持 `concat / summarize / best_of`，并已在 `MultiAgentExecutor._aggregate` 中接入。

- 移除 `MultiAgentExecutor` 内联的 `_llm_summarize` 重复实现，保留 `_concat_fallback` 作为兜底。
- `test_result_synthesizer_service.py` 新增 summarize / best_of 用例，当前共 6 项通过。
- 相关编排测试当前 35 项通过（含新增用例）。

### 5.3 待处理

- `task_decomposer` 的 pyc 残留仍未删除（当前文件系统删除操作被环境策略拦截）。
- 旧 Orchestrator / Conductor 双路径仍待阶段 2 收敛。

### 5.4 数据依赖传递（已完成）

`TaskExecutor` 协议增加可选 `context` 参数；并行与串行执行都会把依赖任务结果通过 `upstream_results` 传给下游，`AgentTaskExecutor` 将上游答案注入下游子任务指令。

- 相关测试：`test_execution_coordinator_service.py` 新增 2 项，`test_agent_task_executor.py` 新增 1 项。

### 5.5 子任务重试（已完成）

`TaskPlanItem` / `ConductorAgentTask` 增加 `retry_count` 与 `retry_interval`，`ExecutionCoordinatorService` 在失败时按配置重试，避免单次瞬时失败直接打断整条链路。

- 失败仍失败时追加 `retried:N` 警告。
- 相关测试：`test_execution_coordinator_service.py` 新增 2 项。

### 5.6 DAGEngine 半成品清理（已完成）

多 Agent 执行模型确定为 `TaskPlan + ExecutionCoordinatorService`，已删除无运行时引用的 `DAGEngine` / `DAGGraph` / `AgentInstancePool` 及其测试，并同步更新路线图与调研文档。

### 5.7 超时执行（已完成）

`ExecutionCoordinatorService` 增加软超时：`timeout_seconds > 0` 时通过独立线程执行，超时返回 `agent_execution_timeout` 失败结果，协调器继续处理后续任务。

- 相关测试：`test_execution_coordinator_service.py` 新增 2 项。

### 5.8 Conductor 平台化能力补齐（已完成）

`ConductorService.decide()` 已补齐旧 Orchestrator 的关键输出：`tool_subset` 与 `cost_policy`，使 Conductor 成为可替换旧 Orchestrator 的决策入口。

- 新增 `test_conductor_service.py`，覆盖工具子集与成本策略补齐。

### 5.9 Orchestrator 兼容门面（已完成）

`OrchestratorService.decide()` 在 `ENABLE_CONDUCTOR` 开启时优先委托 `ConductorService.decide()`，失败再回退旧规则链路。应用调试 / OpenAPI / Web App / 微信等现有调用方无需逐个改造即可统一到 Conductor。

- 新增 `RoutingDecision.from_dict()` 用于 Conductor 输出转 RoutingDecision。
- 相关测试：`test_orchestrator_service.py` 新增 1 项。

### 5.10 Checkpoint / Resume（已完成）

`ExecutionCoordinatorService.execute(..., resume=True)` 可基于 `SubtaskRegistryService` 的 Redis/内存快照恢复执行：已完成/失败任务直接复用，未完成任务继续执行。

- 恢复时标记 `resumed:completed` / `resumed:failed` 警告。
- 相关测试：`test_execution_coordinator_service.py` 新增 1 项。

### 5.11 Replan 能力（已完成）

`ExecutionCoordinatorService` 新增 `plan_repairer` 注入点，执行失败后可重新生成计划再执行一次；`ConductorService.repair_plan()` 可将失败反馈带入 LLM 重新规划。

- `SingleAgentExecutor` / `MultiAgentExecutor` 已支持透传 `plan_repairer`，首页助手执行器已接入 `ConductorService.repair_plan + to_task_plan`。
- 相关测试：`test_execution_coordinator_service.py` 新增 2 项，`test_conductor_service.py` 新增 1 项。

### 5.12 SSE 事件契约测试（已完成）

新增 `test_sse_contracts.py`，固定 `subtask_started` / `subtask_running` / `subtask_completed` / `agent_message` 的事件载荷字段，防止前后端协议再次漂移。

- 当前 4 项契约测试通过。

### 5.13 AgentQueueManager Redis 事件通道（已完成）

`AgentQueueManager.publish()` 会在 Redis 可用时追加事件日志（TTL 24h），`listen` / `alisten` 在 `AGENT_QUEUE_REDIS_CONSUME=1` 时从 Redis 消费事件，失败自动回退内存队列。

- 相关测试：`test_agent_queue_and_base.py` 新增 2 项。

### 5.14 orchestrator_reject 协议补齐（已完成）

`app_debug_service` 的 `orchestrator_reject` 事件补齐 `message` 字段，与前端 `OrchestratorRejectPayload` 契约对齐。

### 5.15 遗留标记分类（已完成）

321 处标记已完成分类：无 `TODO/FIXME/HACK`，260 处兼容标记为存量兼容需求，其余为占位符/临时文件/沙箱等正常业务描述。
