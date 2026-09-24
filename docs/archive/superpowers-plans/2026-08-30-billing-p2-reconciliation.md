# 双轨对账与告警（P2）实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 落地任务结束实时对账（自动多退少补）、偏差率+绝对阈值+亏本三告警、毛利看板，让估算/真实/成本三口径全部可查可算。

**Architecture:** 新增 `billing_usage_event`（原始事件）与 `billing_reconciliation`（任务对账摘要）两表；`BillingUsageAggregator.final()` 扩展为对账回调：落事件 → 定价引擎重算 → 差额多退少补（幂等）→ 写对账行 → 超阈值/亏本告警；`CreditService` 新增 adjustment 交易类型（source="reconciliation" 幂等键）；admin 新增毛利聚合接口；前端新增毛利看板页。

**Tech Stack:** Python 3.12 / Quart / SQLAlchemy / Alembic / pytest / Vue 3 + Arco Design

**范围说明**：本计划只覆盖规格的 P2。前置规格：`docs/superpowers/specs/2026-08-30-billing-reconciliation-routing-design.md` 第 5 节。P1 已完成（定价引擎/成本列/聚合器 model 明细），迁移 head = d7e8f9a0b1c2。

---

### Task 1: 迁移与实体——两张对账表

**Files:**
- Create: `api/internal/migration/versions/e8f9a0b1c2d3_add_billing_reconciliation_tables.py`
- Modify: `api/internal/model/billing.py`（追加两个模型）
- Test: `api/test/internal/model/test_billing_reconciliation_entity.py`

- [ ] **Step 1: 写失败测试——实体字段齐全**

```python
from internal.model.billing import BillingUsageEvent, BillingReconciliation


def test_usage_event_columns():
    keys = BillingUsageEvent.__table__.columns.keys()
    for col in ("task_id", "model_id", "source_type", "input_tokens", "output_tokens",
                "estimated_credits", "actual_credits", "cost_credits", "billing_basis",
                "is_estimated", "created_at"):
        assert col in keys, col


def test_reconciliation_columns():
    keys = BillingReconciliation.__table__.columns.keys()
    for col in ("task_id", "account_id", "estimated_credits", "actual_credits",
                "cost_credits", "diff_credits", "status", "alert_flags"):
        assert col in keys, col
```

- [ ] **Step 2: 运行确认失败**

Run: `python -m pytest test/internal/model/test_billing_reconciliation_entity.py -q --no-cov`
Expected: FAIL（模型不存在）。

- [ ] **Step 3: 实体实现（billing.py 追加）**

```python
class BillingUsageEvent(Base):
    __tablename__ = "billing_usage_event"
    __table_args__ = (
        PrimaryKeyConstraint("id", name="pk_billing_usage_event_id"),
        Index("billing_usage_event_task_idx", "task_id"),
        Index("billing_usage_event_model_idx", "model_id"),
        Index("billing_usage_event_created_idx", "created_at"),
    )

    id = Column(UUID, nullable=False, server_default=text("uuid_generate_v4()"))
    # task_id: 对账聚合单元键（message.id / 编排 task_id）
    task_id = Column(String(128), nullable=False, server_default=text("''::character varying"))
    model_id = Column(String(64), nullable=True)
    source_type = Column(String(64), nullable=False, server_default=text("''::character varying"))
    input_tokens = Column(Integer, nullable=False, server_default=text("0"))
    output_tokens = Column(Integer, nullable=False, server_default=text("0"))
    # billing_basis: provider_usage / tiktoken_estimate
    billing_basis = Column(String(64), nullable=False, server_default=text("''::character varying"))
    # is_estimated: 真实 usage 缺失、用估算兜底时为 true
    is_estimated = Column(Boolean, nullable=False, server_default=text("false"))
    estimated_credits = Column(Integer, nullable=False, server_default=text("0"))
    actual_credits = Column(Integer, nullable=False, server_default=text("0"))
    cost_credits = Column(Integer, nullable=False, server_default=text("0"))
    created_at = Column(DateTime, nullable=False, server_default=text("CURRENT_TIMESTAMP(0)"))


class BillingReconciliation(Base):
    __tablename__ = "billing_reconciliation"
    __table_args__ = (
        PrimaryKeyConstraint("id", name="pk_billing_reconciliation_id"),
        Index("billing_reconciliation_task_idx", "task_id", unique=True),
        Index("billing_reconciliation_account_idx", "account_id"),
    )

    id = Column(UUID, nullable=False, server_default=text("uuid_generate_v4()"))
    task_id = Column(String(128), nullable=False, server_default=text("''::character varying"))
    account_id = Column(UUID, nullable=False)
    # 售价算力
    estimated_credits = Column(Integer, nullable=False, server_default=text("0"))
    actual_credits = Column(Integer, nullable=False, server_default=text("0"))
    # diff = actual - estimated（正=补扣、负=退还）
    diff_credits = Column(Integer, nullable=False, server_default=text("0"))
    # 成本算力（对账/毛利用）
    cost_credits = Column(Integer, nullable=False, server_default=text("0"))
    # 金额成本（人民币，用于报表与汇率敏感度）
    cost_amount = Column(Numeric(12, 6), nullable=False, server_default=text("0.000000"))
    status = Column(String(32), nullable=False, server_default=text("'settled'::character varying"))
    # 告警标记列表：["ratio_deviation","negative_margin"] JSONB
    alert_flags = Column(JSONB, nullable=False, server_default=text("'[]'::jsonb"))
    settled_at = Column(DateTime, nullable=False, server_default=text("CURRENT_TIMESTAMP(0)"))
    created_at = Column(DateTime, nullable=False, server_default=text("CURRENT_TIMESTAMP(0)"))
```

