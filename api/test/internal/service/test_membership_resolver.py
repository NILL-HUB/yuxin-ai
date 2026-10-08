"""会员解析器（membership_resolver）：解析优先级 / 续期 / 到期收敛的权威语义。

**为什么必须真库跑**：解析优先级发生在 SQL 的 `ORDER BY` 里
（生效优先 → 档位价值 → 确定性 tie-break），替身桩只能验证「返回了哪条」，
验证不了「排序规则本身」——而 2026-10-08 的线上错乱（高级会员被免费体验卡顶掉、
身份回落免费但到期时间仍显示付费卡的 2027）正是排序规则缺失导致的：
两条 active 行 expires_at 相同时，PostgreSQL 任意返回一条。

全部用例在显式事务内 `rollback`，绝不落库；无可用 PostgreSQL 时跳过（不制造假绿）。
"""
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import UUID, uuid4

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from internal.model.billing import Membership, Plan, membership_is_effective
from internal.service import membership_resolver as resolver


def _engine():
    """可连的同步引擎；无可用 PostgreSQL 时返回 None（调用方 skip）。"""
    from config import Config

    uri = getattr(Config(), "SQLALCHEMY_DATABASE_URI", "") or ""
    if not uri.startswith("postgresql"):
        return None
    try:
        engine = create_engine(uri)
        with engine.connect():
            pass
        return engine
    except Exception:
        return None


@pytest.fixture()
def session():
    engine = _engine()
    if engine is None:
        pytest.skip("无可用 PostgreSQL，跳过会员解析真库校验")
    db_session = Session(engine)
    try:
        yield db_session
    finally:
        db_session.rollback()
        db_session.close()
        engine.dispose()


def _utcnow() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def _plan(session, *, price, credits, days=30) -> Plan:
    plan = Plan(
        code=f"TST{uuid4().hex[:10].upper()}",
        name="测试套餐",
        plan_type="membership",
        price=Decimal(str(price)),
        duration_days=days,
        grant_token_credits=credits,
        status="active",
    )
    session.add(plan)
    session.flush()
    return plan


def _membership(
    session,
    account_id: UUID,
    plan: Plan,
    *,
    status="active",
    expires_at=None,
    source="order",
    source_id=None,
    created_at=None,
) -> Membership:
    membership = Membership(
        account_id=account_id,
        plan_id=plan.id,
        status=status,
        started_at=_utcnow() - timedelta(days=1),
        expires_at=expires_at or (_utcnow() + timedelta(days=30)),
        source=source,
        source_id=source_id or uuid4(),
    )
    if created_at is not None:
        membership.created_at = created_at
    session.add(membership)
    session.flush()
    return membership


# ── 解析优先级 ────────────────────────────────────────────────────────────


def test_paid_membership_wins_when_expiries_tie(session):
    """回归 NILL 场景：体验卡与付费卡到期时间相同时，身份必须是付费档。"""
    account_id = uuid4()
    trial = _plan(session, price=0, credits=1000, days=7)
    paid = _plan(session, price=280, credits=150000, days=30)
    same_expiry = _utcnow() + timedelta(days=89)
    trial_row = _membership(session, account_id, trial, expires_at=same_expiry, source="order")
    paid_row = _membership(session, account_id, paid, expires_at=same_expiry, source="redeem_code")

    resolved = resolver.resolve_current_membership(session, account_id)

    assert resolved is not None
    assert resolved.id == paid_row.id
    assert resolved.id != trial_row.id


def test_higher_value_plan_wins_even_with_later_expiry_on_other(session):
    """档位优先于到期时间：付费卡（价值高）不会被到期更晚的体验卡顶掉。"""
    account_id = uuid4()
    trial = _plan(session, price=0, credits=1000, days=7)
    paid = _plan(session, price=280, credits=150000, days=30)
    _membership(session, account_id, trial, expires_at=_utcnow() + timedelta(days=365))
    paid_row = _membership(session, account_id, paid, expires_at=_utcnow() + timedelta(days=10))

    assert resolver.resolve_current_membership(session, account_id).id == paid_row.id


def test_effective_membership_beats_expired_higher_tier(session):
    """生效优先：付费卡已过期、体验卡生效中 → 当前身份是体验卡（不是过期的付费卡）。"""
    account_id = uuid4()
    trial = _plan(session, price=0, credits=1000, days=7)
    paid = _plan(session, price=280, credits=150000, days=30)
    _membership(session, account_id, paid, status="expired", expires_at=_utcnow() - timedelta(days=1))
    trial_row = _membership(session, account_id, trial, expires_at=_utcnow() + timedelta(days=3))

    assert resolver.resolve_current_membership(session, account_id).id == trial_row.id
    assert resolver.resolve_effective_membership(session, account_id).id == trial_row.id


