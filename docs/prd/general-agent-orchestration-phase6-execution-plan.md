# 通用 Agent 调度平台 Phase 6 执行计划

## 1. 阶段目标

Phase 6 目标是完成复杂任务的结构化拆解、多 Agent 执行编排和最终结果汇总器第一版闭环。系统应能把复杂需求拆成子任务，按执行模式运行 direct、single-agent、multi-agent parallel、multi-agent serial、deep-thinking 和 fallback 路径，并通过 ResultSynthesizer 输出面向用户的最终答案，而不是把多个 Agent 原始输出直接暴露给用户。

## 2. 执行原则

- 所有生产代码变更先写失败测试，再实现最小代码通过。
- 第一版不接真实异步任务队列，不改现有 AssistantAgentService 主链路的稳定行为。
- ExecutionCoordinator 使用可注入 executor，以便单元测试覆盖成功、失败、串行、并行、fallback。
- ResultSynthesizer 只输出用户可见字段，隐藏 agent_id、内部 task_id、工具内部参数和 internal_notes。
- 下游 Agent 失败不应导致整体请求崩溃，应返回部分结果、warnings 和可解释 fallback。
- 与 Phase 5 计费兼容，AgentResult 和 final answer 保留 cost_summary / billing_events 扩展位。
- 前端新增文案必须走 i18n，不允许硬编码中文或英文。
- 阶段结束必须跑 Docker 后端全量和前端 type-check / lint / unit test。

## 3. 任务清单

### 3.1 任务 0：基线确认

#### 目标

确认 Phase 5 已提交且工作区干净，跑 Phase 6 基线门禁。

#### 验收标准

- [ ] Phase 5 commit 后工作区干净。
- [ ] 后端 Docker 全量测试通过。
- [ ] 前端 Docker type-check / lint / unit test 通过。

#### 完成记录

- [x] Phase 5 已提交：`83a3a88 feat(orchestration): complete phase 5 cost metering`。
- [x] 后端 Docker 全量基线通过：2062 passed / 6 skipped。
- [x] 前端 Docker type-check / lint / unit test 基线通过：97 files / 353 tests passed。

### 3.2 任务 1：定义 AgentResult 与 TaskPlan 标准实体

#### 目标

新增 Phase 6 执行编排所需的标准实体，避免复用现有 queue AgentResult 造成语义混淆。

#### 建议文件

- 新增：`api/internal/entity/execution_orchestration_entity.py`
- 新增测试：`api/test/internal/entity/test_execution_orchestration_entity.py`

#### 验收标准

- [ ] `TaskPlanItem` 支持 task_id、title、description、agent_pool、required_capabilities、depends_on、execution_order、risk_level。
- [ ] `TaskPlan` 支持 original_query、items、execution_mode、reason。
- [ ] `OrchestratedAgentResult` 支持 agent_id、task_id、answer、confidence、sources、tool_calls、warnings、errors、cost、metadata。
- [ ] 实体默认值稳定，confidence 被归一化到 0 到 1。
- [ ] `to_user_safe_dict()` 不输出内部 metadata 和敏感 tool 参数。

#### 完成记录

- [x] 新增 `TaskPlanItem`，支持 task_id/title/description/agent_pool/required_capabilities/depends_on/execution_order/risk_level。
- [x] 新增 `TaskPlan`，支持 original_query/items/execution_mode/reason 与用户可见 summary。
- [x] 新增 `OrchestratedAgentResult`，支持标准 Agent 执行结果字段。
- [x] confidence 已归一化到 0 到 1。
- [x] `to_user_safe_dict()` 不输出 metadata，不输出 tool arguments 等敏感内部参数。
- [x] 聚焦测试通过：`test/internal/entity/test_execution_orchestration_entity.py` 3 passed。

### 3.3 任务 2：实现 TaskPlanner

#### 目标

根据 RoutingDecision 和原始 query 生成结构化任务计划。

#### 建议文件