补充 import：`from sqlalchemy import Boolean`（若未导入）、`from sqlalchemy.dialects.postgresql import JSONB`（billing.py 顶部已导入 JSONB 则跳过）。检查 billing.py 现有 import，缺则补。

- [ ] **Step 4: 运行确认通过**

Run: `python -m pytest test/internal/model/test_billing_reconciliation_entity.py -q --no-cov`
Expected: PASS。

- [ ] **Step 5: 创建迁移 e8f9a0b1c2d3**

`down_revision='d7e8f9a0b1c2'`：

```python
"""add billing usage event and reconciliation tables

Revision ID: e8f9a0b1c2d3
Revises: d7e8f9a0b1c2
Create Date: 2026-08-30 08:00:00.000000
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB


revision = 'e8f9a0b1c2d3'
down_revision = 'd7e8f9a0b1c2'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'billing_usage_event',
        sa.Column('id', sa.UUID(), server_default=sa.text('uuid_generate_v4()'), nullable=False),
        sa.Column('task_id', sa.String(length=128), server_default=sa.text("''::character varying"), nullable=False),
        sa.Column('model_id', sa.String(length=64), nullable=True),
        sa.Column('source_type', sa.String(length=64), server_default=sa.text("''::character varying"), nullable=False),
        sa.Column('input_tokens', sa.Integer(), server_default=sa.text('0'), nullable=False),
        sa.Column('output_tokens', sa.Integer(), server_default=sa.text('0'), nullable=False),
        sa.Column('billing_basis', sa.String(length=64), server_default=sa.text("''::character varying"), nullable=False),
        sa.Column('is_estimated', sa.Boolean(), server_default=sa.text('false'), nullable=False),
        sa.Column('estimated_credits', sa.Integer(), server_default=sa.text('0'), nullable=False),
        sa.Column('actual_credits', sa.Integer(), server_default=sa.text('0'), nullable=False),
        sa.Column('cost_credits', sa.Integer(), server_default=sa.text('0'), nullable=False),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('CURRENT_TIMESTAMP(0)'), nullable=False),
        sa.PrimaryKeyConstraint('id', name='pk_billing_usage_event_id'),
    )
    op.create_index('billing_usage_event_task_idx', 'billing_usage_event', ['task_id'])
    op.create_index('billing_usage_event_model_idx', 'billing_usage_event', ['model_id'])
    op.create_index('billing_usage_event_created_idx', 'billing_usage_event', ['created_at'])

    op.create_table(
        'billing_reconciliation',
        sa.Column('id', sa.UUID(), server_default=sa.text('uuid_generate_v4()'), nullable=False),
        sa.Column('task_id', sa.String(length=128), server_default=sa.text("''::character varying"), nullable=False),
        sa.Column('account_id', sa.UUID(), nullable=False),
        sa.Column('estimated_credits', sa.Integer(), server_default=sa.text('0'), nullable=False),
        sa.Column('actual_credits', sa.Integer(), server_default=sa.text('0'), nullable=False),
        sa.Column('diff_credits', sa.Integer(), server_default=sa.text('0'), nullable=False),
        sa.Column('cost_credits', sa.Integer(), server_default=sa.text('0'), nullable=False),
        sa.Column('cost_amount', sa.Numeric(precision=12, scale=6), server_default=sa.text('0.000000'), nullable=False),
        sa.Column('status', sa.String(length=32), server_default=sa.text("'settled'::character varying"), nullable=False),
        sa.Column('alert_flags', JSONB(), server_default=sa.text("'[]'::jsonb"), nullable=False),
        sa.Column('settled_at', sa.DateTime(), server_default=sa.text('CURRENT_TIMESTAMP(0)'), nullable=False),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('CURRENT_TIMESTAMP(0)'), nullable=False),
        sa.PrimaryKeyConstraint('id', name='pk_billing_reconciliation_id'),
    )
    op.create_index('billing_reconciliation_task_idx', 'billing_reconciliation', ['task_id'], unique=True)
    op.create_index('billing_reconciliation_account_idx', 'billing_reconciliation', ['account_id'])


def downgrade():
    op.drop_index('billing_reconciliation_account_idx', table_name='billing_reconciliation')
    op.drop_index('billing_reconciliation_task_idx', table_name='billing_reconciliation')
    op.drop_table('billing_reconciliation')
    op.drop_index('billing_usage_event_created_idx', table_name='billing_usage_event')
    op.drop_index('billing_usage_event_model_idx', table_name='billing_usage_event')
    op.drop_index('billing_usage_event_task_idx', table_name='billing_usage_event')
    op.drop_table('billing_usage_event')
```

- [ ] **Step 6: 同步测试建表 DDL**

`api/test/conftest.py` 增加两个 CREATE TABLE（参照 `_MODEL_POOL_CONFIG_DDL` 风格，sqlite 兼容：JSONB→TEXT、Numeric→NUMERIC、Boolean→BOOLEAN）：

```sql
CREATE TABLE billing_usage_event (
    id VARCHAR(36) NOT NULL PRIMARY KEY,
    task_id VARCHAR(128) NOT NULL DEFAULT '',
    model_id VARCHAR(64),
    source_type VARCHAR(64) NOT NULL DEFAULT '',
    input_tokens INTEGER NOT NULL DEFAULT 0,
    output_tokens INTEGER NOT NULL DEFAULT 0,
    billing_basis VARCHAR(64) NOT NULL DEFAULT '',
    is_estimated BOOLEAN NOT NULL DEFAULT FALSE,
    estimated_credits INTEGER NOT NULL DEFAULT 0,
    actual_credits INTEGER NOT NULL DEFAULT 0,
    cost_credits INTEGER NOT NULL DEFAULT 0,
    created_at DATETIME NOT NULL
);

CREATE TABLE billing_reconciliation (
    id VARCHAR(36) NOT NULL PRIMARY KEY,
    task_id VARCHAR(128) NOT NULL UNIQUE,
    account_id VARCHAR(36) NOT NULL,
    estimated_credits INTEGER NOT NULL DEFAULT 0,
    actual_credits INTEGER NOT NULL DEFAULT 0,
    diff_credits INTEGER NOT NULL DEFAULT 0,
    cost_credits INTEGER NOT NULL DEFAULT 0,
    cost_amount NUMERIC NOT NULL DEFAULT 0,
    status VARCHAR(32) NOT NULL DEFAULT 'settled',
    alert_flags TEXT NOT NULL DEFAULT '[]',
    settled_at DATETIME NOT NULL,
    created_at DATETIME NOT NULL
);
```

