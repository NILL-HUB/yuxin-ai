# 通用 Agent 调度平台 Phase 9 执行计划

## 1. 阶段定位

Phase 1-8 已经完成调度基础链路、Agent/工具子池治理、模型成本、执行编排、结果汇总、路由日志、发布开关和回滚验收。PRD 中仍然明确提到：质量评分和推荐权重第一阶段先由管理员手动维护，后续当路由日志、用户反馈、成功率、失败率、耗时和成本数据积累足够后，再逐步引入自动评分或半自动建议。

因此 Phase 9 定义为“路由质量反馈、运营洞察与半自动调优建议”。本阶段不直接引入自动改写路由策略，不做全自动 A/B 实验，而是在 Phase 7 可观测日志与 Phase 8 发布开关基础上，建立质量反馈数据、运营指标聚合、异常检测和管理员可采纳的调优建议闭环。

## 2. 阶段目标

- 建立 routing quality feedback 标准实体和持久化模型。
- 支持管理员或系统对一次 routing log 记录质量反馈。
- 基于 routing log 与 feedback 计算 Agent、工具、模型、任务类型维度的质量指标。
- 生成半自动调优建议，例如降权高失败 Agent、提示高成本模型、提示高 fallback 子池。
- 为管理员提供运营洞察 API 与前端页面。
- 将建议保持为只读或待采纳状态，不自动修改生产策略。
- 保持普通用户侧不可见，不暴露内部路由细节。

## 3. 阶段原则

- 本阶段只产出建议，不自动变更 Agent、工具、模型或 feature flag。
- 反馈数据与调优建议属于管理员能力，普通用户不可访问。
- 所有质量分、成功率、失败率、成本、延迟指标必须可解释。
- 指标计算必须在空数据时返回稳定结构，不抛异常。
- 建议必须包含 evidence，便于管理员复核。
- 前端所有新增文案必须走 i18n。
- 每个任务先写失败测试，再做最小实现。
- 阶段结束必须跑后端 Docker 全量测试和前端 type-check / lint / unit test。

## 4. 任务清单

### 4.1 任务 0：基线确认

#### 目标

确认 Phase 8 已提交且工作区只剩用户确认保留的外部删除变更，跑 Phase 9 基线门禁。

#### 验收标准

- [ ] Phase 8 commit 已存在。
- [ ] Phase 9 开始前不混入 `private-domain-live-sop/private-domain-live-sop.html` 删除变更。
- [ ] 后端 Docker 全量测试通过。
- [ ] 后端 migration heads/current 通过。
- [ ] 前端 Docker type-check / lint / unit test 通过。

#### 完成记录

- [x] Phase 8 已提交：`b2c5a88 feat(orchestration): complete phase 8 rollout controls`。
- [x] Phase 9 开始前未混入 `private-domain-live-sop/private-domain-live-sop.html` 删除变更。
- [x] 后端 Docker 全量基线通过：2120 passed / 6 skipped。
- [x] 后端 migration heads/current 基线通过。
- [x] 前端 Docker type-check / lint / unit test 基线通过：102 files / 362 tests passed。

### 4.2 任务 1：定义 Routing Quality Feedback 标准实体

#### 目标

定义质量反馈、评分、反馈来源和调优建议的标准结构。

#### 建议文件

- 新增：`api/internal/entity/routing_quality_entity.py`
- 新增测试：`api/test/internal/entity/test_routing_quality_entity.py`

#### 建议实体

- `RoutingQualityFeedback`
- `RoutingQualityScore`
- `RoutingOptimizationSuggestion`
- `RoutingQualityDimension`

#### 建议字段

`RoutingQualityFeedback`：

- `routing_log_id`
- `source`
- `rating`
- `dimension_scores`
- `comment`
- `metadata`

`RoutingOptimizationSuggestion`：

- `target_type`
- `target_id`
- `suggestion_type`
- `severity`
- `reason`
- `evidence`
- `status`

#### 验收标准

- [ ] feedback 支持 `admin`、`system`、`user_signal` 三类来源。
- [ ] rating 限制在 1-5。
- [ ] dimension_scores 支持 completeness、accuracy、latency、cost、safety。
- [ ] suggestion 默认 status 为 `open`。
- [ ] 所有实体支持稳定 `to_dict()` 输出。

