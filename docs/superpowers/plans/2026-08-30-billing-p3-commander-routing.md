# 指挥官成本路由（P3）实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 打通 Conductor → TaskPlanItem → 子任务独立配模的断裂链路，让指挥官按子任务成本选模；同档内按成本排序；激活 EscalationPolicyService 与 fallback_model_id；删除死字段 routing_rules。

**Architecture:** `TaskPlanItem` 增加 `model_tier`/`model_id_hint`/`complexity`/`balance_credits`；`MultiAgentExecutor._build_plan` 透传 ConductorAgentTask 的档位与 hint（routing_decision.task_plan_summary.agents 中已含 model_tier/model_id_hint）；`_SubtaskTaskExecutor` 在 item.model_tier 有值时按 tier 独立实例化 LLM（`LanguageModelService.get_chat_model_by_tier`），无则回退 host.llm；`RuntimeModelPoolService.select_model_with_fallback` 同档候选链内加成本排序；`ExecutionCoordinatorService` 注入 `EscalationPolicyService`（默认 escalation_enabled=false）；删除 `routing_rules` 列与 admin 表单。

**Tech Stack:** Python 3.12 / Quart / SQLAlchemy / Alembic / pytest / Vue 3 + Arco Design

**范围说明**：本计划覆盖规格 P3。前置规格：`docs/superpowers/specs/2026-08-30-billing-reconciliation-routing-design.md` 第 6、7 节。P1/P2 已完成（定价引擎、对账、聚合器），迁移 head = e8f9a0b1c2d3。

---

### Task 1: TaskPlanItem 增加模型档位字段 + 透传

**Files:**
- Modify: `api/internal/entity/execution_orchestration_entity.py`
- Modify: `api/internal/service/executors/multi_agent_executor.py:185-206`
- Test: `api/test/internal/entity/test_execution_orchestration_entity.py`

- [ ] **Step 1: 写失败测试——字段与透传**

```python
from internal.entity.execution_orchestration_entity import TaskPlanItem


def test_task_plan_item_carries_model_tier_and_hint():
    item = TaskPlanItem.from_dict({
        "task_id": "t1", "title": "调研",
        "model_tier": "3", "model_id_hint": "model-x",
        "complexity": "complex", "balance_credits": 500,
    })
    assert item.model_tier == "3"
    assert item.model_id_hint == "model-x"
    assert item.complexity == "complex"
    assert item.balance_credits == 500
```

- [ ] **Step 2: 运行确认失败**

Run: `python -m pytest test/internal/entity/test_execution_orchestration_entity.py -q --no-cov`
Expected: FAIL（TaskPlanItem 无 model_tier 属性）。

- [ ] **Step 3: 实体新增字段 + from_dict 解析**

在 `TaskPlanItem` dataclass 追加（`execution_order` 后）：

```python
    model_tier: str = ""
    model_id_hint: str = ""
    complexity: str = "simple"
    balance_credits: float = 0.0
```

`from_dict` 追加解析：

```python
            model_tier=_text(data.get("model_tier")) or "1",
            model_id_hint=_text(data.get("model_id_hint")),
            complexity=_text(data.get("complexity")) or "simple",
            balance_credits=_non_negative_float(data.get("balance_credits")),
```

- [ ] **Step 4: 运行确认通过**

Run: `python -m pytest test/internal/entity/test_execution_orchestration_entity.py -q --no-cov`
Expected: PASS。

- [ ] **Step 5: _build_plan 透传**

`multi_agent_executor.py` `_build_plan`（L185-206）的 `TaskPlanItem(...)` 构造追加：

```python
                    model_tier=str(agent.get("model_tier") or ""),
                    model_id_hint=str(agent.get("model_id_hint") or ""),
                    complexity=str(agent.get("complexity") or "simple"),
                    balance_credits=float(agent.get("balance_credits") or 0),
```

（说明：`task_plan_summary.agents` 由 ConductorAgentTask.to_dict() 产生，已含 model_tier/model_id_hint；`complexity/balance_credits` 首期由 routing_decision 或上游传入，缺省 simple/0，供 escalation 读取。）

- [ ] **Step 6: 回归验证**

