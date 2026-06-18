# Phase 14：调优建议采纳与策略变更草稿 执行计划

> **目标：** 将 Phase 9 的半自动调优建议从只读建议升级为管理员可复核、可采纳、可生成策略变更草稿的运营闭环。

**架构：** 以 `RoutingOptimizationSuggestionModel` 为核心扩展状态流转（新增 `applied` 状态），新建 `PolicyChangeDraft` 实体存储策略变更草稿（before/after/diff/impact），新建 `RoutingPolicyChangeService` 生成 preview/apply/rollback，复用 `audit_log` 表记录审计。

**技术栈：** Python 3.11 / Flask / SQLAlchemy / Vue 3 / Arco Design Vue

---

## 1. 现状基线

### 已有基础设施（复用）

| 模块 | 状态 | 文件 |
|------|------|------|
| RoutingOptimizationSuggestionModel | 已实现 | `api/internal/model/routing_quality.py` |
| RoutingOptimizationSuggestionService | 已实现（生成建议） | `api/internal/service/routing_optimization_suggestion_service.py` |
| AdminRoutingQualityHandler | 已实现（metrics/suggestions/feedback） | `api/internal/handler/admin_routing_quality_handler.py` |
| RBAC `routing_quality:read` | 已实现 | `api/internal/service/admin_rbac_service.py` |
| audit_log 表 + AuditLogService | 已实现 | `api/internal/model/audit_log.py` |
| migration head | `d1e2f3a4b5d5` | - |

### 关键未闭环点（Phase 14 核心任务）

1. **缺 `applied` 状态** — 状态枚举仅有 `open/accepted/dismissed`，缺 `applied`
2. **无 accept/dismiss API** — 建议无法状态流转
3. **无 PolicyChangeDraft 实体** — 策略变更草稿表完全不存在
4. **无 preview/diff/impact** — 策略变更预览能力未实现
5. **无 apply/rollback** — 策略变更应用与回滚未实现
6. **无策略变更审计** — apply 后不写审计日志
7. **RBAC 权限不足** — 缺 accept/dismiss/apply/rollback 权限码

---

## 2. 文件结构

### 需要修改的文件

| 文件 | 职责 | 改动 |
|------|------|------|
| `api/internal/entity/routing_quality_entity.py` | 实体枚举 | 新增 `applied` 状态 + `dismiss_reason` 字段 |
| `api/internal/model/routing_quality.py` | 持久化模型 | Suggestion 新增 dismiss_reason/applied_by/applied_at/policy_change_draft_id |
| `api/internal/service/routing_optimization_suggestion_service.py` | 建议服务 | 新增 accept/dismiss/apply 方法 |
| `api/internal/handler/admin_routing_quality_handler.py` | handler | 新增 accept/dismiss/preview/apply/rollback/list_drafts |
| `api/internal/schema/admin_routing_quality_schema.py` | schema | 新增请求/响应 schema |
| `api/internal/router/router.py` | 路由 | 注册 6 条新路由 |
| `api/internal/service/admin_rbac_service.py` | RBAC | 新增 4 个权限码 |
| `api/test/internal/router/test_router_full_matrix.py` | 路由测试 | 更新总数 + 矩阵 |

### 需要新建的文件

| 文件 | 职责 |
|------|------|
| `api/internal/migration/versions/d1e2f3a4b5d6_add_policy_change_draft.py` | 新建 policy_change_draft 表 + suggestion 新增列 |
| `api/internal/entity/policy_change_entity.py` | PolicyChangeDraft 实体 |
| `api/internal/service/routing_policy_change_service.py` | 策略变更服务（preview/apply/rollback） |
| `api/test/internal/service/test_routing_policy_change_service.py` | 策略变更服务测试 |
| `api/test/internal/handler/test_admin_routing_quality_suggestion_flow.py` | 建议流转 handler 测试 |

---

## 3. 任务分解

### 任务 0：基线确认

- [ ] 跑后端全量测试 `docker compose exec llmops-api pytest -q --no-cov`，确认 2208 passed
- [ ] 确认 migration head 为 `d1e2f3a4b5d5`

### 任务 1：PolicyChangeDraft 实体 + migration

**Files:**
- Create: `api/internal/migration/versions/d1e2f3a4b5d6_add_policy_change_draft.py`
- Create: `api/internal/entity/policy_change_entity.py`
- Modify: `api/internal/model/routing_quality.py`

- [ ] **Step 1: 创建 migration** - revision `d1e2f3a4b5d6`，down_revision `d1e2f3a4b5d5`
  - 新建 `policy_change_draft` 表（id, suggestion_id, policy_type, target_id, before_config JSONB, after_config JSONB, diff JSONB, impact JSONB, status, applied_by, applied_at, rolled_back_at, created_at, updated_at）
  - `routing_optimization_suggestion` 表新增 `dismiss_reason`、`applied_by`、`applied_at`、`policy_change_draft_id` 列

- [ ] **Step 2: 创建实体** - PolicyChangeDraft dataclass + PolicyChangeStatus 枚举（pending/applied/rolled_back）

- [ ] **Step 3: 更新模型** - RoutingOptimizationSuggestionModel 新增字段 + 新增 PolicyChangeDraftModel

- [ ] **Step 4: 跑 migration 验证**

### 任务 2：建议状态流转服务（accept/dismiss）

**Files:**
- Modify: `api/internal/service/routing_optimization_suggestion_service.py`

- [ ] **Step 1: 扩展状态枚举** - 新增 `applied` 状态

- [ ] **Step 2: 实现 accept_suggestion** - open → accepted