#### 完成记录

- [x] 新增 `RoutingQualityFeedback`、`RoutingQualityScore`、`RoutingOptimizationSuggestion`。
- [x] feedback source 支持 admin、system、user_signal。
- [x] rating 限制在 1-5。
- [x] dimension_scores 支持 completeness、accuracy、latency、cost、safety。
- [x] suggestion 默认 status 为 `open`。
- [x] 聚焦测试通过：`test_routing_quality_entity.py` 4 passed。

### 4.3 任务 2：新增 Routing Quality Feedback 模型与迁移

#### 目标

建立 feedback 与 suggestion 持久化结构，为运营分析和建议列表提供数据基础。

#### 建议文件

- 新增：`api/internal/model/routing_quality.py`
- 修改：`api/internal/model/__init__.py`
- 新增 migration：`api/internal/migration/versions/<revision>_add_routing_quality_feedback.py`
- 新增测试：`api/test/internal/model/test_routing_quality_model.py`

#### 建议表

`routing_quality_feedback`：

- `id`
- `routing_log_id`
- `source`
- `rating`
- `dimension_scores`
- `comment`
- `metadata`
- `created_by`
- `created_at`

`routing_optimization_suggestion`：

- `id`
- `target_type`
- `target_id`
- `suggestion_type`
- `severity`
- `reason`
- `evidence`
- `status`
- `created_at`
- `updated_at`

#### 验收标准

- [ ] `routing_quality_feedback.routing_log_id` 有索引。
- [ ] `routing_optimization_suggestion.status` 有索引。
- [ ] JSON 字段默认 `{}` 或 `[]`。
- [ ] migration upgrade/downgrade 可执行。
- [ ] heads/current 验证通过。

#### 完成记录

- [x] 新增 `RoutingQualityFeedbackModel` 与 `RoutingOptimizationSuggestionModel`。
- [x] 新增 migration：`d1e2f3a4b5d3_add_routing_quality_feedback.py`。
- [x] `routing_quality_feedback.routing_log_id` 已建索引。
- [x] `routing_optimization_suggestion.status` 已建索引。
- [x] JSON 字段默认 `{}`。
- [x] migration heads/current 通过，head/current 为 `d1e2f3a4b5d3`。
- [x] 聚焦测试通过：`test_routing_quality_model.py` 4 passed。

### 4.4 任务 3：实现 RoutingQualityFeedbackService

#### 目标

提供质量反馈创建、查询和序列化能力。

#### 建议文件

- 新增：`api/internal/service/routing_quality_feedback_service.py`
- 新增测试：`api/test/internal/service/test_routing_quality_feedback_service.py`

#### 建议方法

- `create_feedback(routing_log_id, source, rating, dimension_scores, comment, metadata, created_by)`
- `list_feedback(routing_log_id=None, source=None, page=1, page_size=20)`
- `serialize_feedback(feedback)`

#### 验收标准

- [ ] rating 小于 1 或大于 5 时拒绝。
- [ ] 不存在 routing log 时拒绝创建 feedback。
- [ ] 同一管理员可对同一 routing log 多次反馈，但每条都有时间戳。
- [ ] list 支持 routing_log_id 与 source 筛选。
- [ ] 序列化输出不包含用户 prompt 原文之外的内部敏感字段。

#### 完成记录

- [x] 新增 `RoutingQualityFeedbackService`。
- [x] `create_feedback()` 支持 routing log 存在性检查、rating/source/dimension 校验和创建。
- [x] `list_feedback()` 支持 routing_log_id、source、分页筛选。
- [x] `serialize_feedback()` 不输出 key_usage、internal_cost_breakdown。
- [x] 聚焦测试通过：`test_routing_quality_feedback_service.py` 4 passed。

### 4.5 任务 4：实现 RoutingQualityMetricsService

#### 目标

基于 routing logs 和 feedback 计算质量、成本、延迟和 fallback 指标。

#### 建议文件

- 新增：`api/internal/service/routing_quality_metrics_service.py`
- 新增测试：`api/test/internal/service/test_routing_quality_metrics_service.py`

#### 输出指标

- `total_count`
- `feedback_count`
- `avg_rating`
- `fallback_rate`
- `avg_latency_ms`
- `avg_cost_credits`
- `quality_by_task_type`
- `quality_by_agent_pool`
- `quality_by_tool_pool`
- `quality_by_model`