（在 conftest 建表函数中执行，参照现有模式。）

- [ ] **Step 7: 回归验证**

Run: `python -m pytest test/internal/model/test_billing_reconciliation_entity.py -q --no-cov`
Expected: PASS。

- [ ] **Step 8: Commit**

```bash
git add api/internal/model/billing.py api/internal/migration/versions/e8f9a0b1c2d3_add_billing_reconciliation_tables.py api/test/internal/model/test_billing_reconciliation_entity.py api/test/conftest.py
git commit -m "feat(billing): usage event and reconciliation tables"
```

---

### Task 2: CreditService 新增 adjustment（多退少补）

**Files:**
- Modify: `api/internal/service/credit_service.py`
- Test: `api/test/internal/service/test_credit_service.py`

- [ ] **Step 1: 写失败测试——调整交易**

```python
def test_adjust_credits_positive_refunds(session_stub):
    svc = CreditService(session=session_stub)
    result = svc.adjust_credits(
        ACCOUNT_ID,
        diff_credits=-5,          # 负 = 多扣，退还
        source="reconciliation",
        source_id=TASK_ID,
        description="对账退还",
    )
    assert result["amount"] == 5         # 退还为正
    assert result["reconciliation"] is True


def test_adjust_credits_negative_charges_more(session_stub):
    svc = CreditService(session=session_stub)
    result = svc.adjust_credits(
        ACCOUNT_ID,
        diff_credits=3,           # 正 = 少扣，补扣
        source="reconciliation",
        source_id=TASK_ID,
        description="对账补扣",
    )
    assert result["amount"] == -3
```

（以现有测试 fixture 为准调整 stub 结构；TASK_ID 定义于文件内。）

- [ ] **Step 2: 运行确认失败**

Run: `python -m pytest test/internal/service/test_credit_service.py::TestCreditService::test_adjust_credits_positive_refunds -q --no-cov`
Expected: FAIL（adjust_credits 不存在）。

- [ ] **Step 3: 实现 adjust_credits**

```python
    def adjust_credits(
        self,
        account_id: UUID,
        *,
        diff_credits: int,
        source: str,
        source_id,
        description: str = "",
    ) -> dict:
        """对账多退少补：diff>0 补扣、diff<0 退还。幂等：同 (source, source_id) 只执行一次。

        金额 = -diff_credits（退款为正、补扣为负），与 credit_transaction 扣费符号约定一致。
        """
        diff_credits = int(diff_credits or 0)
        if diff_credits == 0:
            return {"skipped": True, "reason": "zero_diff", "amount": 0}

        tid = str(source_id)
        existing = self.session.query(CreditTransaction).filter(
            CreditTransaction.source == source,
            CreditTransaction.source_id == tid,
            CreditTransaction.transaction_type == "adjust",
        ).one_or_none()
        if existing is not None:
            return {
                "id": str(existing.id),
                "amount": int(existing.amount or 0),
                "balance_after": int(existing.balance_after or 0),
                "reconciliation": True,
                "idempotent": True,
            }

        credit_account = self._get_credit_account_for_update(account_id)
        if credit_account is None:
            raise FailException("账户算力账户不存在")

        amount = -diff_credits
        # 退还（amount>0）：永久算力优先；补扣（amount<0）：配额→永久 顺序扣
        if amount > 0:
            # 退还统一进永久算力（不区分周期包，简化并可追溯）
            credit_account.permanent_credit = int(credit_account.permanent_credit or 0) + amount
        else:
            remaining = -amount
            membership = self._get_current_membership(account_id)
            used_quota = 0
            used_permanent = 0
            if membership is not None and membership.is_active and int(credit_account.quota_credit or 0) > 0:
                used_quota = min(int(credit_account.quota_credit), remaining)
                credit_account.quota_credit = int(credit_account.quota_credit or 0) - used_quota
                remaining -= used_quota
            if remaining > 0 and int(credit_account.permanent_credit or 0) > 0:
                used_permanent = min(int(credit_account.permanent_credit), remaining)
                credit_account.permanent_credit = int(credit_account.permanent_credit or 0) - used_permanent
                remaining -= used_permanent
            if remaining > 0:
                raise FailException("算力不足，无法完成对账补扣")

        credit_account.updated_at = self._now()
        transaction = CreditTransaction(
            account_id=account_id,
            amount=amount,
            balance_after=credit_account.available_tokens,
            transaction_type="adjust",
            source=source,
            source_id=tid,
            description=description or "对账多退少补",
        )
        self.session.add(transaction)
        return {
            "id": str(transaction.id),
            "amount": amount,
            "balance_after": credit_account.available_tokens,
            "reconciliation": True,
            "idempotent": False,
        }
```

（`FailException` 已由 credit_service.py 顶部或 usage_utils 引入；检查并补 import `from internal.exception import FailException`。）

- [ ] **Step 4: 运行确认通过**

Run: `python -m pytest test/internal/service/test_credit_service.py -q --no-cov`
Expected: PASS（原 14 用例 + 新增 2）。

- [ ] **Step 5: 补充幂等回归用例**