- 新增：`api/internal/service/task_planner_service.py`
- 新增测试：`api/test/internal/service/test_task_planner_service.py`

#### 验收标准

- [ ] simple/direct_answer 生成单任务计划。
- [ ] single_agent 生成单 Agent 子任务。
- [ ] multi_agent 复杂需求生成多个子任务，包含 agent_pool 和 required_capabilities。
- [ ] deep_thinking 复杂任务生成 research、analysis、synthesis 等阶段性子任务。
- [ ] 计划数量受 cost_policy.max_agent_count 限制。
- [ ] 高风险或 reject_or_confirm 决策生成 blocked plan，不进入执行。

#### 完成记录

- [x] 新增 `TaskPlannerService`，可根据 RoutingDecision 生成 TaskPlan。
- [x] direct_answer 和 single_agent 均生成单任务计划。
- [x] multi_agent 生成跨 agent_pool 的并行任务，并受 `cost_policy.max_agent_count` 限制。
- [x] deep_thinking 生成 research、analysis、synthesis 串行依赖任务。
- [x] reject_or_confirm 决策生成 blocked plan，不进入执行。
- [x] 聚焦测试通过：`test/internal/service/test_task_planner_service.py` 5 passed。

### 3.4 任务 3：实现 ExecutionCoordinator 基础执行模式

#### 目标

提供统一执行入口，支持 direct_answer、single_agent、multi_agent_parallel、multi_agent_serial、deep_thinking 和 fallback。

#### 建议文件

- 新增：`api/internal/service/execution_coordinator_service.py`
- 新增测试：`api/test/internal/service/test_execution_coordinator_service.py`

#### 验收标准

- [ ] direct_answer 通过 direct executor 返回单个 OrchestratedAgentResult。
- [ ] single_agent 只执行一个子任务。
- [ ] multi_agent_parallel 会执行所有无依赖子任务，并聚合结果。
- [ ] multi_agent_serial 按 execution_order 和 depends_on 顺序执行。
- [ ] deep_thinking 支持阶段性执行并保留阶段 warnings。
- [ ] executor 可注入，测试无需真实 LLM 或真实 Agent。

#### 完成记录

- [x] 新增 `ExecutionCoordinatorService`，支持可注入 executor。
- [x] direct_answer 执行单个 direct task。
- [x] single_agent 只执行首个子任务。
- [x] multi_agent_parallel 执行所有任务并聚合结果。
- [x] multi_agent_serial 按 execution_order 执行任务。
- [x] deep_thinking 支持阶段 warning。
- [x] 聚焦测试通过：`test/internal/service/test_execution_coordinator_service.py` 5 passed。

### 3.5 任务 4：ExecutionCoordinator 失败隔离与 fallback

#### 目标

保证下游 Agent 失败不会导致整体请求崩溃。

#### 建议文件

- 修改：`api/internal/service/execution_coordinator_service.py`
- 修改测试：`api/test/internal/service/test_execution_coordinator_service.py`

#### 验收标准

- [ ] 单个 Agent 失败时记录 errors 和 warnings。
- [ ] 多 Agent 中部分失败时仍返回已完成 AgentResult。
- [ ] 所有 Agent 失败时返回 fallback result。
- [ ] fallback reason 稳定可测试。
- [ ] 失败路径不泄露异常堆栈给用户侧结果。

#### 完成记录

- [x] 单个 Agent 失败时返回 task-level fallback result，记录 stable errors/warnings。
- [x] 多 Agent 部分失败时保留成功结果，同时返回失败任务的安全 fallback。
- [x] 所有 Agent 失败时返回单个 global fallback result。
- [x] 失败路径不向用户结果泄露异常堆栈。
- [x] 聚焦测试通过：`test/internal/service/test_execution_coordinator_service.py` 8 passed。

### 3.6 任务 5：实现 ResultSynthesizer

#### 目标

把多个 AgentResult 合并成最终用户答案。

#### 建议文件

