# 通用 Agent 调度平台 Phase 5 执行计划

## 1. 阶段目标

Phase 5 目标是完成模型池、Key 池、成本策略和实时计费事件的第一版闭环，让调度层可以根据任务复杂度、用户预算和模型健康状态选择模型档位，并把模型、Agent、工具执行过程中产生的 usage_delta 转换为用户侧已发生积分消耗。

## 2. 执行原则

- 所有生产代码变更先写失败测试，再实现最小代码通过。
- 第一版不接真实支付，不扣真实余额，只输出可审计、可展示的计费事件。
- 用户侧只展示当前已发生消耗，不展示预估最终成本。
- 成本策略必须能降级模型或拒绝超预算执行。
- Key 池第一版使用内存实体和服务抽象，不接真实密钥，不记录密钥明文。
- 前端新增文案必须走 i18n，不允许硬编码中文或英文。
- 阶段结束必须跑 Docker 后端全量和前端 type-check / lint / unit test。

## 3. 任务清单

### 3.1 任务 0：基线确认

#### 目标

确认 Phase 4 已提交且工作区干净，跑 Phase 5 基线门禁。

#### 验收标准

- [ ] Phase 4 commit 后工作区干净。
- [ ] 后端 Docker 全量测试通过。
- [ ] 前端 Docker type-check / lint / unit test 通过。

#### 完成记录

- [x] Phase 4 commit 后工作区干净开始：`9b1f69f feat(orchestration): complete phase 4 runtime tools`。
- [x] 后端 Docker 全量基线通过：2046 passed / 6 skipped。
- [x] 前端 Docker type-check / lint / unit test 基线通过：97 files / 352 tests passed。

### 3.2 任务 1：定义模型池与 Key 池实体

#### 目标

新增模型池和 Key 池基础实体，为后续服务提供稳定字段和归一化规则。

#### 验收标准

- [ ] ModelPoolItem 支持 provider、model、tier、capabilities、price、context、health、rate_limit。
- [ ] ModelKeyItem 支持 provider、key_id、tenant_scope、status、quota、usage、failure_count。
- [ ] 不保存或输出密钥明文。
- [ ] 默认值和异常输入有归一化测试。

#### 完成记录

- [x] 新增 ModelPoolItem，支持 provider/model/tier/capabilities/price/context/health/rate_limit/enabled 归一化。
- [x] 新增 ModelKeyItem，支持 provider/key_id/tenant_scope/status/quota/usage/failure_count 归一化。
- [x] ModelKeyItem 不保存输入 secret，to_safe_dict 不输出 secret。
- [x] 聚焦测试通过：`test/internal/entity/test_billing_runtime_entity.py` 2 passed。

### 3.3 任务 2：实现 ModelPoolService

#### 目标

根据任务需求、模型档位和健康状态选择可用模型。

#### 验收标准

- [ ] 按 required_capabilities 过滤模型。
- [ ] 按 tier 优先选择 cheap / standard / strong。
- [ ] unhealthy / disabled 模型不进入候选。
- [ ] 支持 fallback 到更低成本可用模型。

#### 完成记录

- [x] 新增 ModelPoolService，支持按 required_capabilities 与 preferred_tier 选择模型。
- [x] disabled 与 unknown health 模型不进入候选。
- [x] 支持 strong/standard 降级到更低成本可用模型。
- [x] 无匹配模型时返回 None。
- [x] 聚焦测试通过：`test/internal/service/test_model_pool_service.py` 4 passed。

### 3.4 任务 3：实现 KeyPoolService

#### 目标

为模型供应商选择可用 Key，并维护配额、失败和熔断状态。

#### 验收标准

- [ ] 只选择 active 且未超 quota 的 Key。
- [ ] 同 provider 多 Key 时优先选择剩余额度最多的 Key。
- [ ] failure_count 超阈值进入 circuit_open。
- [ ] 不输出 secret 明文。

#### 完成记录

- [x] 新增 KeyPoolService，支持 provider 维度选择 active 且未超 quota 的 Key。
- [x] 多 Key 时优先选择 remaining_credits 最大的 Key。
- [x] inactive、quota exhausted、circuit_open Key 不进入候选。
- [x] failure_count 达阈值后状态切换为 circuit_open。
- [x] 聚焦测试通过：`test/internal/service/test_key_pool_service.py` 4 passed。

### 3.5 任务 4：实现 CostPolicyService

#### 目标

根据任务复杂度、预算等级、用户余额和 deep thinking 开关生成执行成本策略。

#### 验收标准

- [ ] simple 默认 cheap 模型、小 Agent/工具数量。
- [ ] medium 默认 standard 模型。
- [ ] complex 默认 strong 模型并允许 deep thinking。
- [ ] 低预算时降级模型档位和限制 Agent/工具数量。
- [ ] 余额不足时返回 rejected 策略和 stable reason。