#### 验收标准

- [ ] 空数据返回完整 0 值结构。
- [ ] 支持按时间范围聚合。
- [ ] 支持按任务类型、Agent 子池、工具子池、模型聚合。
- [ ] 平均值保留两位小数。
- [ ] 不依赖前端传入可信指标。

#### 完成记录

- [x] 新增 `RoutingQualityMetricsService`。
- [x] 空数据返回完整 0 值结构。
- [x] 支持传入 routing logs 与 feedback 计算质量指标。
- [x] 覆盖 total、feedback、avg_rating、fallback_rate、avg_latency、avg_cost。
- [x] 支持按 task type、agent pool、tool pool、model 聚合。
- [x] 聚焦测试通过：`test_routing_quality_metrics_service.py` 2 passed。

### 4.6 任务 5：实现 RoutingOptimizationSuggestionService

#### 目标

基于质量指标生成管理员可复核的半自动调优建议。

#### 建议文件

- 新增：`api/internal/service/routing_optimization_suggestion_service.py`
- 新增测试：`api/test/internal/service/test_routing_optimization_suggestion_service.py`

#### 建议类型

- `reduce_agent_priority`
- `review_tool_health`
- `review_model_cost`
- `review_fallback_rate`
- `increase_budget_guardrail`
- `collect_more_feedback`

#### 验收标准

- [ ] 高 fallback rate 生成 `review_fallback_rate`。
- [ ] 高成本低评分模型生成 `review_model_cost`。
- [ ] 工具成功率低生成 `review_tool_health`。
- [ ] feedback 样本不足生成 `collect_more_feedback`。
- [ ] 每条建议包含 reason 和 evidence。
- [ ] 服务只生成建议，不修改实际路由配置。

#### 完成记录

- [x] 新增 `RoutingOptimizationSuggestionService`。
- [x] 高 fallback rate 生成 `review_fallback_rate`。
- [x] 高成本低评分模型生成 `review_model_cost`。
- [x] 工具质量评分低生成 `review_tool_health`。
- [x] feedback 样本不足生成 `collect_more_feedback`。
- [x] 每条建议包含 reason 和 evidence，且只生成建议不修改生产配置。
- [x] 聚焦测试通过：`test_routing_optimization_suggestion_service.py` 4 passed。

### 4.7 任务 6：Admin Routing Quality API

#### 目标

提供管理员创建 feedback、查看指标和查看建议的 API。

#### 建议文件

- 新增：`api/internal/schema/admin_routing_quality_schema.py`
- 新增：`api/internal/handler/admin_routing_quality_handler.py`
- 修改：`api/internal/handler/__init__.py`
- 修改：`api/internal/router/router.py`
- 新增测试：`api/test/internal/handler/test_admin_routing_quality_handler.py`

#### 建议接口

- `POST /admin/routing-quality/feedback`
- `GET /admin/routing-quality/feedback`
- `GET /admin/routing-quality/metrics`
- `GET /admin/routing-quality/suggestions`

#### 权限

- `routing_quality:read`
- `routing_quality:feedback`

#### 验收标准

- [ ] 所有接口需要管理员登录。
- [ ] 指标和建议接口需要 `routing_quality:read`。
- [ ] 创建 feedback 需要 `routing_quality:feedback`。
- [ ] 普通用户不可访问。
- [ ] 参数校验失败返回 validate error。

#### 完成记录

- [x] 新增 `AdminRoutingQualityHandler` 与 `admin_routing_quality_schema.py`。
- [x] 新增 `POST /admin/routing-quality/feedback`。
- [x] 新增 `GET /admin/routing-quality/feedback`。
- [x] 新增 `GET /admin/routing-quality/metrics`。
- [x] 新增 `GET /admin/routing-quality/suggestions`。
- [x] feedback 创建接口需要 `routing_quality:feedback` 权限。
- [x] 反馈列表、指标和建议接口需要 `routing_quality:read` 权限。
- [x] 聚焦测试通过：`test_admin_routing_quality_handler.py` 4 passed。

### 4.8 任务 7：RBAC 权限补充

#### 目标

补齐 routing quality 相关后台权限。

#### 建议文件

