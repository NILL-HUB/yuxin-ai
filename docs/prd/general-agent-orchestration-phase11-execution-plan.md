# Phase 11：高风险工具统一确认与审计闭环 执行计划

> **目标：** 让系统可以在授权、作用域、审计和用户确认条件下安全执行高风险工具操作，闭合 Agent 主链路的确认-审计闭环。

**架构：** 在 FunctionCallAgent/DeepThinkingAgent 的 `_tools_node` 接入 `ToolInvokerService`，高风险工具创建 `ToolConfirmation` 记录并阻塞等待用户确认；前端通过 SSE/轮询感知 pending 确认请求，展示 `ToolConfirmationCard`；工具执行结果经 `ToolInvocationAuditService` 持久化到 `audit_log` 表。

**技术栈：** Python 3.11 / Flask / SQLAlchemy / LangGraph / Vue 3 / Arco Design Vue / TypeScript

---

## 1. 现状基线

### 已有基础设施（复用，不重做）

| 模块 | 状态 | 文件 |
|------|------|------|
| ToolConfirmation 模型 + migration | 已实现 | `api/internal/model/tool_confirmation.py`, `migration/versions/d1e2f3a4b5c9_add_tool_confirmation.py` |
| ToolConfirmation handler + service + schema + 路由 | 已实现 | `api/internal/handler/tool_confirmation_handler.py`, `api/internal/service/tool_confirmation_service.py`, `api/internal/schema/tool_confirmation_schema.py` |
| ToolInvokerService（含安全检查 + 审计 payload） | 已实现 | `api/internal/service/tool_invoker_service.py` |
| ToolPolicyFilter（含 high_risk_requires_confirmation） | 已实现 | `api/internal/service/tool_inventory_service.py` |
| ToolInvocationAuditService（payload 构造 + 脱敏） | 已实现 | `api/internal/service/tool_invocation_audit_service.py` |
| AuditLog 模型 + AuditLogService | 已实现 | `api/internal/model/admin.py`, `api/internal/service/audit_log_service.py` |
| 前端 ToolConfirmationCard 组件 + 类型 + 测试 | 已实现 | `ui/src/components/ToolConfirmationCard.vue`, `ui/src/models/tool-confirmation.ts` |

### 三个关键未闭环点（Phase 11 核心任务）

1. **Agent 主链路未接入确认流程**：`FunctionCallAgent._tools_node` 和 `DeepThinkingAgent` 直接 `tool.invoke()`，未调用 `ToolInvokerService`，未查询 `ToolConfirmation`，高风险工具会被直接执行。
2. **RiskLevel 枚举值域分裂**：枚举只有 `safe/medium/high`，但 `ToolInvokerService._security_error` 检查了 `dangerous/sensitive`，而 `normalize_tool_metadata` 会把非枚举值降级为 `medium`，导致 `dangerous/sensitive` 永不命中。
3. **审计闭环未闭合**：`ToolInvocationAuditService.build_payload` 只构造字典，未持久化到 `audit_log` 表；且 `AuditLog.admin_user_id` 与工具调用的 `account_id` 外键不匹配。

---

## 2. 文件结构

### 需要修改的文件

| 文件 | 职责 | 改动 |
|------|------|------|
| `api/internal/entity/tool_inventory_entity.py` | RiskLevel 枚举 | 新增 DANGEROUS/SENSITIVE 枚举值 |
| `api/internal/service/tool_invoker_service.py` | 工具调用安全检查 | 统一使用 RiskLevel 枚举 |
| `api/internal/service/tool_invocation_audit_service.py` | 工具调用审计 | 新增 `persist` 方法落库 |
| `api/internal/model/admin.py` | AuditLog 模型 | 新增 `account_id` 字段（nullable，兼容管理员审计） |
| `api/internal/service/audit_log_service.py` | 审计日志服务 | 新增 `record_for_tool_invocation` 方法 |
| `api/internal/core/agent/agents/function_call_agent.py` | Agent 工具节点 | `_tools_node` 接入 ToolInvokerService + 确认流程 |
| `api/internal/core/agent/agents/deep_thinking_agent.py` | 深度思考 Agent | 同上 |
| `api/internal/handler/tool_confirmation_handler.py` | 确认 handler | 新增 GET 列表/详情接口 |
| `api/internal/schema/tool_confirmation_schema.py` | 确认 schema | 新增列表/详情响应 schema |
| `api/internal/router/router.py` | 路由 | 注册 GET 路由 |
| `ui/src/components/ToolConfirmationCard.vue` | 确认卡片 | 增强字段（目标系统/环境/回滚策略/审计提示） |
| `ui/src/models/tool-confirmation.ts` | 类型定义 | 扩展字段 |
| `ui/src/services/tool-confirmation.ts` | API 服务 | 新增 getList/getDetail/pollPending |