def test_effective_membership_is_none_when_all_expired(session):
    account_id = uuid4()
    paid = _plan(session, price=280, credits=150000)
    expired_row = _membership(session, account_id, paid, status="expired", expires_at=_utcnow() - timedelta(days=2))

    # 展示口径仍能拿到「最近一条」用于显示已过期状态
    assert resolver.resolve_current_membership(session, account_id).id == expired_row.id
    # 权益口径必须为空
    assert resolver.resolve_effective_membership(session, account_id) is None
    assert resolver.has_active_membership(session, account_id) is False


# ── 到期收敛 ──────────────────────────────────────────────────────────────


def test_expire_due_memberships_converges_only_overdue_rows(session):
    account_id = uuid4()
    paid = _plan(session, price=280, credits=150000)
    trial = _plan(session, price=0, credits=1000, days=7)
    overdue = _membership(session, account_id, trial, expires_at=_utcnow() - timedelta(minutes=1))
    alive = _membership(session, account_id, paid, expires_at=_utcnow() + timedelta(days=30))

    changed = resolver.expire_due_memberships(session, account_id)

    assert [row.id for row in changed] == [overdue.id]
    assert overdue.status == "expired"
    assert alive.status == "active"


# ── 开通 / 续期 ───────────────────────────────────────────────────────────


def test_activate_same_plan_extends_and_keeps_other_rows_untouched(session):
    """续费只动本套餐那一条：体验卡行不得被续费动作改写（NILL 数据错乱的直接成因）。"""
    account_id = uuid4()
    trial = _plan(session, price=0, credits=1000, days=7)
    paid = _plan(session, price=280, credits=150000, days=30)
    trial_expiry = _utcnow() - timedelta(days=30)
    trial_row = _membership(session, account_id, trial, status="expired", expires_at=trial_expiry)
    paid_row = _membership(session, account_id, paid, expires_at=_utcnow() + timedelta(days=10))
    before = paid_row.expires_at

    result = resolver.activate_or_extend_membership(
        session, account_id, paid, source="order", source_id=uuid4()
    )

    assert result.id == paid_row.id
    assert result.expires_at == before + timedelta(days=30)  # 顺延，不是从今天重算
    assert trial_row.expires_at == trial_expiry  # 其它套餐行不受影响
    assert trial_row.status == "expired"


def test_activate_creates_new_row_for_expired_same_plan(session):
    account_id = uuid4()
    paid = _plan(session, price=280, credits=150000, days=30)
    old_row = _membership(session, account_id, paid, status="expired", expires_at=_utcnow() - timedelta(days=5))

    result = resolver.activate_or_extend_membership(
        session, account_id, paid, source="order", source_id=uuid4()
    )

    assert result.id != old_row.id
    assert result.status == "active"
    assert result.expires_at > _utcnow()
    assert old_row.status == "expired"


def test_activate_trial_does_not_touch_active_paid_membership(session):
    """兑换体验卡不得改写付费卡（否则付费身份被降级——必须由解析器裁决，而不是覆盖行）。"""
    account_id = uuid4()
    trial = _plan(session, price=0, credits=1000, days=7)
    paid = _plan(session, price=280, credits=150000, days=30)
    paid_row = _membership(session, account_id, paid, expires_at=_utcnow() + timedelta(days=30))
    before = paid_row.expires_at

    trial_row = resolver.activate_or_extend_membership(
        session, account_id, trial, source="redeem_code", source_id=uuid4()
    )

    assert trial_row.id != paid_row.id
    assert paid_row.expires_at == before
    # 解析仍应给出付费卡（价值优先）
    assert resolver.resolve_current_membership(session, account_id).id == paid_row.id


# ── 按来源定位（退款回收权益） ────────────────────────────────────────────


def test_find_membership_by_source_targets_exact_order(session):
    account_id = uuid4()
    paid = _plan(session, price=280, credits=150000)
    trial = _plan(session, price=0, credits=1000, days=7)
    order_id = uuid4()
    target = _membership(session, account_id, paid, source="order", source_id=order_id)
    # 另一条到期更晚的会员行：旧实现「取到期最大的一条」会错命中它
    _membership(
        session,
        account_id,
        trial,
        expires_at=_utcnow() + timedelta(days=365),
        source="order",
        source_id=uuid4(),
    )

    found = resolver.find_membership_by_source(
        session, account_id, source="order", source_id=order_id
    )

    assert found is not None
    assert found.id == target.id


# ── 生效判定（模型级唯一定义） ────────────────────────────────────────────


def test_membership_is_effective_matches_model_property():
    """生效判定只有一处定义：模型的 is_active 与解析器共用同一函数。"""
    now = _utcnow()
    active = Membership(status="active", expires_at=now + timedelta(days=1))
    expired = Membership(status="active", expires_at=now - timedelta(days=1))
    frozen = Membership(status="expired", expires_at=now + timedelta(days=1))

    assert membership_is_effective(active, now) is True
    assert membership_is_effective(expired, now) is False
    assert membership_is_effective(frozen, now) is False
    # 属性口径与函数口径一致（同一实现，防两处判定分叉）
    assert active.is_active is True
    assert expired.is_active is False
    assert frozen.is_active is False