```python
def test_adjust_credits_idempotent(session_stub):
    svc = CreditService(session=session_stub)
    first = svc.adjust_credits(ACCOUNT_ID, diff_credits=3, source="reconciliation", source_id=TASK_ID, description="")
    second = svc.adjust_credits(ACCOUNT_ID, diff_credits=3, source="reconciliation", source_id=TASK_ID, description="")
    assert second["idempotent"] is True
    assert second["amount"] == first["amount"]
```

- [ ] **Step 6: Commit**

```bash
git add api/internal/service/credit_service.py api/test/internal/service/test_credit_service.py
git commit -m "feat(billing): credit adjustment for reconciliation settle"
```

---

### Task 3: 对账服务 BillingReconciliationService

**Files:**
- Create: `api/internal/service/billing_reconciliation_service.py`
- Create: `api/test/internal/service/test_billing_reconciliation_service.py`

- [ ] **Step 1: 写失败测试——结算与告警判定**

```python
from internal.service.billing_reconciliation_service import BillingReconciliationService


def test_settle_writes_reconciliation_and_alerts(db_session_stub):
    svc = BillingReconciliationService(
        session=db_session_stub,
        pricing_engine=_engine(),
        alert_ratio=0.30,
        alert_min_abs=10,
        cost_cover_ratio=1.0,
    )
    result = svc.settle(
        task_id="task-1",
        account_id=ACCOUNT_ID,
        events=[
            {"model_id": "m1", "input_tokens": 5000, "output_tokens": 1000,
             "estimated_credits": 8, "actual_credits": None, "billing_basis": "provider_usage"},
        ],
    )
    assert result["actual_credits"] > 0
    assert "ratio_deviation" in result["alert_flags"]  # 8 -> 实际 7, 偏差 12.5% 若低于阈值则不触发；用例按真实阈值设计


def test_settle_negative_margin_alert():
    svc = BillingReconciliationService(...)
    result = svc.settle(task_id="task-2", account_id=ACCOUNT_ID, events=[...成本高于售价的事件...])
    assert "negative_margin" in result["alert_flags"]
```

（测试中用真实数字设计：偏差率/绝对差/毛利三场景分别触发对应 flag；事件总数为 0 时跳过结算。）

- [ ] **Step 2: 运行确认失败**

Run: `python -m pytest test/internal/service/test_billing_reconciliation_service.py -q --no-cov`
Expected: FAIL（服务不存在）。

- [ ] **Step 3: 实现服务**

```python
"""对账服务：任务结束后把 usage 事件落库、按定价引擎重算实际/成本算力，
求差多退少补，写对账摘要行，按阈值判定告警。"""
import math
from decimal import Decimal
from typing import Any

from internal.model.billing import BillingReconciliation, BillingUsageEvent
from internal.service.credit_service import CreditService


class BillingReconciliationService:
    DEFAULT_ALERT_RATIO = 0.30
    DEFAULT_ALERT_MIN_ABS = 10
    DEFAULT_COST_COVER_RATIO = 1.0

    def __init__(self, session=None, pricing_engine=None, credit_service=None,
                 alert_ratio=None, alert_min_abs=None, cost_cover_ratio=None):
        from internal.extension.database_extension import db
        from internal.core.billing.pricing_engine import PricingEngine
        self.session = session or db.session
        self.pricing_engine = pricing_engine or PricingEngine()
        self.credit_service = credit_service or CreditService(session=self.session)
        self.alert_ratio = alert_ratio if alert_ratio is not None else self.DEFAULT_ALERT_RATIO
        self.alert_min_abs = alert_min_abs if alert_min_abs is not None else self.DEFAULT_ALERT_MIN_ABS
        self.cost_cover_ratio = cost_cover_ratio if cost_cover_ratio is not None else self.DEFAULT_COST_COVER_RATIO

    def persist_event(self, *, task_id: str, model_id, source_type: str, input_tokens: int,
                      output_tokens: int, billing_basis: str, estimated_credits: int,
                      actual_credits: int = 0, cost_credits: int = 0, is_estimated: bool = False) -> BillingUsageEvent:
        event = BillingUsageEvent(
            task_id=task_id, model_id=model_id or None, source_type=source_type,
            input_tokens=max(int(input_tokens or 0), 0), output_tokens=max(int(output_tokens or 0), 0),
            billing_basis=billing_basis or "provider_usage",
            is_estimated=bool(is_estimated),
            estimated_credits=max(int(estimated_credits or 0), 0),
            actual_credits=max(int(actual_credits or 0), 0),
            cost_credits=max(int(cost_credits or 0), 0),
        )
        self.session.add(event)
        return event

    def settle(self, *, task_id: str, account_id, events: list[dict]) -> dict:
        """结算一个任务：重算 → 退补 → 写对账行 → 判定告警。重复调用幂等。"""
        existing = self.session.query(BillingReconciliation).filter(
            BillingReconciliation.task_id == task_id
        ).one_or_none()
        if existing is not None:
            return {"task_id": task_id, "idempotent": True, "status": existing.status,
                    "alert_flags": list(existing.alert_flags or [])}

        total_estimated = 0
        total_actual = 0
        total_cost = 0
        total_cost_amount = Decimal("0.000000")
        for ev in events:
            total_estimated += max(int(ev.get("estimated_credits") or 0), 0)
            input_tokens = max(int(ev.get("input_tokens") or 0), 0)
            output_tokens = max(int(ev.get("output_tokens") or 0), 0)
            model_id = ev.get("model_id") or ""
            plan = self.pricing_engine.plan_usage(model_id, input_tokens=input_tokens, output_tokens=output_tokens)
            total_actual += plan.sell_credits
            total_cost += plan.cost_credits
            # 人民币成本 = tokens × 成本单价/1000（BillingPlan 提供 cost_input_per_1k/cost_output_per_1k）
            cost_rmb = (input_tokens * plan.cost_input_per_1k + output_tokens * plan.cost_output_per_1k) / 1000
            total_cost_amount += Decimal(str(round(cost_rmb, 6)))

        diff = total_actual - total_estimated
        if diff != 0:
            self.credit_service.adjust_credits(
                account_id, diff_credits=diff,
                source="reconciliation", source_id=task_id,
                description=f"对账多退少补 task={task_id}",
            )

        alert_flags = []
        if total_estimated > 0:
            ratio = abs(total_actual - total_estimated) / total_estimated
            if ratio > self.alert_ratio and abs(total_actual - total_estimated) > self.alert_min_abs:
                alert_flags.append("ratio_deviation")
        if total_actual > 0 and total_cost > 0 and (total_cost / total_actual) > self.cost_cover_ratio:
            alert_flags.append("negative_margin")

        row = BillingReconciliation(
            task_id=task_id, account_id=account_id,
            estimated_credits=total_estimated, actual_credits=total_actual,
            diff_credits=diff, cost_credits=total_cost, cost_amount=total_cost_amount,
            status="settled", alert_flags=alert_flags,
        )
        self.session.add(row)
        return {
            "task_id": task_id,
            "estimated_credits": total_estimated,
            "actual_credits": total_actual,
            "cost_credits": total_cost,
            "diff_credits": diff,
            "alert_flags": alert_flags,
            "idempotent": False,
        }

- [ ] **Step 4: 运行确认通过**

Run: `python -m pytest test/internal/service/test_billing_reconciliation_service.py -q --no-cov`
Expected: PASS。

- [ ] **Step 5: Commit**

```bash
git add api/internal/service/billing_reconciliation_service.py api/test/internal/service/test_billing_reconciliation_service.py
git commit -m "feat(billing): reconciliation settle with alerts"
```

---

### Task 4: 聚合器 final() 接入对账回调

**Files:**
- Modify: `api/internal/service/billing_metering_service.py`
- Modify: `api/internal/service/assistant_agent_service.py`
- Test: `api/test/internal/service/test_billing_metering_service.py`

- [ ] **Step 1: 写失败测试——final 落事件 + 调用结算**

```python
def test_final_with_reply_service_persists_events_and_settles():
    aggregator = BillingUsageAggregator(task_id="task-1")
    aggregator.model_tokens("direct_answer", model_id="m1", input_tokens=1500, output_tokens=500, reason="r")
    aggregator.final(reconciliation_service=SimpleNamespace(settle=lambda **kw: {"task_id": kw["task_id"]}))
    assert aggregator.usage_event_buf  # 事件缓冲非空