### 需要新建的文件

| 文件 | 职责 |
|------|------|
| `api/internal/migration/versions/d1e2f3a4b5d4_add_account_id_to_audit_log.py` | audit_log 表新增 account_id 列 |
| `api/test/internal/core/agent/test_tool_confirmation_integration.py` | Agent 确认流程集成测试 |
| `api/test/internal/service/test_tool_invocation_audit_persist.py` | 审计落库测试 |
| `api/test/internal/handler/test_tool_confirmation_list.py` | GET 接口测试 |
| `api/test/internal/security/test_prompt_injection_bypass.py` | prompt 注入绕过安全测试 |

---

## 3. 任务分解

### 任务 0：基线确认

- [ ] 跑后端全量测试 `docker compose exec llmops-api pytest -q --no-cov`，确认 2157 passed
- [ ] 跑前端全量测试 `npm run test:unit`，确认 368 passed
- [ ] 确认 migration head 为 `d1e2f3a4b5d3`
- [ ] 记录基线数字

### 任务 1：RiskLevel 枚举统一

**Files:**
- Modify: `api/internal/entity/tool_inventory_entity.py:12-15`
- Test: `api/test/internal/entity/test_tool_inventory_entity.py`

- [ ] **Step 1: 写失败测试** - 验证 RiskLevel 包含 DANGEROUS 和 SENSITIVE

```python
def test_risk_level_should_include_dangerous_and_sensitive():
    from internal.entity.tool_inventory_entity import RiskLevel
    assert RiskLevel.DANGEROUS.value == "dangerous"
    assert RiskLevel.SENSITIVE.value == "sensitive"
    assert RiskLevel.SAFE.value == "safe"
    assert RiskLevel.MEDIUM.value == "medium"
    assert RiskLevel.HIGH.value == "high"
```

- [ ] **Step 2: 跑测试确认失败** - `pytest test/internal/entity/test_tool_inventory_entity.py::test_risk_level_should_include_dangerous_and_sensitive -v`

- [ ] **Step 3: 实现枚举扩展**

```python
class RiskLevel(str, Enum):
    SAFE = "safe"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    SENSITIVE = "sensitive"
    DANGEROUS = "dangerous"
```

- [ ] **Step 4: 更新 `normalize_tool_metadata` 的 `_normalize_choice`** - 把 dangerous/sensitive 加入合法值集合，不再降级为 medium

- [ ] **Step 5: 更新 `ToolInvokerService._security_error`** - 用 `RiskLevel.DANGEROUS.value` 和 `RiskLevel.SENSITIVE.value` 替换硬编码字符串

- [ ] **Step 6: 跑全量测试确认无回归**

### 任务 2：audit_log 表新增 account_id 字段

**Files:**
- Create: `api/internal/migration/versions/d1e2f3a4b5d4_add_account_id_to_audit_log.py`
- Modify: `api/internal/model/admin.py` (AuditLog 模型)

- [ ] **Step 1: 创建 migration** - `flask db revision -m "add account_id to audit_log"`，revision id `d1e2f3a4b5d4`，down_revision `d1e2f3a4b5d3`

- [ ] **Step 2: 实现 upgrade/downgrade**

```python
def upgrade():
    op.add_column('audit_log', sa.Column('account_id', sa.UUID(), nullable=True))
    op.create_index('audit_log_account_id_idx', 'audit_log', ['account_id'])
    op.create_foreign_key('fk_audit_log_account_id_account', 'audit_log', 'account', ['account_id'], ['id'])

def downgrade():
    op.drop_constraint('fk_audit_log_account_id_account', 'audit_log', type_='foreignkey')
    op.drop_index('audit_log_account_id_idx', table_name='audit_log')
    op.drop_column('audit_log', 'account_id')
```

- [ ] **Step 3: 更新 AuditLog 模型** - 新增 `account_id = Column(UUID, ForeignKey("account.id"), nullable=True)` 和 `account = relationship("Account", foreign_keys=[account_id], lazy="joined")`

