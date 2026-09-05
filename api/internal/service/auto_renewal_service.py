from datetime import UTC, datetime, timedelta
from uuid import UUID

from internal.exception import FailException, NotFoundException
from internal.extension.database_extension import db
from internal.model.billing import CreditAccount, Membership, Plan
from internal.model.distribution import AutoRenewal

MAX_FAIL_COUNT = 3
CREDITS_RENEW_COOLDOWN_HOURS = 24


class AutoRenewalService:
    """自动续费 / 连续包月。

    - membership：到期触发（expires_at - 1 天）；复购同一套餐。
    - credits（永久算力包）：余量触发——permanent_credit ≤ grant×threshold% 时复购同一算力包。
    - 支付走统一订单（pay_method=balance, order_source=auto_renew）→ 扣余额+权益+即时返佣。
    - wechatpay/alipay 周期扣款预留（pay_method 字段与分发分支），未接入时明确拒绝开通。
    """

    def __init__(self, session=None, order_service=None):
        self.session = session or db.session
        self._order_service = order_service

    def _get_order_service(self):
        if self._order_service is None:
            from internal.service.order_service import OrderService

            self._order_service = OrderService(session=self.session)
        return self._order_service

    # ------------------------------------------------------------------
    # 开通 / 管理
    # ------------------------------------------------------------------
    def create(self, account_id: UUID, plan_id: UUID, pay_method: str = "balance") -> AutoRenewal:
        plan = self.session.query(Plan).filter(Plan.id == plan_id).one_or_none()
        if plan is None or not plan.is_active:
            raise FailException("套餐不存在或已禁用")
        plan_type = (plan.plan_type or "membership").strip().lower()
        if plan_type not in ("membership", "credits"):
            raise FailException("该套餐不支持自动续费")
        raw_method = (pay_method or "").strip().lower()
        if raw_method != "balance":
            raise FailException("微信/支付宝自动续费暂未开通，请使用余额自动续费")

        existing = (
            self.session.query(AutoRenewal)
            .filter(
                AutoRenewal.account_id == account_id,
                AutoRenewal.plan_id == plan.id,
                AutoRenewal.status.in_(("active", "paused", "failed")),
            )
            .one_or_none()
        )
        if existing is not None and existing.status == "active":
            raise FailException("该套餐已开通自动续费")
        if existing is not None:
            existing.status = "active"
            existing.pay_method = raw_method
            existing.fail_count = 0
            if plan_type == "membership":
                existing.next_renew_at = self._compute_membership_next_renew(account_id, plan)
            return existing

        renewal = AutoRenewal(
            account_id=account_id,
            plan_id=plan.id,
            plan_type=plan_type,
            pay_method=raw_method,
            status="active",
            next_renew_at=self._compute_membership_next_renew(account_id, plan) if plan_type == "membership" else None,
        )
        self.session.add(renewal)
        self.session.commit()
        return renewal

    def list_mine(self, account_id: UUID) -> list[dict]:
        rows = (
            self.session.query(AutoRenewal)
            .filter(AutoRenewal.account_id == account_id)
            .order_by(AutoRenewal.created_at.desc())
            .all()
        )
        plans = {
            plan.id: plan
            for plan in self.session.query(Plan).filter(Plan.id.in_([row.plan_id for row in rows])).all()
        } if rows else {}
        return [self._serialize(row, plans.get(row.plan_id)) for row in rows]

    def set_status(self, account_id: UUID, renewal_id: UUID, action: str) -> AutoRenewal:
        renewal = (
            self.session.query(AutoRenewal)
            .filter(AutoRenewal.id == renewal_id, AutoRenewal.account_id == account_id)
            .one_or_none()
        )
        if renewal is None:
            raise NotFoundException("自动续费记录不存在")
        if renewal.status == "cancelled":
            raise FailException("已取消的自动续费不可操作")
        if action == "pause":
            renewal.status = "paused"
        elif action == "resume":
            renewal.status = "active"
        elif action == "cancel":
            renewal.status = "cancelled"
        else:
            raise FailException("不支持的操作")
        self.session.commit()
        return renewal

    # ------------------------------------------------------------------
    # 触发执行
    # ------------------------------------------------------------------
    def try_renew_membership(self, renewal: AutoRenewal) -> str:
        if not renewal.is_active or renewal.plan_type != "membership":
            return "skipped"
        if renewal.next_renew_at and renewal.next_renew_at > self._now():
            return "skipped"
        return self._run_renew(renewal)

    def check_credits_threshold(self, account_id: UUID) -> str:
        """算力余量触发：permanent_credit ≤ grant×threshold% 时复购同一算力包（短冷却防重复触发）。"""
        renewals = (
            self.session.query(AutoRenewal)
            .filter(
                AutoRenewal.account_id == account_id,
                AutoRenewal.plan_type == "credits",
                AutoRenewal.status == "active",
            )
            .all()
        )
        if not renewals:
            return "skipped"
        credit_account = (
            self.session.query(CreditAccount)
            .filter(CreditAccount.account_id == account_id)
            .one_or_none()
        )
        permanent = int(credit_account.permanent_credit or 0) if credit_account else 0
        result = "skipped"
        for renewal in renewals:
            plan = self.session.query(Plan).filter(Plan.id == renewal.plan_id).one_or_none()
            if plan is None:
                continue
            threshold = int(plan.auto_renew_threshold_percent or 5)
            grant = int(plan.grant_token_credits or 0)
            if grant <= 0:
                continue
            if permanent <= max(int(grant * threshold / 100), 1):
                result = self._run_renew(renewal)
        return result

    def run_due_scan(self) -> dict:
        """Celery 兜底扫描：到期的 membership 续费 + 达标未触发的余量重扫。"""
        due_memberships = (
            self.session.query(AutoRenewal)
            .filter(
                AutoRenewal.plan_type == "membership",
                AutoRenewal.status == "active",
                AutoRenewal.next_renew_at <= self._now(),
            )
            .all()
        )
        renewed, failed = 0, 0
        for renewal in due_memberships:
            result = self._run_renew(renewal)
            if result == "failed":
                failed += 1
            else:
                renewed += 1
        credit_account_ids = [
            row.account_id
            for row in self.session.query(AutoRenewal.account_id)
            .filter(AutoRenewal.plan_type == "credits", AutoRenewal.status == "active")
            .distinct()
            .all()
        ]
        for account_id in credit_account_ids:
            self.check_credits_threshold(account_id)
        return {"membership_renewed": renewed, "membership_failed": failed, "credits_accounts_scanned": len(credit_account_ids)}

    # ------------------------------------------------------------------
    # 内部
    # ------------------------------------------------------------------
    def _run_renew(self, renewal: AutoRenewal) -> str:
        """执行续费：统一订单（balance/auto_renew）→ 权益 + 即时返佣。余额不足计失败。"""
        now = self._now()
        if renewal.renew_count > 0 and renewal.last_renewed_at and now - renewal.last_renewed_at < timedelta(seconds=600):
            return "cooldown"
        try:
            order_service = self._get_order_service()
            order = order_service.create_order(renewal.account_id, renewal.plan_id, "balance", order_source="auto_renew")
            order_service.pay_with_balance(order)
            renewal.renew_count = int(renewal.renew_count or 0) + 1
            renewal.last_renewed_at = now
            renewal.fail_count = 0
            if renewal.plan_type == "membership":
                renewal.next_renew_at = self._next_membership_expires(renewal.account_id, renewal.plan_id)
            self.session.commit()
            return "renewed"
        except FailException:
            self.session.rollback()
            renewal.fail_count = int(renewal.fail_count or 0) + 1
            if int(renewal.fail_count) >= MAX_FAIL_COUNT:
                renewal.status = "failed"
            try:
                self.session.commit()
            except Exception:
                self.session.rollback()
            return "failed"

    def _compute_membership_next_renew(self, account_id: UUID, plan: Plan) -> datetime:
        membership = self._current_membership(account_id)
        now = self._now()
        if membership is not None and membership.is_active and membership.expires_at:
            base = membership.expires_at
        else:
            base = now + timedelta(days=int(plan.duration_days or 0))
        lead_days = int(plan.auto_renew_threshold_days or 1)
        return base - timedelta(days=max(lead_days, 1))

    def _next_membership_expires(self, account_id: UUID, plan_id: UUID | None = None) -> datetime:
        membership = self._current_membership(account_id)
        lead_days = 1
        if plan_id is not None:
            plan = self.session.query(Plan).filter(Plan.id == plan_id).one_or_none()
            lead_days = int(plan.auto_renew_threshold_days or 1) if plan is not None else 1
        if membership is not None and membership.expires_at:
            return membership.expires_at - timedelta(days=max(lead_days, 1))
        return self._now() + timedelta(days=30)

    def _current_membership(self, account_id: UUID) -> Membership | None:
        return (
            self.session.query(Membership)
            .filter(Membership.account_id == account_id)
            .order_by(Membership.expires_at.desc())
            .first()
        )

    def _serialize(self, renewal: AutoRenewal, plan: Plan | None) -> dict:
        trigger = "到期" if renewal.plan_type == "membership" else "余量"
        return {
            "id": str(renewal.id),
            "plan_id": str(renewal.plan_id),
            "plan_name": plan.name if plan else "",
            "plan_type": renewal.plan_type,
            "pay_method": renewal.pay_method,
            "status": renewal.status,
            "trigger": trigger,
            "threshold_percent": int(plan.auto_renew_threshold_percent or 5) if plan and renewal.plan_type == "credits" else None,
            "threshold_days": int(plan.auto_renew_threshold_days or 1) if plan and renewal.plan_type == "membership" else None,
            "next_renew_at": self._timestamp(renewal.next_renew_at),
            "last_renewed_at": self._timestamp(renewal.last_renewed_at),
            "renew_count": int(renewal.renew_count or 0),
            "fail_count": int(renewal.fail_count or 0),
        }

    @staticmethod
    def _now() -> datetime:
        return datetime.now(UTC).replace(tzinfo=None)

    @staticmethod
    def _timestamp(value) -> int | None:
        if value is None:
            return None
        return int(value.replace(tzinfo=UTC).timestamp())