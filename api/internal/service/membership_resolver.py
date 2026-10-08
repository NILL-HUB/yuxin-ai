"""会员生效解析（**单一权威入口**）。

为什么必须唯一：一个账号可以同时存在多条会员记录（免费体验卡 + 付费卡、不同来源、
不同到期时间），而「当前生效会员」决定**身份标识、套餐额度可用性、存储/功能权益、
分销资格、自动续费口径**。此前这些判定在 8 处各写一份
`order_by(expires_at.desc()).first()`——既无档位优先级、也无确定性 tie-break：
两条 active 行 expires_at 相同时由 PostgreSQL 任选，实测出现
「高级会员被免费体验卡顶掉 → 身份回落试用/免费，但到期时间仍显示付费卡的 2027」
的错乱（2026-10-08 排查 NILL 账号）。

规则（本模块是唯一实现，任何消费方不得再自行排序）：

1. **生效优先**：`status='active'` 且 `expires_at >= now` 的行排在最前；
2. **档位优先**：生效行按套餐价值取最高——`plan.price desc` → `plan.grant_token_credits desc`，
   免费/体验卡不可能顶掉付费卡；
3. **确定性**：同价值再按 `expires_at desc` → `created_at desc` → `id desc`，
   同一份数据在任何时刻都解析出同一条记录（不再依赖 PG 的任意返回顺序）；
4. **无生效行时**返回「最近一条」（按到期时间/创建时间倒序），供 UI 展示已过期状态；
   调用方若需要「当前确实有效」的语义，用 `resolve_effective_membership` 或
   `has_active_membership`，不要自己再判一遍。

写入侧同样唯一：`activate_or_extend_membership` 是开通/续期的唯一实现——
只动**本套餐这一条**记录（同套餐且生效中 → 顺延到期时间；否则新建一条），
绝不触碰其它套餐的会员行（体验卡与付费卡并存是合法状态，谁生效由本模块裁决）。
"""
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

from sqlalchemy import and_, case

from internal.model.billing import Membership, Plan, membership_is_effective

__all__ = [
    "activate_or_extend_membership",
    "expire_due_memberships",
    "find_membership_by_source",
    "has_active_membership",
    "resolve_current_membership",
    "resolve_effective_membership",
]


def _utcnow() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def _ordered_account_memberships(session: Any, account_id: UUID, now: datetime):
    """账号全部会员行，按「生效优先 → 档位价值 → 到期/创建时间」确定性排序。"""
    return (
        session.query(Membership)
        .outerjoin(Plan, Plan.id == Membership.plan_id)
        .filter(Membership.account_id == account_id)
        .order_by(
            case(
                (
                    and_(
                        Membership.status == "active",
                        Membership.expires_at.isnot(None),
                        Membership.expires_at >= now,
                    ),
                    0,
                ),
                else_=1,
            ),
            Plan.price.desc().nullslast(),
            Plan.grant_token_credits.desc().nullslast(),
            Membership.expires_at.desc().nullslast(),
            Membership.created_at.desc().nullslast(),
            Membership.id.desc(),
        )
    )


def resolve_current_membership(
    session: Any,
    account_id: UUID,
    *,
    now: datetime | None = None,
) -> Membership | None:
    """当前会员（用于身份标识/额度/续费口径）：优先生效行，同档位取价值最高。

    无生效行时返回最近一条（已过期）记录，调用方需用 `membership.is_active`
    判断是否真正生效——这是「到期回退免费用户」展示所需的行为。
    """
    effective_now = now or _utcnow()
    return _ordered_account_memberships(session, account_id, effective_now).first()


def resolve_effective_membership(
    session: Any,
    account_id: UUID,
    *,
    now: datetime | None = None,
) -> Membership | None:
    """当前**确实生效**的会员（active 且未过期）；无则 None。

    权益类判定（存储/功能权益、分销资格）用本函数，不要用 `resolve_current_membership`
    再自行判 status——两处判定口径一旦分叉就会出现「有权益但身份是免费」的矛盾态。
    """
    effective_now = now or _utcnow()
    membership = _ordered_account_memberships(session, account_id, effective_now).first()
    if membership is None or not membership_is_effective(membership, effective_now):
        return None
    return membership


def has_active_membership(session: Any, account_id: UUID, *, now: datetime | None = None) -> bool:
    """账号是否有生效中的会员（分销资格等布尔判定用）。"""
    return resolve_effective_membership(session, account_id, now=now) is not None


def find_membership_by_source(
    session: Any,
    account_id: UUID,
    *,
    source: str,
    source_id: UUID,
) -> Membership | None:
    """按来源精确定位会员行（退款回收权益等场景）。

    不能用「取到期时间最大的那条」代替：多会员并存时它可能命中的是另一张卡，
    导致「该退的没退、不该退的被退」。
    """
    return (
        session.query(Membership)
        .filter(
            Membership.account_id == account_id,
            Membership.source == source,
            Membership.source_id == source_id,
        )
        .order_by(Membership.created_at.desc())
        .first()
    )


def expire_due_memberships(
    session: Any,
    account_id: UUID,
    *,
    now: datetime | None = None,
) -> list[Membership]:
    """把已自然到期仍标 active 的会员行收敛为 expired，返回被收敛的行。

    只改状态（不做额度清理）——额度清理由调用方在同一事务内决定，
    因为「是否还有其它生效会员」需要按本模块的解析口径判断。
    """
    effective_now = now or _utcnow()
    memberships = (
        session.query(Membership)
        .filter(Membership.account_id == account_id)
        .all()
    )
    overdue = [
        item
        for item in memberships
        if item.status == "active"
        and item.expires_at is not None
        and item.expires_at < effective_now
    ]
    for item in overdue:
        item.status = "expired"
        item.updated_at = effective_now
    return overdue


def activate_or_extend_membership(
    session: Any,
    account_id: UUID,
    plan: Plan,
    *,
    source: str,
    source_id: UUID,
    now: datetime | None = None,
) -> Membership:
    """开通或续期会员（**唯一实现**：兑换卡密与购买订单共用）。

    - 同一套餐且仍在生效中 → 顺延到期时间（续费）；
    - 否则新建一条会员记录（套餐切换、过期后重新购买）；
    - **不触碰其它套餐的会员行**：体验卡与付费卡并存合法，谁生效由解析器裁决。
    """
    effective_now = now or _utcnow()
    duration_days = int(plan.duration_days or 0)

    membership = (
        session.query(Membership)
        .filter(Membership.account_id == account_id, Membership.plan_id == plan.id)
        .order_by(Membership.expires_at.desc().nullslast(), Membership.created_at.desc())
        .first()
    )
    if (
        membership is not None
        and membership.status == "active"
        and membership.expires_at is not None
        and membership.expires_at > effective_now
    ):
        membership.expires_at = membership.expires_at + timedelta(days=duration_days)
        membership.source = source
        membership.source_id = source_id
        membership.updated_at = effective_now
        return membership

    membership = Membership(
        account_id=account_id,
        plan_id=plan.id,
        status="active",
        started_at=effective_now,
        expires_at=effective_now + timedelta(days=duration_days),
        source=source,
        source_id=source_id,
    )
    session.add(membership)
    return membership