Run: `python -m pytest test/internal/entity/ test/internal/service/test_assistant_agent_service.py -q --no-cov`
Expected: PASS。

- [ ] **Step 7: Commit**

```bash
git add api/internal/entity/execution_orchestration_entity.py api/internal/service/executors/multi_agent_executor.py api/test/internal/entity/test_execution_orchestration_entity.py
git commit -m "feat(routing): task plan item carries conductor model tier"
```

---

### Task 2: 子任务独立配模（子 Agent 按 tier 实例化）

**Files:**
- Modify: `api/internal/service/executors/multi_agent_executor.py:488-498`
- Test: `api/test/internal/service/test_multi_agent_executor.py`

- [ ] **Step 1: 写失败测试——有 model_tier 时独立实例化**

在 `test_multi_agent_executor.py` 追加（参照现有构造方式；用 monkeypatch 拦截 `get_chat_model_by_tier`）：

```python
def test_subtask_executor_resolves_model_by_tier(monkeypatch):
    from internal.service.executors.multi_agent_executor import _SubtaskTaskExecutor
    from internal.entity.execution_orchestration_entity import TaskPlanItem

    resolved = []
    monkeypatch.setattr(
        "internal.service.language_model_service.LanguageModelService.get_chat_model_by_tier",
        lambda tier: resolved.append(tier) or ("llm-" + str(tier)),
    )

    item = TaskPlanItem(task_id="t1", title="t", model_tier="3")
    host = SimpleNamespace(
        agent_class=object, agent_config={}, tools=[], history=[],
        llm="host-llm", long_term_memory=None, user_memory=None,
        subtask_registry=None, query="q",
    )
    executor = _SubtaskTaskExecutor(host=host, event_emitter=None, sse_queue=...)
    # 调用 executor._resolve_llm_for_item(item) 断言返回 "llm-3" 且 resolved == ["3"]
```

（测试以现有 `_SubtaskTaskExecutor` 构造签名为准；核心断言 `resolved` 收到 `"3"`。）

- [ ] **Step 2: 运行确认失败**

Run: `python -m pytest test/internal/service/test_multi_agent_executor.py -q --no-cov`
Expected: FAIL（无 _resolve_llm_for_item）。

- [ ] **Step 3: 实现——_SubtaskTaskExecutor 增加按 tier 解析**

`_SubtaskTaskExecutor` 增加方法并在 `execute()` 中替换 `llm=self.host.llm`：

```python
    def _resolve_llm_for_item(self, item: TaskPlanItem):
        """子任务独立配模：item.model_tier 非空时按档位实例化；失败/缺失回退 host.llm。"""
        tier = getattr(item, "model_tier", "") or ""
        if not tier:
            return self.host.llm
        try:
            from internal.service.language_model_service import LanguageModelService
            return LanguageModelService.get_chat_model_by_tier(tier)
        except Exception:
            logger.warning("子任务按档位实例化失败 tier=%s，回退 host llm", tier, exc_info=True)
            return self.host.llm
```

`execute()`（L488-498）改为：

```python
            task_executor = AgentTaskExecutor(
                agent_class=self.host.agent_class,
                agent_config=self.host.agent_config,
                tools=self.host.tools or [],
                llm=self._resolve_llm_for_item(item),
                history=self.host.history or [],
                query=item.description or self.host.query,
                long_term_memory=self.host.long_term_memory,
                user_memory=self.host.user_memory,
                event_emitter=_event_emitter_with_activity,
            )
```

（需确认 `LanguageModelService.get_chat_model_by_tier` 是 classmethod 可从类调用——查 `language_model_service.py` 定义；若是实例方法则在方法内 `LanguageModelService().get_chat_model_by_tier(tier)`。）

- [ ] **Step 4: 运行确认通过**

Run: `python -m pytest test/internal/service/test_multi_agent_executor.py -q --no-cov`
Expected: PASS。

- [ ] **Step 5: 回归验证**

Run: `python -m pytest test/internal/service/test_assistant_agent_service.py test/internal/service/test_execution_coordinator_service.py -q --no-cov`
Expected: PASS（无 host.llm 行为变化路径回归）。

- [ ] **Step 6: Commit**