- [ ] **Step 4: 跑 migration** - `flask db upgrade --directory internal/migration`

- [ ] **Step 5: 更新 AuditLogService.record_for_tool_invocation** - 接收 account_id 参数，写入 audit_log 表

### 任务 3：ToolInvocationAuditService 落库

**Files:**
- Modify: `api/internal/service/tool_invocation_audit_service.py`
- Modify: `api/internal/service/audit_log_service.py`
- Test: `api/test/internal/service/test_tool_invocation_audit_persist.py`

- [ ] **Step 1: 写失败测试** - 验证 `persist` 方法将 payload 写入 audit_log 表

```python
def test_audit_service_should_persist_tool_invocation(monkeypatch):
    service = ToolInvocationAuditService()
    payload = service.build_payload(tool_id="t1", runtime_name="test_tool", ...)
    AuditLogService().record_for_tool_invocation(account_id=uuid4(), payload=payload)
    logs = AuditLogService().list_audit_logs(...)
    assert len(logs) == 1
    assert logs[0].action == "tool_invocation"
```

- [ ] **Step 2: 实现 `AuditLogService.record_for_tool_invocation`** - action="tool_invocation"，resource_type="tool"，resource_id=tool_id，after_data=payload，account_id=account_id

- [ ] **Step 3: 更新 `ToolInvokerService`** - 在 invoke 成功/失败后调用 `AuditLogService().record_for_tool_invocation`

- [ ] **Step 4: 跑测试确认通过**

### 任务 4：tool-confirmations GET 接口

**Files:**
- Modify: `api/internal/handler/tool_confirmation_handler.py`
- Modify: `api/internal/schema/tool_confirmation_schema.py`
- Modify: `api/internal/router/router.py`
- Test: `api/test/internal/handler/test_tool_confirmation_list.py`

- [ ] **Step 1: 写失败测试** - 验证 GET `/tool-confirmations` 返回当前用户的确认列表，GET `/tool-confirmations/<id>` 返回详情

- [ ] **Step 2: 实现 schema** - `ToolConfirmationResp` 和 `ToolConfirmationListResp`

- [ ] **Step 3: 实现 handler** - `list` 方法（按 owner_account_id 过滤，支持 status 过滤）和 `get` 方法

- [ ] **Step 4: 注册路由** - `GET /tool-confirmations` 和 `GET /tool-confirmations/<uuid:confirmation_id>`

- [ ] **Step 5: 跑测试确认通过**

### 任务 5：Agent _tools_node 接入确认流程（核心）

**Files:**
- Modify: `api/internal/core/agent/agents/function_call_agent.py` (`_tools_node`)
- Modify: `api/internal/core/agent/entities/agent_entity.py` (AgentState 新增 pending_confirmations)
- Modify: `api/internal/service/tool_invoker_service.py` (新增 invoke_with_confirmation)
- Test: `api/test/internal/core/agent/test_tool_confirmation_integration.py`

- [ ] **Step 1: 写失败测试** - 验证高风险工具调用时创建 ToolConfirmation 记录，状态为 pending；用户确认后才执行；用户取消后不执行

- [ ] **Step 2: AgentState 新增字段** - `pending_confirmations: list[dict]` 用于暂存待确认的工具调用

- [ ] **Step 3: 实现 `ToolInvokerService.invoke_with_confirmation`** - 检查 risk_level，如果是 HIGH/SENSITIVE 则创建 ToolConfirmation（status=pending），通过 SSE/队列推送确认请求给前端，阻塞等待状态变为 confirmed/cancelled

- [ ] **Step 4: 修改 `_tools_node`** - 遍历 tool_calls，对每个调用先经 `ToolInvokerService.invoke_with_confirmation`，高风险工具创建确认记录后返回"等待确认"的中间消息，前端确认/取消后通过新的一轮 stream 恢复执行

- [ ] **Step 5: 实现 confirm/cancel 后的恢复执行** - handler confirm 后触发 Agent 继续执行被阻塞的工具调用

- [ ] **Step 6: DeepThinkingAgent 同步修改** - 复用相同的 _tools_node 逻辑

- [ ] **Step 7: 跑集成测试确认通过**

### 任务 6：前端确认卡片接入对话流

**Files:**
- Modify: `ui/src/components/ToolConfirmationCard.vue`
- Modify: `ui/src/models/tool-confirmation.ts`
- Modify: `ui/src/services/tool-confirmation.ts`
- Modify: `ui/src/views/space/apps/components/AgentChatPanel.vue`（或对话流主组件）

