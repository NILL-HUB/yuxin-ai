import random
import string
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import UUID

from sqlalchemy.exc import IntegrityError

from internal.exception import FailException, NotFoundException
from internal.extension.database_extension import db
from internal.model.billing import CreditAccount, CreditTransaction, Membership, Plan
from internal.model.distribution import AutoRenewal, PurchaseOrder
from internal.service.payment.gateway_base import (
    PaymentChannelNotConfigured,
    get_payment_adapter,
    normalize_provider,
)

ONLINE_METHODS = ("wechat", "alipay")
BALANCE_METHOD = "balance"


def _money(value) -> Decimal:
    try:
        return Decimal(str(value or 0)).quantize(Decimal("0.01"))
    except Exception:
        return Decimal("0.00")


class OrderService:
    """统一订单：余额购买、在线支付（预留）、授权、即时返佣。

    订单支付成功（confirm_paid）后：
      - membership → 会员时长叠加 + 套餐额度 += grant + 即时返佣；
      - credits   → 永久算力 += grant + 即时返佣；
      - balance   → 余额 recharge 入账（在线充值），不返佣、不给权益。
    """

    def __init__(self, session=None, balance_service=None, distribution_service=None, payment_config_service=None):
        self.session = session or db.session
        self._balance_service = balance_service
        self._distribution_service = distribution_service
        self._payment_config_service = payment_config_service

    def _get_balance_service(self):
        if self._balance_service is None:
            from internal.service.balance_service import BalanceService

            self._balance_service = BalanceService(session=self.session)
        return self._balance_service

    def _get_distribution_service(self):
        if self._distribution_service is None:
            try:
                from internal.service.distribution_service import DistributionService

                self._distribution_service = DistributionService(session=self.session)
            except ImportError:
                return None
        return self._distribution_service

    def _get_payment_config_service(self):
        if self._payment_config_service is None:
            from internal.service.payment_config_service import PaymentConfigService

            self._payment_config_service = PaymentConfigService(session=self.session)
        return self._payment_config_service

    # ------------------------------------------------------------------
    # 订单创建与状态流转
    # ------------------------------------------------------------------
    def create_and_handle(self, account_id: UUID, plan_id: UUID, pay_method: str, order_source: str = "normal", client_ip: str = "") -> tuple:
        """创建订单并立即处理支付（单一调用，避免跨 _to_thread 会话丢失）。

        余额：创建→扣款→确认→即时返佣（commit 链在内部）；
        在线：创建→返回支付参数（订单保持 pending 持久化，等待回调）。
        返回 (order, payment_params)。
        """
        order = self.create_order(account_id, plan_id, pay_method, order_source, client_ip)
        if pay_method == BALANCE_METHOD:
            paid = self.pay_with_balance(order)
            return paid, None
        params = self.pay_with_online(order)
        return order, params

    def create_order(self, account_id: UUID, plan_id: UUID, pay_method: str, order_source: str = "normal", client_ip: str = "") -> PurchaseOrder:
        plan = self.session.query(Plan).filter(Plan.id == plan_id).one_or_none()
        if plan is None or not plan.is_active:
            raise FailException("套餐不存在或已禁用")
        raw_method = normalize_provider((pay_method or "").strip().lower())
        plan_type = (plan.plan_type or "membership").strip().lower()
        if plan_type not in ("balance", "membership", "credits"):
            raise FailException("套餐类型无效")
        if plan_type == "balance":
            if raw_method not in ONLINE_METHODS:
                raise FailException("余额充值订单仅支持在线支付")
        else:
            if raw_method not in (ONLINE_METHODS + (BALANCE_METHOD,)):
                raise FailException("不支持的支付方式")
        if raw_method in ONLINE_METHODS and not self._get_payment_config_service().is_enabled(raw_method):
            raise FailException("该支付渠道暂未开通，请先配置支付渠道")
        self._enforce_purchase_limit(account_id, plan)

        order_no = self._generate_order_no()
        order = PurchaseOrder(
            account_id=account_id,
            plan_id=plan.id,
            plan_type=plan_type,
            amount=_money(plan.price),
            pay_method=raw_method,
            order_source=order_source,
            status="pending",
            client_ip=client_ip or "",
        )
        order.order_no = order_no
        self.session.add(order)
        self.session.commit()
        return order

    def pay_with_balance(self, order: PurchaseOrder) -> PurchaseOrder:
        if order.pay_method != BALANCE_METHOD:
            raise FailException("该订单不支持余额支付")
        if order.status != "pending":
            raise FailException("订单状态不允许支付")
        balance_service = self._get_balance_service()
        account = balance_service.ensure_account(order.account_id)
        if _money(account.balance) < _money(order.amount):
            raise FailException(f"余额不足，当前余额 {account.balance} 元")
        if _money(order.amount) > 0:
            self._debit_purchase(order.account_id, order)
        return self.confirm_paid(order)

    def pay_with_online(self, order: PurchaseOrder) -> dict:
        if order.pay_method not in ONLINE_METHODS:
            raise FailException("该订单不支持在线支付")
        if order.status != "pending":
            raise FailException("订单状态不允许支付")
        if not self._get_payment_config_service().is_enabled(order.pay_method):
            raise FailException("该支付渠道暂未开通，请先配置支付渠道")
        try:
            config = self._payment_config(order.pay_method)
            adapter = get_payment_adapter(order.pay_method, config)
            return adapter.create_payment(order)
        except PaymentChannelNotConfigured as exc:
            raise FailException(str(exc)) from exc

    def confirm_paid(self, order: PurchaseOrder, transaction_id: str | None = None) -> PurchaseOrder:
        """幂等确认支付成功并履约（授权权益/充值余额/即时返佣）。"""
        if order.status == "paid":
            if transaction_id and not order.transaction_id:
                order.transaction_id = transaction_id
            return order
        if order.status != "pending":
            raise FailException("订单状态不允许确认支付")
        order.status = "paid"
        order.paid_at = self._now()
        if transaction_id:
            order.transaction_id = transaction_id
        if order.plan_type == "balance":
            self._get_balance_service().credit(
                order.account_id,
                order.amount,
                source="order",
                source_id=order.id,
                amount_type="recharge",
                description=f"在线充值余额 {order.amount} 元",
            )
        else:
            self._fulfill_rights(order)
            self._maybe_enable_auto_renewal(order)
            self._settle_commission(order)
        self._commit_idempotent()
        return order

    def cancel(self, order_no: str, account_id: UUID | None = None) -> PurchaseOrder:
        order = self._get_order(order_no, account_id)
        if order.status != "pending":
            raise FailException("仅待支付订单可取消")
        order.status = "closed"
        self._commit_idempotent()
        return order

    def mock_paid(self, order_no: str) -> PurchaseOrder:
        """本地联调：模拟支付成功（仅 ALLOW_MOCK_PAYMENT 开启时由路由注册该入口）。"""
        order = self._get_order(order_no, None)
        return self.confirm_paid(order, transaction_id=f"MOCK-{order.order_no}")

    def handle_notify(self, provider: str, payload=None, headers: dict | None = None) -> dict:
        provider = normalize_provider(provider)
        adapter = get_payment_adapter(provider, self._payment_config(provider))
        result = adapter.verify_callback(payload, headers=headers)
        if not result.get("paid") or not result.get("order_no"):
            raise FailException("回调验签失败或支付未成功")
        order = self._get_order(result["order_no"], None)
        if result.get("amount") is not None:
            expected = float(order.amount)
            actual = float(result["amount"])
            if abs(expected * 100 - actual * 100) > 1:
                raise FailException("回调金额与订单金额不一致")
        if result.get("amount_fen") is not None:
            expected_fen = int(round(float(order.amount) * 100))
            if abs(expected_fen - int(result["amount_fen"])) > 1:
                raise FailException("回调金额与订单金额不一致")
        self.confirm_paid(order, transaction_id=result.get("transaction_id"))
        return {"success": True, "order_no": order.order_no}

    def _payment_config(self, provider: str) -> dict:
        service = self._get_payment_config_service()
        config = service.get(provider)
        if config is None:
            return {}
        return service.decrypt_payload(config)

    # ------------------------------------------------------------------
    # 查询
    # ------------------------------------------------------------------
    def get_order(self, order_no: str, account_id: UUID | None = None) -> PurchaseOrder:
        return self._get_order(order_no, account_id)

    def list_orders(self, account_id: UUID, current_page: int = 1, page_size: int = 20) -> dict:
        current_page = max(int(current_page or 1), 1)
        page_size = max(min(int(page_size or 20), 50), 1)
        query = (
            self.session.query(PurchaseOrder)
            .filter(PurchaseOrder.account_id == account_id)
            .order_by(PurchaseOrder.created_at.desc())
        )
        total = query.count()
        rows = query.offset((current_page - 1) * page_size).limit(page_size).all()
        return {
            "list": [self.serialize(order) for order in rows],
            "paginator": self._paginator(total, current_page, page_size),
        }

    def serialize(self, order: PurchaseOrder) -> dict:
        return {
            "order_no": order.order_no,
            "plan_id": str(order.plan_id),
            "plan_type": order.plan_type,
            "amount": float(order.amount),
            "pay_method": order.pay_method,
            "order_source": order.order_source,
            "status": order.status,
            "transaction_id": order.transaction_id,
            "paid_at": self._timestamp(order.paid_at),
            "created_at": self._timestamp(order.created_at),
        }

    # ------------------------------------------------------------------
    # 内部：履约 / 记账 / 幂等提交
    # ------------------------------------------------------------------
    def _fulfill_rights(self, order: PurchaseOrder) -> None:
        plan = self.session.query(Plan).filter(Plan.id == order.plan_id).one_or_none()
        if plan is None:
            raise FailException("关联套餐不存在")
        granted = int(plan.grant_token_credits or 0)
        if order.plan_type == "membership":
            self._upsert_membership(order.account_id, plan, order.id)
            self._grant_credits(order.account_id, granted, order.id, pool="quota", plan=plan)
        elif order.plan_type == "credits":
            self._grant_credits(order.account_id, granted, order.id, pool="permanent")

    def _maybe_enable_auto_renewal(self, order: PurchaseOrder) -> None:
        """自动续费版套餐（auto_renew_default）支付成功后自动开通余额自动续费。

        与 AutoRenewalService.create 语义一致，但不单独 commit，
        由 confirm_paid 尾部 _commit_idempotent 统一提交，保证订单履约原子性。
        """
        if order.plan_type == "balance":
            return
        plan = self.session.query(Plan).filter(Plan.id == order.plan_id).one_or_none()
        if plan is None or not plan.is_active:
            return
        if not bool(plan.auto_renew_default):
            return
        existing = (
            self.session.query(AutoRenewal)
            .filter(
                AutoRenewal.account_id == order.account_id,
                AutoRenewal.plan_id == plan.id,
                AutoRenewal.status.in_(("active", "paused", "failed")),
            )
            .one_or_none()
        )
        if existing is not None and existing.status == "active":
            return
        now = self._now()
        next_renew_at = (
            self._membership_next_renew(order.account_id, plan)
            if order.plan_type == "membership"
            else None
        )
        if existing is not None:
            existing.status = "active"
            existing.pay_method = BALANCE_METHOD
            existing.fail_count = 0
            existing.next_renew_at = next_renew_at
            existing.updated_at = now
            return
        self.session.add(AutoRenewal(
            account_id=order.account_id,
            plan_id=plan.id,
            plan_type=order.plan_type,
            pay_method=BALANCE_METHOD,
            status="active",
            next_renew_at=next_renew_at,
        ))

    def _membership_next_renew(self, account_id: UUID, plan: Plan | None = None) -> datetime:
        membership = (
            self.session.query(Membership)
            .filter(Membership.account_id == account_id)
            .order_by(Membership.expires_at.desc())
            .first()
        )
        lead_days = max(int(plan.auto_renew_threshold_days or 1), 1) if plan is not None else 1
        if membership is not None and membership.expires_at:
            return membership.expires_at - timedelta(days=lead_days)
        return self._now() + timedelta(days=30)

    def _upsert_membership(self, account_id: UUID, plan: Plan, source_id: UUID) -> Membership:
        now = self._now()
        membership = (
            self.session.query(Membership)
            .filter(Membership.account_id == account_id)
            .order_by(Membership.expires_at.desc())
            .first()
        )
        if membership and membership.plan_id == plan.id and membership.expires_at and membership.expires_at > now:
            base = membership.expires_at
            membership.expires_at = base + timedelta(days=int(plan.duration_days or 0))
            membership.status = "active"
            membership.source = "order"
            membership.source_id = source_id
            membership.updated_at = now
            return membership
        membership = Membership(
            account_id=account_id,
            plan_id=plan.id,
            status="active",
            started_at=now,
            expires_at=now + timedelta(days=int(plan.duration_days or 0)),
            source="order",
            source_id=source_id,
        )
        self.session.add(membership)
        return membership

    def _grant_credits(self, account_id: UUID, amount: int, source_id: UUID, *, pool: str, plan: Plan | None = None) -> None:
        credit_account = (
            self.session.query(CreditAccount)
            .filter(CreditAccount.account_id == account_id)
            .with_for_update()
            .one_or_none()
        )
        if credit_account is None:
            credit_account = CreditAccount(account_id=account_id, permanent_credit=0, quota_credit=0, total_granted=0, total_consumed=0)
            self.session.add(credit_account)
        granted = int(amount or 0)
        if pool == "quota":
            if plan is not None and (plan.quota_refresh_period or "none") == "cycle" and int(plan.duration_days or 0) > 0:
                credit_account.quota_granted = granted
                credit_account.quota_cycle_days = int(plan.duration_days)
                credit_account.quota_credit = granted
                credit_account.quota_reset_at = self._now() + timedelta(days=int(plan.duration_days))
            else:
                credit_account.quota_credit = int(credit_account.quota_credit or 0) + granted
        else:
            credit_account.permanent_credit = int(credit_account.permanent_credit or 0) + granted
        credit_account.total_granted = int(credit_account.total_granted or 0) + granted
        credit_account.updated_at = now = self._now()
        self.session.add(CreditTransaction(
            account_id=account_id,
            amount=granted,
            balance_after=credit_account.available_tokens,
            transaction_type="order_grant",
            source="order",
            source_id=source_id,
            description="订单支付赠送算力值",
        ))

    def _debit_purchase(self, account_id: UUID, order: PurchaseOrder) -> None:
        self._get_balance_service().debit(
            account_id,
            order.amount,
            source="order",
            source_id=order.id,
            amount_type="purchase",
            description=f"余额购买套餐 {order.amount} 元",
        )

    # ------------------------------------------------------------------
    # 限购
    # ------------------------------------------------------------------
    _PERIOD_LABELS = {"all": "累计", "day": "每日", "week": "每周", "month": "每月"}
    _PERIOD_STEPS = ("all", "day", "week", "month")

    def _enforce_purchase_limit(self, account_id: UUID, plan: Plan) -> None:
        limit = int(plan.purchase_limit or 0)
        period = (plan.purchase_limit_period or "none").strip().lower()
        if limit <= 0 or period not in self._PERIOD_STEPS:
            return
        start = self._purchase_limit_since(period)
        query = self.session.query(PurchaseOrder).filter(
            PurchaseOrder.account_id == account_id,
            PurchaseOrder.plan_id == plan.id,
            PurchaseOrder.status == "paid",
        )
        if start is not None:
            query = query.filter(PurchaseOrder.paid_at >= start)
        if query.count() >= limit:
            label = self._PERIOD_LABELS.get(period, period)
            raise FailException(f"该套餐{label}限购 {limit} 次，已达购买上限")

    @staticmethod
    def _purchase_limit_since(period: str) -> datetime | None:
        now = datetime.now(UTC).replace(tzinfo=None)
        if period == "all":
            return None
        if period == "day":
            return now.replace(hour=0, minute=0, second=0, microsecond=0)
        if period == "week":
            day_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
            return day_start - timedelta(days=day_start.weekday())
        if period == "month":
            return now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        return None

    def _settle_commission(self, order: PurchaseOrder) -> None:
        distribution_service = self._get_distribution_service()
        if distribution_service is None:
            return
        settle = getattr(distribution_service, "settle_commission_for_order", None)
        if settle is None:
            return
        settle(order.account_id, order)

    def _commit_idempotent(self) -> None:
        try:
            self.session.commit()
        except IntegrityError as error:
            self.session.rollback()
            message = str(error)
            if "uq_balance_transaction_account_source_type" in message or "order_no" in message:
                raise FailException("操作冲突，请刷新后重试") from error
            raise

    def _get_order(self, order_no: str, account_id: UUID | None) -> PurchaseOrder:
        query = self.session.query(PurchaseOrder).filter(PurchaseOrder.order_no == order_no)
        if account_id is not None:
            query = query.filter(PurchaseOrder.account_id == account_id)
        order = query.one_or_none()
        if order is None:
            raise NotFoundException("订单不存在")
        return order

    def _generate_order_no(self) -> str:
        for _ in range(20):
            candidate = "PO" + datetime.now(UTC).strftime("%Y%m%d%H%M%S") + "".join(random.choices(string.digits, k=6))
            existing = self.session.query(PurchaseOrder.id).filter(PurchaseOrder.order_no == candidate).first()
            if existing is None:
                return candidate
        raise FailException("订单号生成失败，请重试")

    @staticmethod
    def _now() -> datetime:
        return datetime.now(UTC).replace(tzinfo=None)

    @staticmethod
    def _timestamp(value) -> int | None:
        if value is None:
            return None
        return int(value.replace(tzinfo=UTC).timestamp())

    @staticmethod
    def _paginator(total: int, current_page: int, page_size: int) -> dict:
        import math

        return {
            "total_record": total,
            "total_page": math.ceil(total / page_size) if total else 0,
            "current_page": current_page,
            "page_size": page_size,
        }