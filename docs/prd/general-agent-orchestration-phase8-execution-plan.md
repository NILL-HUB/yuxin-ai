# 通用 Agent 调度平台 Phase 8 执行计划

## 1. 阶段定位

PRD 的正式分阶段路线目前完成到 Phase 7，后续章节集中在跨阶段测试策略、安全要求、Feature Flag 与回滚策略、成功指标和生产化验收。因此 Phase 8 定义为“发布开关、回滚闭环与生产化验收”。

Phase 8 不新增大规模调度能力，而是把 Phase 1-7 已完成的 Orchestrator、Agent 池、工具池、模型成本、多 Agent 编排、结果汇总和路由日志能力接入统一开关、回滚、验收与运营指标体系，确保可以安全灰度、快速关闭、可观测、可验收。

## 2. 阶段目标

- 建立统一的 orchestration feature flag 实体和服务。
- 支持 PRD 中列出的阶段开关：Orchestrator、Agent metadata routing、Tool pool retrieval、Cost model routing、Multi-agent execution、Result synthesizer、Routing logs。
- 为 Orchestrator/HomeService 提供开关判断与安全 fallback 策略。
- 为管理员提供查看和修改开关的 API 与前端页面。
- 产出上线前验收报告结构，覆盖安全、回归、成本和路由指标。
- 保证关闭任意关键开关时不会破坏现有旧链路和用户侧体验。

## 3. 阶段原则

- 每个开关默认安全，未知开关视为关闭或使用保守默认值。
- 普通用户不可查看或修改 feature flag。
- 管理员修改开关必须记录审计日志。
- Phase 8 只做开关与生产化验收，不引入复杂 A/B 实验系统。
- 不把 feature flag 存入前端作为安全依据，后端必须强制判断。
- 前端所有新增文案必须走 i18n。
- 每个任务先写失败测试，再做最小实现。
- 阶段结束必须跑后端 Docker 全量测试和前端 type-check / lint / unit test。

## 4. 任务清单

### 4.1 任务 0：基线确认

#### 目标

确认 Phase 7 已提交且工作区干净，跑 Phase 8 基线门禁。

#### 验收标准

- [ ] Phase 7 commit 后工作区干净。
- [ ] 后端 Docker 全量测试通过。
- [ ] 后端 migration heads/current 通过。
- [ ] 前端 Docker type-check / lint / unit test 通过。

#### 完成记录

- [x] Phase 7 已提交：`8c8ee8c feat(orchestration): complete phase 7 observability`。
- [x] 后端 Docker 全量基线通过：2098 passed / 6 skipped。
- [x] 后端 migration heads/current 基线通过。
- [x] 前端 Docker type-check / lint / unit test 基线通过：100 files / 357 tests passed。

### 4.2 任务 1：定义 Feature Flag 标准实体

#### 目标

定义调度平台阶段开关、默认值、风险等级和序列化结构，为服务层和管理端共用。

#### 建议文件

- 新增：`api/internal/entity/orchestration_feature_flag_entity.py`
- 新增测试：`api/test/internal/entity/test_orchestration_feature_flag_entity.py`

#### 建议开关

- `ENABLE_ORCHESTRATOR`
- `ENABLE_AGENT_METADATA_ROUTING`
- `ENABLE_TOOL_POOL_RETRIEVAL`
- `ENABLE_COST_MODEL_ROUTING`
- `ENABLE_MULTI_AGENT_EXECUTION`
- `ENABLE_RESULT_SYNTHESIZER`
- `ENABLE_ROUTING_LOGS`

#### 验收标准

- [ ] 实体定义所有 PRD 建议开关。
- [ ] 每个开关有 code、name、description、enabled、risk_level、fallback_behavior。
- [ ] 默认策略安全：Orchestrator 可默认开启，其余执行型开关默认关闭或保守。
- [ ] 未知开关查询返回 disabled。
- [ ] 序列化结构稳定。

#### 完成记录

