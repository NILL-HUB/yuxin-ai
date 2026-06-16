# 通用 Agent 调度平台 Phase 7 执行计划

## 1. 阶段目标

Phase 7 目标是完成调度日志、成本面板与运营闭环第一版，让管理员可以持续观察、诊断和优化调度系统。该阶段基于已有 `RoutingLog` 表、`RoutingLogService`、`AdminRoutingLogHandler` 和 Phase 5/6 的 cost_policy、billing_events、task_plan_summary、synthesis_summary 字段进行增量增强，不重写既有日志链路。

## 2. 执行原则

- 所有生产代码变更先写失败测试，再实现最小代码通过。
- 优先增强已有 `routing_log` 能力，不在本阶段引入复杂外部可观测平台。
- 管理员可看高细节调度日志，普通用户不能访问 Admin routing logs。
- 用户侧只展示聚合扣费，不展示内部模型、Key、Agent、工具成本拆分。
- 当前阶段允许暂不真实脱敏，但必须预留 `redaction_enabled` 和敏感字段定义。
- 日志保留周期第一版默认 30 天，可通过配置实体/服务表达，不必接真实定时清理任务。
- 前端新增页面和文案必须走 i18n，不允许硬编码中文或英文。
- 阶段结束必须跑 Docker 后端全量和前端 type-check / lint / unit test。

## 3. 任务清单

### 3.1 任务 0：基线确认

#### 目标

确认 Phase 6 已提交且工作区干净，跑 Phase 7 基线门禁。

#### 验收标准

- [ ] Phase 6 commit 后工作区干净。
- [ ] 后端 Docker 全量测试通过。
- [ ] 前端 Docker type-check / lint / unit test 通过。

#### 完成记录

- [x] Phase 6 已提交：`f1f02b4 feat(orchestration): complete phase 6 result synthesis`。
- [x] 后端 Docker 全量基线通过：2085 passed / 6 skipped。
- [x] 前端 Docker type-check / lint / unit test 基线通过：98 files / 355 tests passed。

### 3.2 任务 1：定义 RoutingObservability 标准实体

#### 目标

定义调度日志序列化、脱敏策略、保留策略和统计摘要所需实体，避免散落在 handler/service 中。

#### 建议文件

- 新增：`api/internal/entity/routing_observability_entity.py`
- 新增测试：`api/test/internal/entity/test_routing_observability_entity.py`

#### 验收标准

- [ ] `RoutingLogRetentionPolicy` 默认保留 30 天。
- [ ] `RoutingLogRedactionPolicy` 支持 `redaction_enabled` 和 `sensitive_fields`。
- [ ] `RoutingLogSearchFilters` 支持时间、用户、Agent、Agent 子池、工具、工具子池、模型、Key、状态筛选字段。
- [ ] `RoutingLogMetricsSummary` 支持总数、成功数、失败数、fallback 数、总 credits、平均耗时、命中率字段。
- [ ] 实体序列化稳定，默认值可测试。

#### 完成记录

- [x] 新增 `RoutingLogRetentionPolicy`，默认保留 30 天。
- [x] 新增 `RoutingLogRedactionPolicy`，支持 `redaction_enabled` 与默认 sensitive_fields。
- [x] 新增 `RoutingLogSearchFilters`，覆盖时间、用户、Agent、工具、模型、Key、状态筛选字段。
- [x] 新增 `RoutingLogMetricsSummary`，覆盖总数、成功数、失败数、fallback 数、credits、耗时和命中率字段。
- [x] 聚焦测试通过：`test/internal/entity/test_routing_observability_entity.py` 4 passed。

### 3.3 任务 2：扩展 RoutingLog 数据结构与迁移

#### 目标

让 routing log 能承载 Phase 7 管理员页面需要的筛选字段和成本/耗时信息。

#### 建议文件

- 修改：`api/internal/model/routing_log.py`
- 新增迁移：`api/internal/migration/versions/<revision>_extend_routing_log_observability.py`
- 修改测试：`api/test/scripts/test_verify_migration_upgrade.py` 如需要。

#### 建议新增字段

- `user_query`
- `task_classification`
- `model_selection`
- `agent_pool_hits`
- `tool_pool_hits`
- `key_usage`
- `cost_summary`
- `latency_ms`
- `fallback_reason`
- `redaction_enabled`
- `retention_expires_at`

#### 验收标准

- [ ] migration heads/current 正常。
- [ ] 新字段默认值安全，不破坏已有 routing log。
- [ ] 常用筛选字段有索引或 JSON 结构可序列化。
- [ ] downgrade 可回滚新增字段。