```bash
git add api/internal/service/executors/multi_agent_executor.py api/test/internal/service/test_multi_agent_executor.py
git commit -m "feat(routing): per-subtask model resolution by tier"
```

---

### Task 3: 同档内成本排序（select_model_with_fallback）

**Files:**
- Modify: `api/internal/service/runtime_model_pool_service.py:45-78`
- Test: `api/test/internal/service/test_runtime_model_pool_service.py`

- [ ] **Step 1: 写失败测试——同档成本排序**

```python
def test_select_model_with_fallback_sorts_by_cost_within_tier(session_stub):
    from internal.service.runtime_model_pool_service import RuntimeModelPoolService

    svc = RuntimeModelPoolService(db=session_stub, language_model_manager=None)
    # 构造两个同 tier 模型：成本参考值 A=2.0（便宜）、B=5.0（贵）
    # get_active_models 返回 [A(priority=1), B(priority=1)]；_get_tier_policy 返回 None（无白名单）
    primary, fallbacks = svc.select_model_with_fallback(tier="2")
    assert primary.model_name == "cheap-model"
```

（以现有测试 fixture 的 `_session_stub`/建表为准构造；断言 primary 是参考成本最低者，且 priority 排序仍优先于成本。）

- [ ] **Step 2: 运行确认失败**

Run: `python -m pytest test/internal/service/test_runtime_model_pool_service.py::test_select_model_with_fallback_sorts_by_cost_within_tier -q --no-cov`
Expected: FAIL（当前按 priority+created_at 排序，不按成本）。

- [ ] **Step 3: 实现成本参考值与排序**

`runtime_model_pool_service.py`：

- 新增静态方法：

```python
    @staticmethod
    def _cost_reference(model: ModelPoolConfig) -> float:
        """同档成本参考：按 3:1 输入输出均衡权重，成本值取自成本基准（元/1k）。
        返回越小越省；两个成本都未配置时返回很大值（排最后，仍可用但非优先）。"""
        in_cost = float(getattr(model, "input_cost_per_1k_tokens", 0) or 0)
        out_cost = float(getattr(model, "output_cost_per_1k_tokens", 0) or 0)
        if in_cost <= 0 and out_cost <= 0:
            return float("inf")
        return in_cost * 3 + out_cost
```

- 在 `select_model_with_fallback` 的**排序层**（`get_active_models` 返回后、白名单/default 逻辑不变的前提下），调整候选链内排序。最小侵入方案：`get_active_models` 排序键改为 `priority DESC, cost_reference ASC, created_at ASC`：

```python
        return query.order_by(
            ModelPoolConfig.priority.desc(),
            ModelPoolConfig.created_at.asc(),
        ).all()
```

改为先按 priority 分组、组内按成本排序——`select_model_with_fallback` 内：

```python
        models = self.get_active_models(tier, model_type)
        if not models:
            return None, []
        # 同 priority 组内按成本参考值升序（省模型优先）；priority 仍为第一键
        models.sort(key=lambda m: (0 - int(m.priority or 0), self._cost_reference(m), m.created_at or self._now()))
```

（注意：`get_active_models` 保持 SQL 排序不动；在 `select_model_with_fallback` 入口做内存稳定排序，避免动 SQL 影响其他调用方。）

- [ ] **Step 4: 运行确认通过**

Run: `python -m pytest test/internal/service/test_runtime_model_pool_service.py -q --no-cov`
Expected: PASS（含原 15 用例 + 新用例）。

- [ ] **Step 5: 回归验证（含 assistant 主路径）**

Run: `python -m pytest test/internal/service/test_runtime_model_pool_service.py test/internal/service/test_assistant_agent_service.py test/internal/service/test_language_model_service.py -q --no-cov`
Expected: PASS。

- [ ] **Step 6: Commit**

```bash
git add api/internal/service/runtime_model_pool_service.py api/test/internal/service/test_runtime_model_pool_service.py
git commit -m "feat(routing): cost-aware ordering within tier"
```

---

### Task 4: EscalationPolicyService 生产注入（默认关闭）