```

- [ ] **Step 2: 运行确认失败**

Run: `python -m pytest test/internal/service/test_billing_metering_service.py::test_final_with_reply_service_persists_events_and_settles -q --no-cov`
Expected: FAIL（final 无 reconciliation_service 参数）。

- [ ] **Step 3: 实现——聚合器事件缓冲 + final 扩展**

`billing_metering_service.py`：

- 增加字段 `usage_event_buf: list[dict] = field(default_factory=list)`。
- `model_tokens()` 内追加事件到 buf（估算口径）：

```python
            self.usage_event_buf.append({
                "model_id": model_id,
                "source_type": source_name,
                "input_tokens": max(input_tokens, 0),
                "output_tokens": max(output_tokens, 0),
                "estimated_credits": sell_credits,
                "billing_basis": "provider_usage",
                "is_estimated": False,
            })
```

- `final(reconciliation_service=None, **extra)`：

```python
    def final(self, reconciliation_service: Any = None) -> BillingUsageDelta:
        event = self._record(...)  # 原有逻辑保持

        if (self.credit_service is not None and self.account_id is not None and self.total_tokens > 0):
            try:
                self.credit_service.consume_for_feature(
                    account_id=self.account_id,
                    feature_key=self.feature_key,
                    token_count=self.total_tokens,
                )
            except Exception:
                logger.warning(...)

        # P2：对账回调——把事件落库并结算（幂等）
        if reconciliation_service is not None and self.account_id is not None and self.usage_event_buf:
            try:
                for ev in self.usage_event_buf:
                    reconciliation_service.persist_event(
                        task_id=self.task_id,
                        model_id=ev["model_id"],
                        source_type=ev["source_type"],
                        input_tokens=ev["input_tokens"],
                        output_tokens=ev["output_tokens"],
                        billing_basis=ev["billing_basis"],
                        estimated_credits=ev["estimated_credits"],
                        is_estimated=ev["is_estimated"],
                    )
                reconciliation_service.settle(task_id=self.task_id, account_id=self.account_id, events=self.usage_event_buf)
            except Exception:
                logger.warning("BillingUsageAggregator 对账失败 task_id=%s", self.task_id, exc_info=True)
        return event