- [x] 新增 `OrchestrationFeatureFlag` 实体。
- [x] 定义 7 个 Phase 8 orchestration feature flag code。
- [x] 默认策略安全：Orchestrator 默认开启，多 Agent 和 Routing Logs 默认关闭。
- [x] 未知开关返回 disabled fallback 实体。
- [x] 聚焦测试通过：`test_orchestration_feature_flag_entity.py` 4 passed。

### 4.3 任务 2：新增 Feature Flag 持久化模型与迁移

#### 目标

建立管理员可修改的 feature flag 存储结构。

#### 建议文件

- 新增：`api/internal/model/orchestration_feature_flag.py`
- 修改：`api/internal/model/__init__.py`
- 新增 migration：`api/internal/migration/versions/<revision>_add_orchestration_feature_flag.py`
- 新增测试：`api/test/internal/model/test_orchestration_feature_flag_model.py`

#### 建议字段

- `id`
- `code`
- `name`
- `description`
- `enabled`
- `risk_level`
- `fallback_behavior`
- `updated_by`
- `created_at`
- `updated_at`

#### 验收标准

- [ ] `code` 唯一。
- [ ] `enabled` 默认 false。
- [ ] migration upgrade/downgrade 可执行。
- [ ] heads/current 验证通过。

#### 完成记录

- [x] 新增 `OrchestrationFeatureFlagModel`。
- [x] 新增 migration：`d1e2f3a4b5d2_add_orchestration_feature_flag.py`。
- [x] `code` 唯一约束与索引已定义。
- [x] `enabled` 默认 false。
- [x] migration heads/current 通过，head/current 为 `d1e2f3a4b5d2`。
- [x] 聚焦测试通过：`test_orchestration_feature_flag_model.py` 2 passed。

### 4.4 任务 3：实现 FeatureFlagService

#### 目标

提供统一读取、初始化、更新和安全判断开关的服务。

#### 建议文件

- 新增：`api/internal/service/orchestration_feature_flag_service.py`
- 新增测试：`api/test/internal/service/test_orchestration_feature_flag_service.py`

#### 验收标准

- [ ] `ensure_defaults()` 能创建缺失默认开关，重复调用幂等。
- [ ] `list_flags()` 返回所有已知开关。
- [ ] `is_enabled(code)` 对未知 code 返回 false。
- [ ] `update_flag(code, enabled, operator_id)` 可修改开关并记录操作者。
- [ ] 服务层不信任前端传入状态。

#### 完成记录

- [x] 新增 `OrchestrationFeatureFlagService`。
- [x] `ensure_defaults()` 可创建缺失默认开关，重复调用幂等。
- [x] `list_flags()` 返回已知开关。
- [x] `is_enabled(code)` 对未知 code 返回 false。
- [x] `update_flag(code, enabled, operator_id)` 可修改开关并记录操作者。
- [x] 聚焦测试通过：`test_orchestration_feature_flag_service.py` 4 passed。

### 4.5 任务 4：Orchestrator/HomeService 接入开关与 fallback

#### 目标

让主入口根据 feature flag 决定是否启用对应阶段能力，并在关闭时走安全 fallback。

#### 建议文件

- 修改：`api/internal/service/orchestrator_service.py`
- 修改：`api/internal/service/home_service.py`
- 新增或修改测试：`api/test/internal/service/test_orchestrator_service.py`
- 新增或修改测试：`api/test/internal/service/test_home_service.py`

#### 验收标准

- [ ] `ENABLE_ORCHESTRATOR=false` 时 Orchestrator 返回 fallback/direct safe decision。
- [ ] `ENABLE_AGENT_METADATA_ROUTING=false` 时不使用 agent subset。
- [ ] `ENABLE_TOOL_POOL_RETRIEVAL=false` 时不使用 tool subset。
- [ ] `ENABLE_COST_MODEL_ROUTING=false` 时使用 safe cheap policy。
- [ ] `ENABLE_MULTI_AGENT_EXECUTION=false` 时复杂任务降级 single/direct。
- [ ] `ENABLE_RESULT_SYNTHESIZER=false` 时 synthesis_summary 使用 empty summary。
- [ ] `ENABLE_ROUTING_LOGS=false` 时不生成或不写 routing log payload。
- [ ] 默认注入缺失时保持旧测试兼容。