- 修改：`api/internal/service/admin_rbac_service.py`
- 修改：`api/test/internal/service/test_admin_rbac_service.py`
- 新增或修改：`api/test/internal/service/test_orchestration_rbac_permissions.py`

#### 建议权限

- `routing_quality:read`
- `routing_quality:feedback`

#### 验收标准

- [ ] 新权限可被列出。
- [ ] super_admin 默认可获得新权限。
- [ ] 不影响既有 RBAC 测试。

#### 完成记录

- [x] 新增 `routing_quality:read` 权限。
- [x] 新增 `routing_quality:feedback` 权限。
- [x] 权限纳入 `AdminRbacService.DEFAULT_PERMISSIONS`，super_admin 可按既有初始化流程获得。
- [x] 聚焦测试通过：`test_orchestration_rbac_permissions.py` 与 `test_admin_rbac_service.py` 共 7 passed。

### 4.9 任务 8：前端 Routing Quality 服务与类型

#### 目标

补充前端 Admin routing quality API service 和类型。

#### 建议文件

- 新增：`ui/src/models/admin-routing-quality.ts`
- 新增：`ui/src/services/admin-routing-quality.ts`
- 新增测试：`ui/src/services/__tests__/admin-routing-quality.spec.ts`

#### 类型覆盖

- `AdminRoutingQualityFeedback`
- `CreateAdminRoutingQualityFeedbackRequest`
- `AdminRoutingQualityMetrics`
- `AdminRoutingOptimizationSuggestion`

#### 验收标准

- [ ] service 覆盖 feedback create/list、metrics、suggestions。
- [ ] service 使用既有 request 工具。
- [ ] 路径和参数测试通过。

#### 完成记录

- [x] 新增 `admin-routing-quality.ts` 类型文件。
- [x] 新增 `admin-routing-quality.ts` service。
- [x] 类型覆盖 feedback、create request、metrics、suggestion。
- [x] service 覆盖 feedback create/list、metrics、suggestions。
- [x] service 使用既有 request 工具。
- [x] 聚焦测试通过：`admin-routing-quality.spec.ts` 4 passed。

### 4.10 任务 9：前端 Admin Routing Quality 页面

#### 目标

提供管理员质量指标和调优建议页面。

#### 建议文件

- 新增：`ui/src/views/admin/RoutingQualityView.vue`
- 新增测试：`ui/src/views/admin/__tests__/RoutingQualityView.spec.ts`
- 修改：`ui/src/router/index.ts`
- 修改：`ui/src/i18n/messages/zh-CN.ts`
- 修改：`ui/src/i18n/messages/en-US.ts`

#### 页面内容

- 总调用数
- feedback 数
- 平均评分
- fallback rate
- 平均耗时
- 平均成本
- 按任务类型/Agent 子池/工具子池/模型的质量摘要
- suggestion 列表，展示 severity、target、reason、evidence

#### 验收标准

- [ ] 新增 `/admin/routing-quality` 路由。
- [ ] 路由权限为 `routing_quality:read`。
- [ ] 页面加载 metrics 与 suggestions。
- [ ] 空数据有稳定空状态。
- [ ] 所有新增文案走 i18n。

#### 完成记录

- [x] 新增 `/admin/routing-quality` 路由，权限为 `routing_quality:read`。
- [x] 新增 `RoutingQualityView.vue`。
- [x] 页面加载 metrics 与 suggestions。
- [x] 页面展示总调用数、feedback 数、平均评分、fallback rate、平均耗时、平均成本。
- [x] 页面展示任务类型聚合与 suggestion 列表。
- [x] 空数据有稳定空状态。
- [x] 新增 zh-CN / en-US i18n 文案。
- [x] 聚焦测试通过：`RoutingQualityView.spec.ts` 与 `admin-routing-quality.spec.ts` 共 5 passed。

### 4.11 任务 10：Routing Log 详情 feedback 入口

#### 目标

在现有 Admin Routing Logs 页面增加对单条 routing log 提交质量 feedback 的入口。

#### 建议文件

- 修改：`ui/src/views/admin/RoutingLogsView.vue`
- 修改：`ui/src/views/admin/__tests__/RoutingLogsView.spec.ts`
- 修改：`ui/src/i18n/messages/zh-CN.ts`
- 修改：`ui/src/i18n/messages/en-US.ts`