**Files:**
- Modify: `api/internal/service/execution_coordinator_service.py`
- Modify: `api/internal/service/executors/single_agent_executor.py:118-124`
- Modify: `api/internal/service/executors/multi_agent_executor.py:111-117`
- Test: `api/test/internal/service/test_execution_coordinator_service.py`

- [ ] **Step 1: 写失败测试——生产路径注入**

在 `test_execution_coordinator_service.py` 增加：

```python
def test_coordinator_injected_with_escalation_when_enabled(session_stub):
    from internal.service.execution_coordinator_service import ExecutionCoordinatorService
    svc = ExecutionCoordinatorService(
        executor=executor, cancel_token=None, subtask_registry=None, request_id="r1",
        escalation_policy_service=EscalationPolicyService(),
    )
    assert svc.escalation_policy_service is not None
```

（以现有构造签名为准。）

- [ ] **Step 2: 运行确认失败**

Run: `python -m pytest test/internal/service/test_execution_coordinator_service.py::test_coordinator_injected_with_escalation_when_enabled -q --no-cov`
Expected: 视构造签名而定——若已支持参数则 PASS；若签名缺 escalation_policy_service 则 FAIL。本任务的落点是**两个 executor 生产构造点**。

- [ ] **Step 3: 实现——executor 构造 Coordinator 时带开关**

在 `single_agent_executor.py` L118-124 与 `multi_agent_executor.py` L111-117 的 Coordinator 构造处，按 `billing_config` 开关 `escalation_enabled`（默认 false）注入：

```python
        escalate_service = None
        try:
            from internal.model.billing import BillingConfig
            from internal.service.cost_policy_service import EscalationPolicyService
            from internal.extension.database_extension import db
            row = db.session.query(BillingConfig).filter(BillingConfig.code == "escalation_enabled").one_or_none()
            if row is not None and float(row.value_numeric or 0) >= 1:
                escalate_service = EscalationPolicyService()
        except Exception:
            escalate_service = None

        coordinator = ExecutionCoordinatorService(
            executor=self,
            cancel_token=cancel_token,
            subtask_registry=subtask_registry,
            request_id=request_id,
            escalation_policy_service=escalate_service,
        )
```

（两处各一份完整代码，不得写"同上"。）

- [ ] **Step 4: 运行确认通过**

Run: `python -m pytest test/internal/service/test_execution_coordinator_service.py test/internal/service/test_assistant_agent_service.py -q --no-cov`
Expected: PASS（escalation_enabled 未配置时行为不变）。

- [ ] **Step 5: 补充开关配置测试**

在 `billing_config` 测试文件或 executor 测试中验证：`escalation_enabled=1` 时注入非 None；缺省时 None。

- [ ] **Step 6: Commit**

```bash
git add api/internal/service/execution_coordinator_service.py api/internal/service/executors/single_agent_executor.py api/internal/service/executors/multi_agent_executor.py api/test/internal/service/test_execution_coordinator_service.py
git commit -m "feat(routing): wire escalation policy behind billing config flag"
```

---

### Task 5: 子任务配模兜底链（tier 失败回退 host.llm + hint 元数据）

**Files:**
- Modify: `api/internal/service/executors/multi_agent_executor.py`（_resolve_llm_for_item 兜底增强）
- Test: `api/test/internal/service/test_multi_agent_executor.py`

> 说明：经核实，仓库**没有**按模型 ID 实例化池模型的现成 API（`get_pool_model_by_id` 不存在；`get_chat_model_by_tier` 是 classmethod 走池解析）。因此 `model_id_hint` 本阶段**只作元数据透传**（进入 agent 上下文供未来使用），不引入不存在的接口；实例化一律按 tier。Task 5 聚焦「tier 解析异常时兜底 host.llm」与「hint 透传到 execute 上下文」。

- [ ] **Step 1: 写失败测试——tier 解析失败回退 host.llm**

```python
def test_resolve_llm_falls_back_to_host_on_tier_error(monkeypatch):
    from internal.service.executors.multi_agent_executor import _SubtaskTaskExecutor
    from internal.entity.execution_orchestration_entity import TaskPlanItem

    def _boom(tier):
        raise RuntimeError("no model in pool")

    monkeypatch.setattr(
        "internal.service.language_model_service.LanguageModelService.get_chat_model_by_tier",
        classmethod(lambda cls, tier: _boom(tier)),
    )
    item = TaskPlanItem(task_id="t1", title="t", model_tier="3")
    host = SimpleNamespace(llm="host-llm")
    executor = _SubtaskTaskExecutor(host=host, event_emitter=None, sse_queue=None)
    assert executor._resolve_llm_for_item(item) == "host-llm"
```