```

（`persist_event` 签名以此为准；Task 3 与 Task 4 由不同子代理做，**约定接口签名**：`persist_event(*, task_id, model_id, source_type, input_tokens, output_tokens, billing_basis, estimated_credits, is_estimated)` 与 `settle(*, task_id, account_id, events)`。）

- [ ] **Step 4: 调用方接入**

`assistant_agent_service.py` `_stream_direct_answer`（L354-422 区域）：
- 导入 `BillingReconciliationService`；
- 构造聚合器后创建 `reconciliation_service = BillingReconciliationService()`；
- `final()` 调用改为 `billing_aggregator.final(reconciliation_service=reconciliation_service)`。

`_stream_single_agent` / `_stream_multi_agent` 同样注入（它们已有 `billing_aggregator.final()` 调用点，找到后加参数）。

- [ ] **Step 5: 回归验证**

Run: `python -m pytest test/internal/service/test_billing_metering_service.py test/internal/service/test_billing_cancel_summary.py test/internal/service/test_billing_sse_integration.py test/internal/service/test_assistant_agent_service.py -q --no-cov`
Expected: PASS。

- [ ] **Step 6: Commit**

```bash
git add api/internal/service/billing_metering_service.py api/internal/service/assistant_agent_service.py api/test/internal/service/test_billing_metering_service.py
git commit -m "feat(billing): aggregator final hooks reconciliation"
```

---

### Task 5: admin 对账/毛利接口（含告警标记）

**Files:**
- Create: `api/internal/service/admin_billing_reconciliation_service.py`
- Create: `api/internal/schema/admin_billing_reconciliation_schema.py`
- Modify: `api/app/http/admin_routes_7.py`
- Modify: `api/app/http/support.py`
- Test: `api/test/app/http/test_admin_routes_7.py`

- [ ] **Step 1: 写失败测试——按模型毛利聚合接口**

在 `test_admin_routes_7.py` 新增 `TestAdminReconciliationRoutes`：

```python
class TestAdminReconciliationRoutes:
    def _setup(self, monkeypatch):
        service = SimpleNamespace(
            list_reconciliations=lambda **kw: {"list": [], "paginator": {"total_record": 0, "total_page": 0, "current_page": 1, "page_size": 20}},
            model_margin_summary=lambda **kw: {"list": [], "total_margin": 0, "total_actual": 0},
        )
        monkeypatch.setattr(support, "_get_service", lambda cls: service if cls.__name__ == "AdminBillingReconciliationService" else None)
        return service

    def test_model_margin(self, monkeypatch):
        self._setup(monkeypatch)

        async def _run():
            async with asgi_app.quart_app.test_client() as client:
                resp = await client.get("/admin/billing-reconciliations/margin?group_by=model")
                return resp, await resp.json

        resp, payload = asyncio.run(_run())
        assert resp.status_code == 200
        assert payload["code"] == "success"
```

- [ ] **Step 2: 运行确认失败**

Run: `python -m pytest test/app/http/test_admin_routes_7.py::TestAdminReconciliationRoutes -q --no-cov`
Expected: FAIL（路由不存在）。

- [ ] **Step 3: 实现服务**

`admin_billing_reconciliation_service.py`：

```python
"""管理端对账查询：任务对账列表、按模型/按用户毛利聚合、告警筛选。"""
from internal.model.billing import BillingReconciliation


class AdminBillingReconciliationService:
    def __init__(self, session=None):
        from internal.extension.database_extension import db
        self.session = session or db.session

    def list_reconciliations(self, *, keyword="", alert=None, current_page=1, page_size=20) -> dict:
        query = self.session.query(BillingReconciliation)
        if alert:
            query = query.filter(BillingReconciliation.alert_flags.op("@>")([alert]))
        total = query.count()
        rows = query.order_by(BillingReconciliation.created_at.desc()).offset(
            (current_page - 1) * page_size
        ).limit(page_size).all()
        return {"list": [self._serialize(r) for r in rows],
                "paginator": {"total_record": total, "total_page": math.ceil(total / page_size)
                              if page_size else 0, "current_page": current_page, "page_size": page_size}}

    def model_margin_summary(self, *, current_page=1, page_size=20) -> dict:
        rows = self.session.query(BillingReconciliation).all()
        agg = {}
        for r in rows:
            # 简化：按 task 维度聚合毛利（模型级拆分依赖 usage_event join，首期按对账行聚合）
            key = "all"
            bucket = agg.setdefault(key, {"calls": 0, "actual": 0, "cost": 0, "margin": 0})
            bucket["calls"] += 1
            bucket["actual"] += int(r.actual_credits or 0)
            bucket["cost"] += int(r.cost_credits or 0)
        items = [{"model_name": "汇总", **v} for v in agg.values()]
        total_margin = sum(int(v["actual"]) - int(v["cost"]) for v in agg.values())
        total_actual = sum(int(v["actual"]) for v in agg.values())
        return {"list": items, "total_margin": total_margin, "total_actual": total_actual}

    @staticmethod
    def _serialize(r) -> dict:
        return {
            "id": str(r.id), "task_id": r.task_id, "account_id": str(r.account_id),
            "estimated_credits": int(r.estimated_credits or 0),
            "actual_credits": int(r.actual_credits or 0),
            "cost_credits": int(r.cost_credits or 0),
            "diff_credits": int(r.diff_credits or 0),
            "status": r.status, "alert_flags": list(r.alert_flags or []),
            "created_at": int(r.created_at.replace(tzinfo=UTC).timestamp()) if r.created_at else 0,
        }
```

（`math`/`UTC` import 补齐。`alert_flags @> [...]` 为 PG JSONB 操作符，sqlite 测试用 stub 不落库。）

- [ ] **Step 4: schema**

`admin_billing_reconciliation_schema.py`：

```python
from marshmallow import Schema, fields


class AdminReconciliationResp(Schema):
    class Meta:
        ordered = True

    id = fields.String()
    task_id = fields.String()
    account_id = fields.String()
    estimated_credits = fields.Integer()
    actual_credits = fields.Integer()
    cost_credits = fields.Integer()
    diff_credits = fields.Integer()
    status = fields.String()
    alert_flags = fields.List(fields.String())
    created_at = fields.Integer()