#### 完成记录

- [x] `RoutingLog` 模型新增 user_query、task_classification、model_selection、agent_pool_hits、tool_pool_hits、key_usage、cost_summary、latency_ms、fallback_reason、redaction_enabled、retention_expires_at。
- [x] 新增 migration：`d1e2f3a4b5d1_extend_routing_log_observability.py`。
- [x] 新增 retention_expires_at 与 latency_ms 索引。
- [x] migration heads/current 通过，当前 head 为 `d1e2f3a4b5d1`。
- [x] 聚焦测试通过：`test/internal/model/test_routing_log_model.py` 2 passed。

### 3.4 任务 3：增强 RoutingLogService record/page 序列化

#### 目标

让服务层可以记录完整调度日志，并在 page 查询中支持 Phase 7 筛选字段。

#### 建议文件

- 修改：`api/internal/service/routing_log_service.py`
- 修改测试：`api/test/internal/service/test_routing_log_service.py`

#### 验收标准

- [ ] `record()` 可接收 user_query、task_classification、model_selection、agent_pool_hits、tool_pool_hits、key_usage、cost_summary、latency_ms、fallback_reason、retention_expires_at。
- [ ] `page()` 支持 account_id、status、agent_id、agent_pool、tool_name、tool_pool、model_id、key_id、start_at、end_at 筛选。
- [ ] `_serialize()` 输出完整管理员可见字段。
- [ ] 默认调用保持向后兼容。

#### 完成记录

- [x] `RoutingLogService.record()` 支持 Phase 7 新增日志字段。
- [x] `RoutingLogService.page()` 支持 account/status/agent/tool/model/key/time 过滤参数。
- [x] `_serialize()` 输出完整管理员可见 Phase 7 字段。
- [x] 默认调用保持向后兼容。
- [x] 聚焦测试通过：`test/internal/service/test_routing_log_service.py` 2 passed。

### 3.5 任务 4：敏感字段脱敏策略预留

#### 目标

实现可测试的脱敏工具，不要求默认开启，但需要能在服务层或 schema 层调用。

#### 建议文件

- 新增：`api/internal/service/routing_log_redaction_service.py`
- 新增测试：`api/test/internal/service/test_routing_log_redaction_service.py`

#### 验收标准

- [ ] 默认 `redaction_enabled=False` 时原样返回。
- [ ] 开启后对 configured sensitive fields 进行递归脱敏。
- [ ] 默认敏感字段包括 prompt、raw_prompt、api_key、secret、token、headers、arguments。
- [ ] 不改变原始输入对象。

#### 完成记录

- [x] 新增 `RoutingLogRedactionService`。
- [x] 默认 `redaction_enabled=False` 时返回深拷贝后的原始 payload。
- [x] 开启后递归脱敏 prompt/raw_prompt/api_key/secret/token/headers/arguments。
- [x] 支持自定义 sensitive_fields。
- [x] 不改变原始输入对象。
- [x] 聚焦测试通过：`test/internal/service/test_routing_log_redaction_service.py` 3 passed。

### 3.6 任务 5：运营统计服务

#### 目标

基于 RoutingLog 聚合 Agent/工具/成本/状态统计，为成本面板和运营闭环提供数据。

#### 建议文件

- 新增：`api/internal/service/routing_observability_service.py`
- 新增测试：`api/test/internal/service/test_routing_observability_service.py`

#### 验收标准

- [ ] 输出 agent_pool_hit_rate。
- [ ] 输出 tool_pool_hit_rate。
- [ ] 输出 agent_hit_rate。
- [ ] 输出 tool_success_rate。
- [ ] 输出 status_count、fallback_count、total_credits、avg_latency_ms。
- [ ] 空日志返回 0 值摘要，不抛异常。

#### 完成记录

- [x] 新增 `RoutingObservabilityService`。
- [x] 输出 agent_pool_hit_rate、tool_pool_hit_rate、agent_hit_rate、tool_success_rate。
- [x] 输出 status_count、fallback_count、total_credits、avg_latency_ms。
- [x] 空日志返回 0 值摘要，不抛异常。
- [x] 聚焦测试通过：`test/internal/service/test_routing_observability_service.py` 2 passed。

### 3.7 任务 6：Admin RoutingLog API 筛选与 summary 增强

#### 目标

让管理员可以通过 API 按 PRD 要求筛选路由日志，并读取统计摘要。

#### 建议文件