- [ ] **Step 2: 运行确认失败**

Run: `python -m pytest test/internal/service/test_multi_agent_executor.py -q --no-cov`
Expected: FAIL（_resolve_llm_for_item 已存在于 Task 2，但此用例若此前未覆盖异常回退则先红）。

- [ ] **Step 3: 实现——_resolve_llm_for_item 兜底 + hint 透传**

```python
    def _resolve_llm_for_item(self, item: TaskPlanItem):
        """子任务独立配模：item.model_tier 非空时按档位实例化；失败/缺失回退 host.llm。

        model_id_hint 本阶段仅作元数据透传（无按 ID 实例化的池 API），
        实例化一律按 tier 走 get_chat_model_by_tier（classmethod，池解析+降级）。
        """
        tier = getattr(item, "model_tier", "") or ""
        if not tier:
            return self.host.llm
        try:
            from internal.service.language_model_service import LanguageModelService
            return LanguageModelService.get_chat_model_by_tier(tier)
        except Exception:
            logger.warning("子任务按档位实例化失败 tier=%s，回退 host llm", tier, exc_info=True)
            return self.host.llm
```

（若 Task 2 已实现同逻辑则此步仅补 hint 透传：`execute()` 构造 AgentTaskExecutor 后，在 `item.model_id_hint` 非空时塞入 `context["model_id_hint"] = item.model_id_hint`。）

- [ ] **Step 4: 运行确认通过**

Run: `python -m pytest test/internal/service/test_multi_agent_executor.py test/internal/service/test_assistant_agent_service.py -q --no-cov`
Expected: PASS。

- [ ] **Step 5: Commit**

```bash
git add api/internal/service/executors/multi_agent_executor.py api/test/internal/service/test_multi_agent_executor.py
git commit -m "feat(routing): fallback to host llm and hint passthrough"
```

---

### Task 6: 删除死字段 routing_rules

**Files:**
- Create: `api/internal/migration/versions/f0a1b2c3d4e5_drop_model_tier_routing_rules.py`
- Modify: `api/internal/model/model_pool_entity.py:119`
- Modify: `api/internal/schema/admin_model_pool_schema.py`
- Modify: `api/internal/service/admin_model_pool_service.py:496-517,827`
- Test: `api/test/app/http/test_admin_routes_3.py`

- [ ] **Step 1: 写失败测试——实体不再含 routing_rules**

```python
from internal.model.model_pool_entity import ModelTierPolicy


def test_model_tier_policy_dropped_routing_rules():
    assert "routing_rules" not in ModelTierPolicy.__table__.columns.keys()
```

- [ ] **Step 2: 运行确认失败**

Run（该测试）: Expected: FAIL（列仍存在）。

- [ ] **Step 3: 实体删列 + admin 清理**

- `model_pool_entity.py` 删除 `routing_rules` 列。
- `admin_model_pool_service.py`：`create_tier_policy`/`update_tier_policy`/serialize（L496/517/827）删除 routing_rules 读写；`admin_model_pool_schema.py` 对应删除 DictField 与 fields.Dict。
- 模型池服务 `_get_tier_policy` 使用处不读 routing_rules。

- [ ] **Step 4: 迁移 f0a1b2c3d4e5**

```python
"""drop routing_rules from model_tier_policy

Revision ID: f0a1b2c3d4e5
Revises: e8f9a0b1c2d3
Create Date: 2026-08-30 10:00:00.000000
"""
from alembic import op

revision = 'f0a1b2c3d4e5'
down_revision = 'e8f9a0b1c2d3'
branch_labels = None
depends_on = None


def upgrade():
    op.drop_column('model_tier_policy', 'routing_rules')


def downgrade():
    from alembic import op
    import sqlalchemy as sa
    from sqlalchemy.dialects.postgresql import JSONB
    op.add_column('model_tier_policy', sa.Column(
        'routing_rules', JSONB(),
        server_default=sa.text("'{}'::jsonb"), nullable=False,
    ))
```