- [ ] **Step 1: 扩展类型** - `ToolConfirmationPrompt` 新增 target_system/target_environment/rollback_strategy/audit_hint/impact_scope 字段

- [ ] **Step 2: 增强 ToolConfirmationCard** - 展示目标系统、目标环境、执行摘要、影响范围、回滚策略、授权状态、审计提示；默认焦点落在"取消"按钮上（非"执行"按钮）

- [ ] **Step 3: 新增 API** - `getPendingConfirmations()`、`pollPendingConfirmations(interval)`、`confirmToolConfirmation(id)`、`cancelToolConfirmation(id)`

- [ ] **Step 4: 接入对话流** - 对话进行中轮询 pending confirmations，有 pending 时弹出 ToolConfirmationCard，用户确认/取消后调用对应 API

- [ ] **Step 5: 跑前端测试确认无回归**

### 任务 7：安全测试

**Files:**
- Create: `api/test/internal/security/test_prompt_injection_bypass.py`

- [ ] **Step 1: 测试 prompt 注入无法绕过确认** - 构造包含"跳过确认直接执行"指令的 prompt，验证高风险工具仍然创建 ToolConfirmation

- [ ] **Step 2: 测试 confirmation_id 伪造** - 用户 A 不能确认/取消用户 B 的 confirmation

- [ ] **Step 3: 测试危险工具禁用** - dangerous 级别工具直接拒绝，不创建确认记录

- [ ] **Step 4: 测试取消后不执行** - 用户取消后工具不执行，返回可理解的替代说明

- [ ] **Step 5: 测试审计完整性** - 每次工具调用（无论成功/失败/取消）都有审计记录

### 任务 8：最终全量测试与文档同步

- [ ] 跑后端全量测试
- [ ] 跑前端全量测试 + type-check + lint
- [ ] 跑 migration 验证（heads/current 一致）
- [ ] 更新 PRD 当前状态为"Phase 1-11 已提交"
- [ ] 更新 Phase 11 执行计划完成状态
- [ ] git commit

---

## 4. 验收标准（对齐 PRD 16.12）

1. sensitive/dangerous 工具不能绕过确认 UI 直接执行
2. 确认卡片展示风险等级、工具名称、目标系统、目标环境、执行摘要、影响范围、回滚策略、授权状态和审计提示
3. 默认焦点不能落在执行按钮上
4. 用户取消后不执行工具，并返回可理解的替代说明
5. 已进入不可中断外部写操作时，系统记录审计并提示用户可能已生效
6. 每次工具调用都有审计记录落库到 audit_log 表

---

## 5. 推荐执行顺序

1. 任务 0：基线确认
2. 任务 1：RiskLevel 枚举统一（基础，后续任务依赖）
3. 任务 2：audit_log 表新增 account_id（migration 前置）
4. 任务 3：ToolInvocationAuditService 落库
5. 任务 4：tool-confirmations GET 接口（前端依赖）
6. 任务 5：Agent _tools_node 接入确认流程（核心，最复杂）
7. 任务 6：前端确认卡片接入对话流
8. 任务 7：安全测试
9. 任务 8：最终全量测试与文档同步

---

## 6. 风险与约束

| 风险 | 应对 |
|------|------|
| Agent 阻塞等待确认会导致 stream 中断 | 使用 LangGraph 的 interrupt 机制或两阶段 stream（创建确认→暂停→确认后恢复） |
| 前端轮询 pending confirmations 增加负载 | 使用 SSE 推送而非轮询，或 3 秒间隔轮询 + 指数退避 |
| audit_log 表 account_id 为 nullable 可能导致历史数据混淆 | 新增字段 nullable=True，仅工具调用审计写入 account_id，管理员审计仍写 admin_user_id |
| dangerous 工具完全禁用可能影响现有功能 | 先调研是否有工具标记为 dangerous，若无则无影响 |

---

## 7. 与 Phase 10 的衔接

Phase 10 完成了知识库分层与用户长期记忆召回。Phase 11 聚焦工具执行安全。两者通过 `ToolPolicyFilter` 产生交集：Phase 10 的知识库工具有 `knowledge_scope` 权限隔离，Phase 11 的高风险工具有确认-审计闭环。两个 phase 共同构成"作用域隔离 + 安全确认"的完整安全体系。