- 修改：`api/internal/schema/admin_routing_log_schema.py`
- 修改：`api/internal/handler/admin_routing_log_handler.py`
- 修改测试：`api/test/internal/handler/test_phase1_closure_handler.py` 或新增 `api/test/internal/handler/test_admin_routing_log_handler.py`

#### 验收标准

- [ ] list 请求支持 account_id、status、agent_id、agent_pool、tool_name、tool_pool、model_id、key_id、start_at、end_at。
- [ ] 响应包含完整 Phase 7 routing log 字段。
- [ ] 可选返回 summary，包含命中率、成功率、成本和延迟摘要。
- [ ] 保持 `@admin_login_required` 和 `routing_log:read` 权限。
- [ ] 普通用户或无权限管理员不可查看日志。

#### 完成记录

- [x] Admin RoutingLog list 请求支持 account_id、status、agent_id、agent_pool、tool_name、tool_pool、model_id、key_id、start_at、end_at。
- [x] 响应 schema 补齐 Phase 7 完整 routing log 字段。
- [x] 响应支持 summary 字段。
- [x] 保持原有 `@admin_login_required` 与 `routing_log:read` 权限入口。
- [x] 聚焦测试通过：`TestAdminRoutingLogApi` 2 passed。

### 3.8 任务 7：完整请求生成完整日志的服务级闭环

#### 目标

在 Orchestrator/HomeService 可观测输出基础上，把 Phase 5/6 字段组装成 RoutingLogService.record 可接受的完整日志载荷。

#### 建议文件

- 新增：`api/internal/service/routing_observability_payload_service.py`
- 新增测试：`api/test/internal/service/test_routing_observability_payload_service.py`
- 如必要，修改：`api/internal/service/orchestrator_service.py`

#### 验收标准

- [ ] 从 RoutingDecision 生成 routing_decision、task_classification、model_selection、agent_pool_hits、tool_pool_hits、cost_summary。
- [ ] 从 billing_events 生成用户侧聚合 total_credits。
- [ ] fallback_reason 从 decision.reason 或 synthesis_summary.user_warnings 中提取。
- [ ] 不把内部 raw prompt、tool arguments 或 secret 放入用户侧 payload。
- [ ] 该阶段不强制真实写 DB，可先提供可测试 payload builder。

#### 完成记录

- [x] 新增 `RoutingObservabilityPayloadService`。
- [x] 从 RoutingDecision 生成 routing_decision、task_classification、model_selection、agent_pool_hits、tool_pool_hits、cost_summary。
- [x] 从 billing_events 生成用户侧聚合 total_credits。
- [x] 从 synthesis_summary.user_warnings 或 decision.reason 提取 fallback_reason。
- [x] payload 不包含 raw_prompt、tool arguments 或 secret。
- [x] 聚焦测试通过：`test/internal/service/test_routing_observability_payload_service.py` 2 passed。

### 3.9 任务 8：前端 Admin Routing Logs 服务与类型

#### 目标

补充前端 Admin routing logs API service 和类型，为页面展示做准备。

#### 建议文件

- 新增：`ui/src/services/admin-routing-logs.ts`
- 新增测试：`ui/src/services/__tests__/admin-routing-logs.spec.ts`
- 如需要，新增：`ui/src/models/admin-routing-log.ts`

#### 验收标准

- [ ] 前端 service 支持 list 查询参数：时间、用户、Agent、Agent 子池、工具、工具子池、模型、Key、状态。
- [ ] 类型包含 routing_decision、agent_candidates、tool_candidates、billing_events、cost_summary、latency_ms、fallback_reason、summary。
- [ ] service 使用既有 request 工具和 Admin API 风格。
- [ ] 单元测试覆盖 query 参数传递。

#### 完成记录

- [x] 新增 `ui/src/models/admin-routing-log.ts`。
- [x] 新增 `ui/src/services/admin-routing-logs.ts`。
- [x] 前端 service 支持 Phase 7 list 查询参数。
- [x] 类型覆盖 routing_decision、agent/tool candidates、billing_events、cost_summary、latency_ms、fallback_reason、summary。
- [x] 聚焦测试通过：`src/services/__tests__/admin-routing-logs.spec.ts` 1 passed。

### 3.10 任务 9：前端 Admin Routing Logs 页面与路由

#### 目标

提供管理员路由日志页面第一版，可展示筛选条件、日志列表和摘要指标。

#### 建议文件

- 新增：`ui/src/views/admin/RoutingLogsView.vue`
- 新增测试：`ui/src/views/admin/__tests__/RoutingLogsView.spec.ts`
- 修改：`ui/src/router/index.ts`
- 修改：`ui/src/i18n/messages/zh-CN.ts`
- 修改：`ui/src/i18n/messages/en-US.ts`