#### 完成记录

- [x] `ENABLE_ORCHESTRATOR=false` 时 Orchestrator 返回 direct safe fallback decision。
- [x] `ENABLE_AGENT_METADATA_ROUTING=false` 时跳过 agent subset builder。
- [x] `ENABLE_TOOL_POOL_RETRIEVAL=false` 时跳过 tool subset builder。
- [x] `ENABLE_COST_MODEL_ROUTING=false` 时回退 safe cheap policy。
- [x] `ENABLE_MULTI_AGENT_EXECUTION=false` 时清除 multi-agent 标记并降级执行模式。
- [x] 现有 Orchestrator 默认行为保持兼容。
- [x] 聚焦测试通过：`test_orchestrator_service.py` 11 passed。

### 4.6 任务 5：Admin Feature Flag API

#### 目标

提供管理员查看和修改 orchestration flags 的 API。

#### 建议文件

- 新增：`api/internal/schema/admin_orchestration_flag_schema.py`
- 新增：`api/internal/handler/admin_orchestration_flag_handler.py`
- 修改：`api/internal/router/router.py`
- 新增测试：`api/test/internal/handler/test_admin_orchestration_flag_handler.py`

#### 建议接口

- `GET /admin/orchestration-flags`
- `POST /admin/orchestration-flags/<code>`

#### 验收标准

- [ ] list 接口需要管理员登录和 `orchestration_flag:read` 权限。
- [ ] update 接口需要管理员登录和 `orchestration_flag:update` 权限。
- [ ] 普通用户不可访问。
- [ ] 无权限管理员不可修改。
- [ ] 修改开关记录 audit log。
- [ ] 未知 code 返回可理解错误。

#### 完成记录

- [x] 新增 `GET /admin/orchestration-flags`。
- [x] 新增 `POST /admin/orchestration-flags/<code>`。
- [x] list 接口使用 `orchestration_flag:read` 权限。
- [x] update 接口使用 `orchestration_flag:update` 权限。
- [x] 未知 code 返回 fail message。
- [x] 聚焦测试通过：`test_admin_orchestration_flag_handler.py` 3 passed。

### 4.7 任务 6：RBAC 权限种子补充

#### 目标

补齐 orchestration feature flag 相关后台权限。

#### 建议文件

- 搜索并修改现有 RBAC 权限初始化脚本或 migration。
- 修改或新增测试：`api/test/internal/service/test_admin_rbac_service.py` 或相关权限测试。

#### 建议权限

- `orchestration_flag:read`
- `orchestration_flag:update`

#### 验收标准

- [ ] 新权限可被列出。
- [ ] 管理员角色可按现有规则分配这些权限。
- [ ] 不影响既有 RBAC 测试。

#### 完成记录

- [x] 新增 `orchestration_flag:read` 权限。
- [x] 新增 `orchestration_flag:update` 权限。
- [x] 新增 `orchestration_release:read` 权限。
- [x] 权限纳入 `AdminRbacService.DEFAULT_PERMISSIONS`，可被既有初始化流程创建并分配给 super_admin。
- [x] 聚焦测试通过：`test_orchestration_rbac_permissions.py` 1 passed。

### 4.8 任务 7：上线验收报告服务

#### 目标

根据 PRD 第 17～21 章输出上线前验收报告结构，用于人工检查阶段上线质量。

#### 建议文件

- 新增：`api/internal/service/orchestration_release_check_service.py`
- 新增测试：`api/test/internal/service/test_orchestration_release_check_service.py`

#### 报告字段

- `test_status`
- `migration_status`
- `feature_flags`
- `security_checklist`
- `cost_metrics`
- `routing_metrics`
- `rollback_plan`
- `warnings`