- 新增：`api/internal/service/result_synthesizer_service.py`
- 新增测试：`api/test/internal/service/test_result_synthesizer_service.py`

#### 验收标准

- [ ] 多 Agent 结果不会原样直出。
- [ ] 能合并、去重、格式化 answer 和 sources。
- [ ] 失败结果不参与主答案，但转为 user_warnings。
- [ ] final confidence 基于有效结果 confidence 加权计算。
- [ ] 输出包含 final_answer、summary、confidence、visible_sources、user_warnings。
- [ ] 输出不包含 agent_id、内部 task_id、internal_notes。

#### 完成记录

- [x] 新增 `ResultSynthesizerService`，合并多个 AgentResult 为用户可见最终答案。
- [x] 多 Agent answer 合并输出，不原样暴露 agent_id/task_id/internal metadata。
- [x] sources 去重合并。
- [x] 失败结果转为 user_warnings，不参与主答案。
- [x] final confidence 基于有效结果平均计算。
- [x] 无有效结果时输出 fallback final answer。
- [x] 聚焦测试通过：`test/internal/service/test_result_synthesizer_service.py` 3 passed。

### 3.7 任务 6：冲突检测与质量检查

#### 目标

新增结果冲突检测和质量检查第一版规则。

#### 建议文件

- 新增：`api/internal/service/result_quality_checker_service.py`
- 修改：`api/internal/service/result_synthesizer_service.py`
- 新增测试：`api/test/internal/service/test_result_quality_checker_service.py`

#### 验收标准

- [ ] 互斥结论或明显冲突的结果会生成 conflict warning。
- [ ] 低 confidence 结果降低 final confidence。
- [ ] 无有效结果时生成 fallback final answer。
- [ ] high risk warning 会传递到用户可见 warnings。
- [ ] 质量检查不泄露内部 Agent 配置。

#### 完成记录

- [x] 新增 `ResultQualityCheckerService`，支持冲突、低置信度与 high risk warning 检测。
- [x] ResultSynthesizer 集成质量检查 warning。
- [x] 低 confidence 结果会降低 final confidence。
- [x] 无有效结果时继续输出 fallback final answer。
- [x] 质量检查不输出内部 metadata/Agent 配置。
- [x] 聚焦测试通过：`test_result_quality_checker_service.py` 与 `test_result_synthesizer_service.py` 共 7 passed。

### 3.8 任务 7：Orchestrator 串联 TaskPlanner / ExecutionCoordinator / ResultSynthesizer

#### 目标

让 Orchestrator 可以输出 Phase 6 结构化编排摘要，同时不破坏现有主链路。

#### 建议文件

- 修改：`api/internal/entity/orchestrator_entity.py`
- 修改：`api/internal/service/orchestrator_service.py`
- 修改测试：`api/test/internal/service/test_orchestrator_service.py`

#### 验收标准

- [ ] RoutingDecision 包含 task_plan_summary。
- [ ] OrchestratorService 可注入 TaskPlanner、ExecutionCoordinator、ResultSynthesizer。
- [ ] 默认仍只做决策，不强制真实执行下游 Agent。
- [ ] fallback 决策包含空 task_plan_summary 和 safe synthesis placeholder。
- [ ] 不影响 Phase 1-5 现有测试。

#### 完成记录

- [x] RoutingDecision 新增 `task_plan_summary` 与 `synthesis_summary`。
- [x] OrchestratorService 注入并使用 `TaskPlannerService` 生成计划摘要。
- [x] 默认仍只做决策和摘要，不真实执行下游 Agent。
- [x] fallback 决策包含 safe task_plan_summary 与 empty synthesis_summary。
- [x] 不影响 Phase 1-5 既有 Orchestrator 行为。
- [x] 聚焦测试通过：`test/internal/service/test_orchestrator_service.py` 9 passed。

### 3.9 任务 8：HomeService 返回结果汇总占位结构

#### 目标

主入口 `/home` intent 结果中增加 Phase 6 可观测字段，便于前端和后续 SSE 对接。