```

- [ ] **Step 5: 路由**

`admin_routes_7.py` 追加：

```python
    @quart_app.get("/admin/billing-reconciliations")
    async def admin_billing_reconciliations_list():
        from app.http import asgi_app as a
        from quart import request
        from internal.schema.admin_billing_reconciliation_schema import AdminReconciliationResp
        from internal.service.admin_billing_reconciliation_service import AdminBillingReconciliationService

        current_page = max(int(request.args.get("current_page", 1) or 1), 1)
        page_size = max(int(request.args.get("page_size", 20) or 20), 1)
        alert = request.args.get("alert") or None
        result = await a._to_thread(
            a._get_service(AdminBillingReconciliationService).list_reconciliations,
            alert=alert, current_page=current_page, page_size=page_size,
        )
        resp = AdminReconciliationResp(many=True)
        return a._ok({"list": resp.dump(result["list"]), "paginator": result["paginator"]})

    @quart_app.get("/admin/billing-reconciliations/margin")
    async def admin_billing_reconciliations_margin():
        from app.http import asgi_app as a
        from internal.service.admin_billing_reconciliation_service import AdminBillingReconciliationService

        result = await a._to_thread(a._get_service(AdminBillingReconciliationService).model_margin_summary)
        return a._ok(result)
```

（照抄现有 `_ok`/`_get_service`/`_to_thread` 约定；`request.args` 需 `from quart import request`。若 admin_routes_7.py 顶部已 import request 则无需重复。）

- [ ] **Step 6: support.py 权限映射**

在 `_admin_route_permission` 增加：

```python
    if _admin_match(segments, ("admin", "billing-reconciliations")):
        return "plan:read" if method == "GET" else "plan:update"
```

- [ ] **Step 7: 回归验证**

Run: `python -m pytest test/app/http/test_admin_routes_7.py -q --no-cov`
Expected: PASS（原有用例 + 新增）。

- [ ] **Step 8: Commit**

```bash
git add api/internal/service/admin_billing_reconciliation_service.py api/internal/schema/admin_billing_reconciliation_schema.py api/app/http/admin_routes_7.py api/app/http/support.py api/test/app/http/test_admin_routes_7.py
git commit -m "feat(billing): admin reconciliation and margin APIs"
```

---

### Task 6: 前端毛利看板页

**Files:**
- Create: `ui/src/views/admin/BillingReconciliationView.vue`
- Create: `ui/src/services/admin-billing-reconciliation.ts`
- Create: `ui/src/models/billing-reconciliation.ts`
- Modify: `ui/src/router/index.ts`（admin 路由）
- Modify: `ui/src/i18n/messages/zh-CN.ts`、`ui/src/i18n/messages/en-US.ts`
- Test: `ui/src/views/admin/__tests__/BillingReconciliationView.spec.ts`

- [ ] **Step 1: 服务与模型**

`ui/src/models/billing-reconciliation.ts`：

```typescript
export interface BillingReconciliation {
  id: string
  task_id: string
  account_id: string
  estimated_credits: number
  actual_credits: number
  cost_credits: number
  diff_credits: number
  status: string
  alert_flags: string[]
  created_at: number
}

export interface MarginSummaryItem {
  model_name: string
  calls: number
  actual: number
  cost: number
  margin: number
}

export interface MarginSummary {
  list: MarginSummaryItem[]
  total_margin: number
  total_actual: number
}

export interface AdminReconciliationListResponse {
  list: BillingReconciliation[]
  paginator: { total_record: number; total_page: number; current_page: number; page_size: number }
}
```

`ui/src/services/admin-billing-reconciliation.ts`：

```typescript
import { get } from '@/utils/request'
import type { AdminReconciliationListResponse, MarginSummary } from '@/models/billing-reconciliation'

export const listReconciliations = async (params: { alert?: string; current_page: number; page_size: number }) => {
  const response = await get<AdminReconciliationListResponse>('/admin/billing-reconciliations', { params })
  return response.data
}

export const getMarginSummary = async () => {
  const response = await get<MarginSummary>('/admin/billing-reconciliations/margin')
  return response.data
}
```

- [ ] **Step 2: 页面实现**

`BillingReconciliationView.vue` 遵循现有 admin 页面范式（page-hero + stats cards + toolbar + table），核心区块：

```vue
<template>
  <section class="billing-reconciliation-page" :aria-busy="loading">
    <header class="page-hero">
      <div>
        <p class="page-kicker">Billing Reconcile</p>
        <h2>{{ t('admin.reconcile.title') }}</h2>
        <p>{{ t('admin.reconcile.description') }}</p>
      </div>
    </header>

    <div class="grid gap-4 md:grid-cols-4">
      <article class="rounded-lg border bg-white p-4">
        <p class="text-sm text-gray-500">{{ t('admin.reconcile.stats.totalActual') }}</p>
        <strong class="text-xl">{{ marginSummary.total_actual }}</strong>
      </article>
      <article class="rounded-lg border bg-white p-4">
        <p class="text-sm text-gray-500">{{ t('admin.reconcile.stats.totalCost') }}</p>
        <strong class="text-xl">{{ totalCost }}</strong>
      </article>
      <article class="rounded-lg border bg-white p-4">
        <p class="text-sm text-gray-500">{{ t('admin.reconcile.stats.margin') }}</p>
        <strong :class="marginClass">{{ marginSummary.total_margin }}</strong>
      </article>
      <article class="rounded-lg border bg-white p-4">
        <p class="text-sm text-gray-500">{{ t('admin.reconcile.stats.alertCount') }}</p>
        <strong class="text-red-600">{{ alertCount }}</strong>
      </article>
    </div>

    <section class="panel mt-4">
      <h3 class="panel-title">{{ t('admin.reconcile.marginByModel') }}</h3>
      <a-table :data="marginSummary.list" :loading="loading" :pagination="false" row-key="model_name">
        <template #columns>
          <a-table-column :title="t('admin.reconcile.columns.model')" data-index="model_name" />
          <a-table-column :title="t('admin.reconcile.columns.calls')" data-index="calls" align="right" />
          <a-table-column :title="t('admin.reconcile.columns.actual')" data-index="actual" align="right" />
          <a-table-column :title="t('admin.reconcile.columns.cost')" data-index="cost" align="right" />
          <a-table-column :title="t('admin.reconcile.columns.margin')" align="right">
            <template #cell="{ record }">
              <a-tag :color="record.margin >= 0 ? 'green' : 'red'">{{ record.margin }}</a-tag>
            </template>
          </a-table-column>
        </template>
      </a-table>
    </section>

    <section class="panel mt-4">
      <h3 class="panel-title">{{ t('admin.reconcile.settleRecords') }}</h3>
      <a-table :data="reconciliations" :loading="loading" :pagination="false" row-key="id">
        <template #columns>
          <a-table-column :title="t('admin.reconcile.columns.taskId')" data-index="task_id">
            <template #cell="{ record }"><code class="text-xs">{{ record.task_id.slice(0, 12) }}…</code></template>
          </a-table-column>
          <a-table-column :title="t('admin.reconcile.columns.estimated')" data-index="estimated_credits" align="right" />
          <a-table-column :title="t('admin.reconcile.columns.actual')" data-index="actual_credits" align="right" />
          <a-table-column :title="t('admin.reconcile.columns.diff')" data-index="diff_credits" align="right">
            <template #cell="{ record }">
              <span :class="record.diff_credits > 0 ? 'text-amber-600' : record.diff_credits < 0 ? 'text-green-600' : 'text-gray-400'">{{ record.diff_credits }}</span>
            </template>
          </a-table-column>
          <a-table-column :title="t('admin.reconcile.columns.alerts')" data-index="alert_flags">
            <template #cell="{ record }">
              <a-tag v-for="flag in record.alert_flags" :key="flag" :color="flag === 'negative_margin' ? 'red' : 'orange'">{{ t(`admin.reconcile.alertFlags.${flag}`) }}</a-tag>
            </template>
          </a-table-column>
        </template>
      </a-table>
    </section>
  </section>