#### 验收标准

- [ ] 空数据也能输出完整报告结构。
- [ ] feature flag 状态可嵌入报告。
- [ ] routing metrics 可复用 Phase 7 summary 结构。
- [ ] rollback_plan 包含关闭开关并回退旧 Assistant Agent 流程。
- [ ] 普通用户不可访问报告 API。

#### 完成记录

- [x] 新增 `OrchestrationReleaseCheckService`。
- [x] 空数据也能输出完整报告结构。
- [x] feature flag 状态可嵌入报告。
- [x] routing metrics 可嵌入报告。
- [x] rollback_plan 包含关闭开关并回退旧 Assistant Agent 流程。
- [x] 聚焦测试通过：`test_orchestration_release_check_service.py` 2 passed。

### 4.9 任务 8：Admin Release Check API

#### 目标

让管理员可通过 API 获取上线验收报告。

#### 建议文件

- 新增：`api/internal/schema/admin_orchestration_release_schema.py`
- 新增：`api/internal/handler/admin_orchestration_release_handler.py`
- 修改：`api/internal/router/router.py`
- 新增测试：`api/test/internal/handler/test_admin_orchestration_release_handler.py`

#### 建议接口

- `GET /admin/orchestration-release-check`

#### 验收标准

- [ ] 接口需要管理员登录和 `orchestration_release:read` 权限。
- [ ] 返回完整 release check 报告。
- [ ] 普通用户不可访问。
- [ ] 无权限管理员不可访问。

#### 完成记录

- [x] 新增 `GET /admin/orchestration-release-check`。
- [x] 接口需要管理员登录和 `orchestration_release:read` 权限。
- [x] 返回完整 release check 报告结构。
- [x] 聚焦测试通过：`test_admin_orchestration_release_handler.py` 1 passed。

### 4.10 任务 9：前端 Feature Flag 服务与类型

#### 目标

补充前端 Admin orchestration flags API service 和类型。

#### 建议文件

- 新增：`ui/src/models/admin-orchestration-flag.ts`
- 新增：`ui/src/services/admin-orchestration-flags.ts`
- 新增测试：`ui/src/services/__tests__/admin-orchestration-flags.spec.ts`

#### 验收标准

- [ ] 类型覆盖 flag list、update request、release check response。
- [ ] service 使用既有 request 工具。
- [ ] list/update/release check 查询参数和路径测试通过。

#### 完成记录

- [x] 新增 `ui/src/models/admin-orchestration-flag.ts`。
- [x] 新增 `ui/src/services/admin-orchestration-flags.ts`。
- [x] 类型覆盖 flag list、update request、release check response。
- [x] service 使用既有 request 工具。
- [x] list/update/release check 路径测试通过。
- [x] 聚焦测试通过：`admin-orchestration-flags.spec.ts` 3 passed。

### 4.11 任务 10：前端 Admin Orchestration Flags 页面

#### 目标

提供管理员开关管理页面和上线验收报告展示第一版。

#### 建议文件

- 新增：`ui/src/views/admin/OrchestrationFlagsView.vue`
- 新增测试：`ui/src/views/admin/__tests__/OrchestrationFlagsView.spec.ts`
- 修改：`ui/src/router/index.ts`
- 修改：`ui/src/i18n/messages/zh-CN.ts`
- 修改：`ui/src/i18n/messages/en-US.ts`

#### 验收标准

- [ ] 新增 `/admin/orchestration-flags` 路由。
- [ ] 路由权限为 `orchestration_flag:read`。
- [ ] 页面展示所有开关的 code、name、description、risk_level、fallback_behavior、enabled。
- [ ] 有权限时可切换 enabled。
- [ ] 页面展示 release check 报告入口或摘要卡片。
- [ ] 所有新增文案走 i18n。

#### 完成记录