#### 完成记录

- [x] 新增 CostPolicyService，按 task_complexity、budget_level、balance_credits 和 deep_thinking_requested 输出成本策略。
- [x] simple 使用 cheap 策略，medium 使用 standard 策略，complex 使用 strong 策略。
- [x] low budget 降级到 cheap 并关闭 deep thinking。
- [x] balance 不足返回 allowed=False 和 insufficient_balance。
- [x] 聚焦测试通过：`test/internal/service/test_cost_policy_service.py` 4 passed。

### 3.6 任务 5：实现 BillingMeteringService

#### 目标

将模型、Agent、工具 usage_delta 转换为统一 billing events。

#### 验收标准

- [ ] 输出 billing_started、billing_delta、billing_summary、billing_cancelled、billing_final。
- [ ] total_credits 单调递增，cancel 不追加预估费用。
- [ ] 事件包含 source_type、source_name、delta_credits、total_credits、reason、metadata。
- [ ] 支持 token usage 到 credits 的可配置转换。

#### 完成记录

- [x] BillingUsageDelta 支持 metadata 并在 SSE payload 中输出。
- [x] BillingUsageAggregator 支持 credits_per_1k_tokens 配置。
- [x] 新增 model_tokens，将 input/output token usage 转换为 credits delta。
- [x] cancelled 事件继续只保留当前已发生 total_credits，不追加预估费用。
- [x] 聚焦测试通过：`test/internal/service/test_billing_metering_service.py` 5 passed。

### 3.7 任务 6：Orchestrator 输出成本策略摘要

#### 目标

调度决策中附加 cost_policy 和 billing_events，供前端和管理端观测。

#### 验收标准

- [ ] RoutingDecision 包含 cost_policy。
- [ ] Orchestrator fallback 包含 safe cost_policy。
- [ ] HomeService 返回 billing_events 初始事件。
- [ ] 不影响现有 Orchestrator 测试。

#### 完成记录

- [x] RoutingDecision 新增 cost_policy 与 billing_events 字段。
- [x] Orchestrator 正常与 fallback 决策均输出 safe cost_policy 和 billing_started 事件。
- [x] HomeService 返回 cost_policy 与 billing_events 初始事件。
- [x] 聚焦测试通过：`test_orchestrator_service.py` 与 `test_home_service.py` 共 20 passed。

### 3.8 任务 7：前端计费组件 i18n 与事件字段增强

#### 目标

增强 BillingUsageIndicator，使用 i18n 并展示当前已发生 credits 与取消状态。

#### 验收标准

- [ ] 组件不硬编码中文或英文展示文案。
- [ ] 支持 metadata 字段但不展示敏感信息。
- [ ] cancelled 状态展示当前已发生消耗。
- [ ] 前端类型与后端事件字段一致。

#### 完成记录

- [x] BillingUsageEvent 前端类型支持 metadata。
- [x] BillingUsageIndicator 改为使用 `billing.usage.*` i18n key，不再硬编码中文或英文展示文案。
- [x] zh-CN 与 en-US 均新增 billing usage 文案。
- [x] cancelled 状态继续展示当前已发生 total_credits。
- [x] 聚焦测试通过：`BillingUsageIndicator.spec.ts` 3 passed。

### 3.9 任务 8：Admin 成本可观测补充

#### 目标

让管理端路由日志和计费事件字段结构一致，便于后续面板消费。

#### 验收标准

- [ ] AdminRoutingLog schema billing_events 支持 metadata。
- [ ] 新增测试确认 billing_events 不丢字段。
- [ ] 不改现有管理端路由权限。

#### 完成记录

- [x] Admin routing log 测试样例补充 billing_events.metadata。
- [x] 验证 AdminRoutingLog schema 不丢失 billing_events metadata 字段。
- [x] 不改现有管理端路由权限。
- [x] 聚焦测试通过：`TestAdminRoutingLogApi` 2 passed。

### 3.10 任务 9：最终全量测试与文档同步

#### 目标

完成最终全量验证，更新 PRD 和本执行文档。

#### 验收标准

- [ ] 后端 Docker 全量测试通过。
- [ ] 前端 Docker type-check 通过。
- [ ] 前端 Docker lint 通过。
- [ ] 前端 Docker unit test 通过。
- [ ] PRD 状态更新为 Phase 5 已完成。
- [ ] 本执行文档所有任务完成记录已更新。

#### 完成记录

- [x] 后端 Docker 全量测试通过：2062 passed / 6 skipped。
- [x] 前端 Docker type-check 通过。
- [x] 前端 Docker lint 通过。
- [x] 前端 Docker unit test 通过：97 files / 353 tests passed。
- [x] PRD 状态更新为 Phase 5 已完成，版本更新为 v2.6。
- [x] 本执行文档所有任务完成记录已更新。