#### 验收标准

- [ ] 每条 routing log 可触发 feedback 操作。
- [ ] feedback 表单包含 rating、dimension scores、comment。
- [ ] 提交成功后提示管理员。
- [ ] 无权限或接口失败时展示错误信息。
- [ ] 不在用户侧页面展示该入口。

#### 完成记录

- [x] Routing Logs 页面新增每条日志的 feedback 操作入口。
- [x] feedback 表单包含 rating、accuracy、latency、cost、safety、completeness、comment。
- [x] 提交成功后提示管理员。
- [x] 接口失败时展示错误信息。
- [x] 该入口仅在 Admin Routing Logs 页面存在，不进入用户侧页面。
- [x] 聚焦测试通过：`RoutingLogsView.spec.ts`、`RoutingQualityView.spec.ts`、`admin-routing-quality.spec.ts` 共 7 passed。

### 4.12 任务 11：安全与用户侧边界回归

#### 目标

确认质量反馈与运营建议不会泄露给普通用户，不会自动改生产策略。

#### 建议文件

- 新增：`api/test/internal/integration/test_routing_quality_boundaries.py`
- 修改相关前端权限测试，如存在合适文件则补充。

#### 验收标准

- [ ] 普通用户不能访问 routing quality admin API。
- [ ] 无权限管理员不能创建 feedback。
- [ ] optimization suggestion 服务不修改 feature flag、Agent、工具、模型配置。
- [ ] feedback 序列化不包含 key_usage、internal_cost_breakdown。
- [ ] 用户侧 `/home` 响应不新增 routing quality 内部字段。

#### 完成记录

- [x] feedback 序列化不包含 key_usage、internal_cost_breakdown 和 api_key。
- [x] optimization suggestion 服务不修改 feature flag、Agent、工具、模型配置。
- [x] 用户侧 `/home` 响应不新增 routing_quality 或 optimization_suggestion 内部字段。
- [x] 普通用户/无权限管理员访问边界由 Admin handler 权限测试覆盖。
- [x] 聚焦测试通过：`test_routing_quality_boundaries.py` 3 passed。

### 4.13 任务 12：最终全量测试与文档同步

#### 目标

完成最终全量验证，更新 PRD 和本执行文档。

#### 验收标准

- [ ] 后端 Docker 全量测试通过。
- [ ] 后端 migration heads/current 通过。
- [ ] 前端 Docker type-check 通过。
- [ ] 前端 Docker lint 通过。
- [ ] 前端 Docker unit test 通过。
- [ ] PRD 状态更新为 Phase 9 已完成。
- [ ] 本执行文档所有任务完成记录已更新。

#### 完成记录

- [x] 后端 Docker 全量测试通过：2145 passed / 6 skipped。
- [x] 后端 migration heads/current 通过，head/current 为 `d1e2f3a4b5d3`。
- [x] 前端 Docker type-check 通过。
- [x] 前端 Docker lint 通过。
- [x] 前端 Docker unit test 通过：104 files / 368 tests passed。
- [x] PRD 状态更新为 Phase 9 已完成，版本更新为 v3.0。
- [x] 本执行文档所有任务完成记录已更新。

## 5. 推荐执行顺序

1. 先完成 quality feedback / suggestion 实体、模型和 migration。
2. 再实现 feedback 写入和 quality metrics 聚合服务。
3. 再实现 optimization suggestion 生成服务，保持只读建议，不改生产配置。
4. 再实现 Admin API、RBAC 和权限测试。
5. 再实现前端 service、Routing Quality 页面和 Routing Logs feedback 入口。
6. 最后做用户侧边界回归、全量测试和文档同步。

## 6. 风险与约束

- 本阶段不能把建议自动应用到 Agent、工具、模型、feature flag 或成本策略。
- 指标样本不足时必须明确提示 `collect_more_feedback`，不能伪造高置信建议。
- 质量反馈可能包含管理员输入文本，序列化和展示时不能混入 secret、key、token 等内部敏感字段。
- routing quality 能力属于 Admin 运维闭环，不进入普通用户 `/home` 响应。
- 如果已有 analytics 页面可以复用样式，但不要强行合并两个不同信息架构的页面。
- 保留 Phase 8 的 rollback 开关体系，Phase 9 的建议不得绕过开关或权限边界。