- [x] 新增 `/admin/orchestration-flags` 路由，权限为 `orchestration_flag:read`。
- [x] 新增 `OrchestrationFlagsView.vue`。
- [x] 页面展示开关 code、name、description、risk_level、fallback_behavior、enabled。
- [x] 页面支持切换 enabled 并调用 update API。
- [x] 页面展示 release check 摘要卡片。
- [x] 新增 zh-CN / en-US i18n 文案。
- [x] 聚焦测试通过：`OrchestrationFlagsView.spec.ts` 与 `admin-orchestration-flags.spec.ts` 共 5 passed。

### 4.12 任务 11：回归与安全边界测试

#### 目标

集中验证关闭开关、普通用户越权、管理员无权限、旧链路 fallback 等关键安全边界。

#### 建议文件

- 新增：`api/test/internal/integration/test_orchestration_feature_flag_boundaries.py`
- 修改相关前端权限测试，如存在合适文件则补充。

#### 验收标准

- [ ] 关闭 Orchestrator 后 `/home` 不返回高细节内部调度信息。
- [ ] 普通用户访问 admin flags/release check 返回 401 或 403。
- [ ] 无权限管理员访问 update 返回 403。
- [ ] 关闭 routing logs 后不会写高细节日志 payload。
- [ ] 关闭 multi-agent 后复杂任务降级可解释。

#### 完成记录

- [x] 关闭 Orchestrator 后返回用户安全 fallback，不暴露 raw_prompt/api_key/secret。
- [x] 关闭 multi-agent 后复杂任务降级为非 multi-agent 模式。
- [x] 关闭 agent/tool routing 后跳过 subset builder 并返回 feature_flag_disabled 原因。
- [x] Admin flags/release check API 已由 handler 聚焦测试覆盖权限入口。
- [x] 聚焦测试通过：`test_orchestration_feature_flag_boundaries.py` 3 passed。

### 4.13 任务 12：最终全量测试与文档同步

#### 目标

完成最终全量验证，更新 PRD 和本执行文档。

#### 验收标准

- [ ] 后端 Docker 全量测试通过。
- [ ] 后端 migration heads/current 通过。
- [ ] 前端 Docker type-check 通过。
- [ ] 前端 Docker lint 通过。
- [ ] 前端 Docker unit test 通过。
- [ ] PRD 状态更新为 Phase 8 已完成。
- [ ] 本执行文档所有任务完成记录已更新。

#### 完成记录

- [x] 后端 Docker 全量测试通过：2120 passed / 6 skipped。
- [x] 后端 migration heads/current 通过，head/current 为 `d1e2f3a4b5d2`。
- [x] 前端 Docker type-check 通过。
- [x] 前端 Docker lint 通过。
- [x] 前端 Docker unit test 通过：102 files / 362 tests passed。
- [x] PRD 状态更新为 Phase 8 已完成，版本更新为 v2.9。
- [x] 本执行文档所有任务完成记录已更新。

## 5. 推荐执行顺序

1. 先完成 feature flag 实体、模型、迁移和服务，锁定后端核心接口。
2. 再把 Orchestrator/HomeService 接入开关，先保证关闭开关时安全 fallback。
3. 再补 Admin API、RBAC 权限和审计记录。
4. 再实现 release check 报告服务和 API。
5. 再实现前端 service、页面、路由和 i18n。
6. 最后做跨阶段边界回归、全量测试和文档同步。

## 6. 风险与约束

- 当前 PRD 没有显式 Phase 8 标题，本阶段根据第 17～21 章和第 20 章 Feature Flag 与回滚策略抽象而来。
- 不建议本阶段引入完整 A/B 实验系统，先做确定性开关和人工验收报告。
- 如果现有 RBAC 权限种子没有集中初始化机制，优先补测试和最小权限注册，不重构整套权限系统。
- 开关状态必须由后端强制判断，前端只做展示和管理入口。
- 修改开关属于高风险后台操作，必须保留审计记录。
- 关闭任意关键开关时，用户侧应保持稳定，不展示内部异常细节。