- [ ] **Step 3: 实现 dismiss_suggestion** - open/accepted → dismissed，记录 dismiss_reason

- [ ] **Step 4: 写测试验证状态流转**

### 任务 3：策略变更服务（preview/diff/impact/apply/rollback）

**Files:**
- Create: `api/internal/service/routing_policy_change_service.py`
- Test: `api/test/internal/service/test_routing_policy_change_service.py`

- [ ] **Step 1: 实现 generate_preview** - 根据 suggestion 生成 before/after/diff/impact

- [ ] **Step 2: 实现 apply_draft** - 验证 status=pending → 应用策略 → 写审计日志 → 状态 applied（事务保证原子性）

- [ ] **Step 3: 实现 rollback_draft** - applied → rolled_back，恢复 before_config，写审计

- [ ] **Step 4: 写测试验证 preview/apply/rollback**

### 任务 4：Handler + 路由 + Schema + RBAC

**Files:**
- Modify: `api/internal/handler/admin_routing_quality_handler.py`
- Modify: `api/internal/schema/admin_routing_quality_schema.py`
- Modify: `api/internal/router/router.py`
- Modify: `api/internal/service/admin_rbac_service.py`
- Test: `api/test/internal/handler/test_admin_routing_quality_suggestion_flow.py`

- [ ] **Step 1: 新增 schema** - AcceptReq/DismissReq/PreviewResp/ApplyResp/RollbackResp

- [ ] **Step 2: 新增 RBAC 权限码** - routing_quality:accept/dismiss/apply/rollback

- [ ] **Step 3: 实现 handler 方法** - accept/dismiss/preview/apply/rollback/list_drafts

- [ ] **Step 4: 注册 6 条路由** - POST accept, POST dismiss, GET preview, POST apply, POST rollback, GET policy-changes

- [ ] **Step 5: 更新路由测试矩阵**

- [ ] **Step 6: 写 handler 测试**

### 任务 5：前端策略变更管理

**Files:**
- Modify: `ui/src/views/admin/routing-quality/` 相关页面
- Modify: `ui/src/i18n/messages/zh-CN.ts` + `en-US.ts`

- [ ] **Step 1: 建议列表新增操作按钮** - accept/dismiss/preview

- [ ] **Step 2: 新增 preview 弹窗** - 展示 before/after/diff/impact

- [ ] **Step 3: 新增 apply/rollback 按钮**

- [ ] **Step 4: i18n 完整**

### 任务 6：最终全量测试与文档同步

- [ ] 跑后端全量测试
- [ ] 跑前端全量测试 + type-check + lint
- [ ] 更新 PRD 当前状态为"Phase 1-14 已提交"
- [ ] git commit

---

## 4. 验收标准（对齐 PRD 16.15）

1. 系统不能自动应用建议，必须管理员确认 ✅ apply 接口需手动调用
2. 采纳建议前展示变更 diff 和影响范围 ✅ preview 接口返回 diff + impact
3. 应用后写入审计日志 ✅ apply_draft 调用 AuditLogService
4. 应用失败时不产生部分策略变更 ✅ 事务包裹，异常回滚
5. 管理员可以 dismiss 不适用建议并记录原因 ✅ dismiss 接口 + dismiss_reason

---

## 5. 推荐执行顺序

1. 任务 0：基线确认 ✅（2208 passed, head d1e2f3a4b5d5）
2. 任务 1：PolicyChangeDraft 实体 + migration ✅（head d1e2f3a4b5d6）
3. 任务 2-3：建议状态流转 + 策略变更服务 ✅（10 passed，accept/dismiss/preview/apply/rollback）
4. 任务 4：Handler + 路由 + Schema + RBAC ✅（2224 passed, 278 routes, 6 条新路由）
5. 任务 5：前端策略变更管理 ✅（368 passed）
6. 任务 6：最终全量测试与文档同步 ✅（后端 2224 passed + 前端 368 passed）

## 6. Phase 14 完成状态

### 后端
- 全量测试：2224 passed, 6 skipped, 0 failed（比基线 2208 多 16 个新测试）
- migration heads/current：d1e2f3a4b5d6 (head)
- PolicyChangeDraft 实体 + policy_change_draft 表（migration d1e2f3a4b5d6）
- RoutingOptimizationSuggestionModel 新增 dismiss_reason/applied_by/applied_at/policy_change_draft_id
- 建议状态流转：open → accepted → applied（4 态完整），可 dismiss
- RoutingPolicyChangeService：generate_preview / apply_draft（事务+审计）/ rollback_draft
- 6 条新路由：accept / dismiss / preview / apply / rollback / list_policy_changes
- RBAC 新增 4 个权限码：routing_quality:accept/dismiss/apply/rollback
- apply 失败时事务回滚，不产生部分策略变更
- apply/rollback 写入 audit_log

### 前端
- 全量测试：368 passed
- type-check：0 errors
- lint：0 errors
- 新增 /admin/routing-quality/suggestions 页面（建议列表 + 采纳/驳回/预览/应用）
- 预览弹窗展示 before/after/diff/impact
- i18n 完整（中英文，policyChange 段落）

### 验收标准达成
1. ✅ 系统不能自动应用建议，必须管理员确认（apply 需手动调用）
2. ✅ 采纳建议前展示变更 diff 和影响范围（preview 接口返回 diff + impact）
3. ✅ 应用后写入审计日志（apply_draft 调用 AuditLogService）
4. ✅ 应用失败时不产生部分策略变更（事务包裹，异常回滚）
5. ✅ 管理员可以 dismiss 不适用建议并记录原因（dismiss 接口 + dismiss_reason）