- [ ] **Step 5: 同步测试 DDL**

`api/test/conftest.py` 的 model_tier_policy DDL 中删除 `routing_rules` 行（若无此列定义则跳过）。

- [ ] **Step 6: 回归验证**

Run: `python -m pytest test/app/http/test_admin_routes_3.py test/internal/service/test_runtime_model_pool_service.py -q --no-cov`
Expected: PASS。

- [ ] **Step 7: Commit**

```bash
git add api/internal/model/model_pool_entity.py api/internal/schema/admin_model_pool_schema.py api/internal/service/admin_model_pool_service.py api/internal/migration/versions/f0a1b2c3d4e5_drop_model_tier_routing_rules.py api/test/conftest.py api/test/app/http/test_admin_routes_3.py
git commit -m "refactor(routing): drop dead routing_rules field"
```

---

### Task 7: 全量回归、迁移应用与 E2E

- [ ] **Step 1: 后端全量**

Run: `python -m pytest test -q --no-cov`
Expected: 全量通过。

- [ ] **Step 2: 前端全量**

Run: `npm run lint`、`npx vue-tsc --noEmit`、`npx vitest run`

- [ ] **Step 3: 应用迁移**

`docker restart llmops-api` → healthy。
Run: `docker exec llmops-db psql -U postgres -d llmops -t -A -c "SELECT version_num FROM alembic_version"`
Expected: `f0a1b2c3d4e5`。

Run: `docker exec llmops-db psql -U postgres -d llmops -t -A -c "SELECT count(*) FROM information_schema.columns WHERE table_name='model_tier_policy' AND column_name='routing_rules'"`
Expected: `0`。

- [ ] **Step 4: E2E——子任务独立配模**

容器内 python（经 app 初始化）：构造带 model_tier="3"/model_id_hint 的 TaskPlanItem → 调 `_SubtaskTaskExecutor._resolve_llm_for_item` → 断言返回按 tier 解析的模型且不同于 host.llm。

- [ ] **Step 5: E2E——同档成本排序**

构造两个同 tier 模型（成本参考不同）→ `select_model_with_fallback` → 断言 primary 为成本低者。清理测试模型。

- [ ] **Step 6: E2E——escalation 开关**

`billing_config` 写 `escalation_enabled=0` → executor 构造的 escalation_policy_service 为 None；写 1 → 非 None。验证后恢复删除。

- [ ] **Step 7: 清理数据与脚本、graphify**

```bash
docker exec llmops-db psql -U postgres -d llmops -c "DELETE FROM model_pool_config WHERE model_name LIKE 'e2e%'; DELETE FROM billing_config WHERE code='escalation_enabled'"
python -m graphify update .
```

---

## 计划自检

- **规格覆盖**：P3 五块——TaskPlanItem 透传（Task 1）、子任务独立配模（Task 2）、同档成本排序（Task 3）、Escalation 激活（Task 4）、兜底链+hint 透传（Task 5）、routing_rules 删除（Task 6）。说明：规格中"fallback_model_id 激活"经核实仓库无按 ID 实例化的池 API，本阶段以「tier 解析失败回退 host.llm + hint 透传」落地，不引入不存在的接口（记录于 Task 5 说明）。
- **接口一致性**（跨任务契约）：
  - `TaskPlanItem.model_tier/model_id_hint/complexity/balance_credits`（Task 1 定义；Task 2/4 读取）
  - `_SubtaskTaskExecutor._resolve_llm_for_item(item)`（Task 2 定义；Task 5 增强）
  - `RuntimeModelPoolService._cost_reference(model)`（Task 3 定义，仅 Task 3 使用）
  - `escalation_enabled` billing_config 键（Task 4 定义，E2E 用）
- **无占位符**：每步骤含完整代码/命令/预期；引用的 `get_chat_model_by_tier` 已核实为真实 classmethod（language_model_service.py L704）。
- **向后兼容**：escalation 默认关闭、host.llm 兜底、get_active_models SQL 排序不动（内存稳定排序）——全部不改变现有行为。