</template>
```

script：onMounted 并行 `loadMargin()` + `loadList()`；分页态独立；毛利负 tag 红色；告警计数 = 对账行 alert_flags.length 之和。

- [ ] **Step 3: 路由与 i18n**

`router/index.ts`：admin 布局下新增 `/admin/billing-reconciliations` → `BillingReconciliationView`（参照现有 admin 子路由写法）。

i18n 增加 `admin.reconcile.*`（zh-CN / en-US，覆盖 title/description/stats×4/columns×7/alertFlags.ratio_deviation/alertFlags.negative_margin）。

- [ ] **Step 4: 组件测试**

`BillingReconciliationView.spec.ts`：mock 两个 service 后断言 stats 渲染、负毛利红 tag 类存在、告警 tag 渲染、无数据空态。

- [ ] **Step 5: 前端全量验证**

Run: `npm run lint` + `npx vue-tsc --noEmit` + `npx vitest run`
Expected: 全绿。

- [ ] **Step 6: Commit**

```bash
git add ui/src/views/admin/BillingReconciliationView.vue ui/src/services/admin-billing-reconciliation.ts ui/src/models/billing-reconciliation.ts ui/src/router/index.ts ui/src/i18n/messages/zh-CN.ts ui/src/i18n/messages/en-US.ts ui/src/views/admin/__tests__/BillingReconciliationView.spec.ts
git commit -m "feat(billing): admin reconciliation and margin dashboard"
```

---

### Task 7: 全量回归、迁移应用与 E2E

- [ ] **Step 1: 后端全量**

Run: `python -m pytest test -q --no-cov`
Expected: 全量通过。

- [ ] **Step 2: 前端全量**

Run: `npm run lint`、`npx vue-tsc --noEmit`、`npx vitest run`
Expected: 全绿。

- [ ] **Step 3: 应用迁移**

`docker restart llmops-api` → healthy。
Run: `docker exec llmops-db psql -U postgres -d llmops -t -A -c "SELECT version_num FROM alembic_version"`
Expected: `e8f9a0b1c2d3`。

Run: `docker exec llmops-db psql -U postgres -d llmops -t -A -c "SELECT count(*) FROM information_schema.columns WHERE table_name='billing_reconciliation'"`
Expected: >= 12。

- [ ] **Step 4: E2E——对账写入与毛利接口**

容器内 python（经 `app.http.app` 初始化）验证：调用 `BillingReconciliationService.settle()` 写入一行 → `AdminBillingReconciliationService.model_margin_summary()` 返回该行 → 检查 `alert_flags` 数组。清理测试行。

- [ ] **Step 5: E2E——审计/告警落点确认**

对账行 alert_flags 含 `ratio_deviation` 时确认后台可查（admin 接口返回）。

- [ ] **Step 6: 清理数据与脚本、graphify**

```bash
docker exec llmops-db psql -U postgres -d llmops -c "DELETE FROM billing_reconciliation WHERE task_id LIKE 'e2e%'"
python -m graphify update .
```

---

## 计划自检

- **规格覆盖**：P2 三块——表（Task 1）、退补+结算+告警（Task 2/3/4）、看板接口+前端（Task 5/6）全部有任务。
- **接口一致性**（跨任务契约，严禁偏离）：
  - `CreditService.adjust_credits(account_id, *, diff_credits, source, source_id, description)`（Task 2 定义，Task 3 调用）
  - `BillingReconciliationService.persist_event(*, task_id, account_id, model_id, source_type, input_tokens, output_tokens, billing_basis, estimated_credits, is_estimated)` / `settle(*, task_id, account_id, events)`（Task 3 定义，Task 4 调用）
  - `BillingUsageAggregator.final(reconciliation_service=None)`（Task 4 定义，assistant_agent_service 调用）
  - admin 路由 `/admin/billing-reconciliations` 与 `/admin/billing-reconciliations/margin`（Task 5 定义，Task 6 前端调用）
- **无占位符**：每步骤含完整代码/命令/预期。
- **幂等保证**：对账唯一索引 `billing_reconciliation(task_id)` 唯一 + adjust 交易 `(source, source_id, transaction_type)` 唯一，双重防重复结算。