#### 验收标准

- [ ] 新增 `/admin/routing-logs` 路由，权限为 `routing_log:read`。
- [ ] 页面展示 summary cards：总日志数、成功数、fallback 数、总 credits、平均耗时。
- [ ] 页面展示筛选控件占位：时间、用户、Agent、工具、模型、Key、状态。
- [ ] 页面展示日志列表关键字段：用户问题、任务分类、模型、Agent 子池、工具子池、成本、耗时、状态、fallback 原因。
- [ ] 所有页面文案走 i18n。

#### 完成记录

- [x] 新增 `/admin/routing-logs` 路由，权限为 `routing_log:read`。
- [x] 新增 `RoutingLogsView.vue`，展示 summary cards、筛选控件和日志列表。
- [x] 页面展示用户问题、任务分类、模型、Agent 子池、工具子池、成本、耗时、状态、fallback 原因。
- [x] 新增 zh-CN / en-US admin.routingLogs i18n 文案，页面文案均通过 i18n 获取。
- [x] 聚焦测试通过：`RoutingLogsView.spec.ts` 与 `admin-routing-logs.spec.ts` 共 2 passed。

### 3.11 任务 10：用户侧聚合扣费边界验证

#### 目标

确保普通用户侧继续只看到聚合扣费，不看到内部成本拆分。

#### 建议文件

- 修改测试：`api/test/internal/service/test_home_service.py`
- 修改测试：`ui/src/components/__tests__/BillingUsageIndicator.spec.ts`

#### 验收标准

- [ ] HomeService 用户侧不返回 model_selection、key_usage、internal_cost_breakdown。
- [ ] BillingUsageIndicator 只展示 total_credits 聚合值。
- [ ] 用户侧类型不暴露 key_id、provider_key、internal_cost_breakdown。

#### 完成记录

- [x] HomeService 用户侧不返回 model_selection、key_usage、internal_cost_breakdown。
- [x] BillingUsageIndicator 继续只展示 total_credits 聚合值。
- [x] BillingUsageIndicator 不展示 key_id、model source_name 或 internal_cost_breakdown。
- [x] 聚焦后端测试通过：`test_get_user_intent_should_include_phase2_agent_pool_summary` 1 passed。
- [x] 聚焦前端测试通过：`BillingUsageIndicator.spec.ts` 3 passed。

### 3.12 任务 11：最终全量测试与文档同步

#### 目标

完成最终全量验证，更新 PRD 和本执行文档。

#### 验收标准

- [ ] 后端 Docker 全量测试通过。
- [ ] 后端 migration heads/current 通过。
- [ ] 前端 Docker type-check 通过。
- [ ] 前端 Docker lint 通过。
- [ ] 前端 Docker unit test 通过。
- [ ] PRD 状态更新为 Phase 7 已完成。
- [ ] 本执行文档所有任务完成记录已更新。

#### 完成记录

- [x] 后端 Docker 全量测试通过：2098 passed / 6 skipped。
- [x] 后端 migration heads/current 通过，head/current 为 `d1e2f3a4b5d1`。
- [x] 前端 Docker type-check 通过。
- [x] 前端 Docker lint 通过。
- [x] 前端 Docker unit test 通过：100 files / 357 tests passed。
- [x] PRD 状态更新为 Phase 7 已完成，版本更新为 v2.8。
- [x] 本执行文档所有任务完成记录已更新。

## 4. 推荐执行顺序

1. 先完成实体层和迁移，锁定 RoutingLog 可承载的字段。
2. 再增强 RoutingLogService 的记录、查询和序列化能力。
3. 再实现脱敏策略和运营统计服务，保证后台展示数据安全且可聚合。
4. 再增强 Admin API 和权限测试。
5. 再做前端 service、页面、路由和 i18n。
6. 最后验证普通用户侧扣费边界，跑全量测试并同步文档。

## 5. 阻塞与风险

- 当前没有需要产品确认的阻塞点。
- 已存在 `routing_log` 表和 Admin RoutingLog API，Phase 7 应增量增强，不要重复创建第二套日志表。
- 真实定时清理日志可以后置，本阶段只需保留周期字段和默认策略，避免引入 scheduler 风险。
- 当前阶段可先实现 payload builder，不强制把每个 `/home` intent 请求都写入 DB，以降低对现有入口性能和测试稳定性的影响。
- 前端页面第一版以可观测和筛选结构为主，不做复杂图表库引入，避免新增依赖。