#### 建议文件

- 修改：`api/internal/service/home_service.py`
- 修改测试：`api/test/internal/service/test_home_service.py`

#### 验收标准

- [ ] HomeService 返回 task_plan_summary。
- [ ] HomeService 返回 synthesis_summary。
- [ ] 普通用户字段不包含内部 Agent 原始输出。
- [ ] 与 Phase 5 cost_policy / billing_events 字段兼容。

#### 完成记录

- [x] HomeService intent 结果新增 `task_plan_summary`。
- [x] HomeService intent 结果新增 `synthesis_summary`。
- [x] 普通用户字段不包含内部 Agent 原始输出。
- [x] 与 Phase 5 cost_policy / billing_events 字段兼容。
- [x] 聚焦测试通过：`test_get_user_intent_should_include_phase2_agent_pool_summary` 1 passed。

### 3.10 任务 9：前端类型与 i18n 补充

#### 目标

为后续前端展示编排进度和结果汇总补充类型和 i18n 文案。

#### 建议文件

- 修改：`ui/src/models` 下主入口或 orchestration 类型文件。
- 修改：`ui/src/i18n/messages/zh-CN.ts`
- 修改：`ui/src/i18n/messages/en-US.ts`
- 新增或修改对应前端测试。

#### 验收标准

- [ ] 前端类型支持 task_plan_summary 和 synthesis_summary。
- [ ] 新增文案全部走 i18n。
- [ ] 不把 Agent 原始输出字段暴露为普通用户 UI 类型。
- [ ] type-check 通过。

#### 完成记录

- [x] 前端 `HomeIntentData` 支持 `task_plan_summary` 与 `synthesis_summary`。
- [x] 新增 `HomeTaskPlanSummary`、`HomeTaskPlanSummaryItem`、`HomeSynthesisSummary` 类型。
- [x] 新增 home orchestration i18n 文案，zh-CN / en-US 均已覆盖。
- [x] 前端类型未暴露 raw_agent_outputs 或 internal_notes。
- [x] 聚焦测试通过：`src/models/__tests__/home.spec.ts` 2 passed。

### 3.11 任务 10：最终全量测试与文档同步

#### 目标

完成最终全量验证，更新 PRD 和本执行文档。

#### 验收标准

- [ ] 后端 Docker 全量测试通过。
- [ ] 前端 Docker type-check 通过。
- [ ] 前端 Docker lint 通过。
- [ ] 前端 Docker unit test 通过。
- [ ] PRD 状态更新为 Phase 6 已完成。
- [ ] 本执行文档所有任务完成记录已更新。

#### 完成记录

- [x] 后端 Docker 全量测试通过：2085 passed / 6 skipped。
- [x] 前端 Docker type-check 通过。
- [x] 前端 Docker lint 通过。
- [x] 前端 Docker unit test 通过：98 files / 355 tests passed。
- [x] PRD 状态更新为 Phase 6 已完成，版本更新为 v2.7。
- [x] 本执行文档所有任务完成记录已更新。

## 4. 推荐执行顺序

1. 先完成实体层，锁定 TaskPlan 和 OrchestratedAgentResult 结构。
2. 再完成 TaskPlanner，确保复杂任务能被拆分但不真实执行。
3. 再完成 ExecutionCoordinator，以可注入 executor 做编排和失败隔离。
4. 再完成 ResultSynthesizer 和 QualityChecker，保证用户只看到汇总结果。
5. 最后串联 Orchestrator / HomeService 和前端类型，避免过早改动主链路。

## 5. 阻塞与风险

- 当前没有需要产品确认的阻塞点。
- 第一版建议不接真实 A2A 并行调用，使用 executor 抽象和测试桩验证编排语义，避免一次性扩大到网络、权限、计费、超时和重试全链路。
- 如果后续要让 `/assistant-agent/chat` 真实进入多 Agent 执行，需要另起任务处理 SSE 事件协议、取消语义和真实下游 Agent 调用超时。