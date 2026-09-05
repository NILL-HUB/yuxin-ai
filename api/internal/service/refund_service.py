from decimal import Decimal
from datetime import UTC, datetime
from uuid import UUID

from internal.exception import FailException, NotFoundException
from internal.extension.database_extension import db
from internal.model.account import Account
from internal.model.billing import CreditAccount, CreditTransaction, Membership
from internal.model.distribution import BalanceTransaction, PurchaseOrder, ReturnRequest


class RefundService:
    """售后退款：申请 → 审核 → 资金回补 + 权益回收 + 佣金回扣。

    - 可退范围：paid 订单；直购订单（membership/credits）要求支付后未发生任何算力消耗；
      在线充值订单（balance）直接可退。
    - 审核通过：资金回补（余额购买回余额 / 在线充值扣回 / 线上直购标记线退）；
      权益回收（会员终止+清额度 / 永久算力扣回）；上级佣金回扣（余额不足 → refund_hold 人工）。
    """

    def __init__(self, session=None, balance_service=None):
        self.session = session or db.session
        self._balance_service = balance_service

    def _get_balance_service(self):
        if self._balance_service is None:
            from internal.service.balance_service import BalanceService

            self._balance_service = BalanceService(session=self.session)
        return self._balance_service

    def create(self, account_id: UUID, order_no: str, reason: str = "") -> ReturnRequest:
        order = self._get_order(order_no, account_id)
        if order.status != "paid":
            raise FailException("仅已支付订单可申请退款")
        existing = (
            self.session.query(ReturnRequest)
            .filter(ReturnRequest.order_id == order.id, ReturnRequest.status == "pending")
            .one_or_none()
        )
        if existing is not None:
            raise FailException("该订单已有待处理的退款申请")
        if order.plan_type != "balance" and self._order_rights_consumed(order):
            raise FailException("订单权益已发生消耗，无法退款")
        refund = ReturnRequest(
            account_id=account_id,
            order_id=order.id,
            amount=order.amount,
            reason=(reason or "")[:1024],
            status="pending",
        )
        self.session.add(refund)
        self.session.commit()
        return refund

    def list_mine(self, account_id: UUID, current_page: int = 1, page_size: int = 20) -> dict:
        current_page = max(int(current_page or 1), 1)
        page_size = max(min(int(page_size or 20), 50), 1)
        query = (
            self.session.query(ReturnRequest, PurchaseOrder)
            .join(PurchaseOrder, PurchaseOrder.id == ReturnRequest.order_id)
            .filter(ReturnRequest.account_id == account_id)
            .order_by(ReturnRequest.created_at.desc())
        )
        total = query.count()
        rows = query.offset((current_page - 1) * page_size).limit(page_size).all()
        return {"list": [self._serialize(refund, order) for refund, order in rows], "paginator": self._paginator(total, current_page, page_size)}

    def list_all(self, status: str = "", current_page: int = 1, page_size: int = 20) -> dict:
        current_page = max(int(current_page or 1), 1)
        page_size = max(min(int(page_size or 20), 50), 1)
        query = (
            self.session.query(ReturnRequest, PurchaseOrder, Account)
            .join(PurchaseOrder, PurchaseOrder.id == ReturnRequest.order_id)
            .join(Account, Account.id == ReturnRequest.account_id)
        )
        if status:
            query = query.filter(ReturnRequest.status == status)
        query = query.order_by(ReturnRequest.created_at.desc())
        total = query.count()
        rows = query.offset((current_page - 1) * page_size).limit(page_size).all()
        return {"list": [self._serialize(refund, order, account) for refund, order, account in rows], "paginator": self._paginator(total, current_page, page_size)}

    def approve(self, request_id: UUID, reviewer_id: UUID | None = None, review_note: str = "") -> ReturnRequest:
        refund = self._find(request_id)
        if refund.status != "pending":
            raise FailException("该退款申请已处理")
        order = self.session.query(PurchaseOrder).filter(PurchaseOrder.id == refund.order_id).one_or_none()
        if order is None or order.status != "paid":
            raise FailException("订单状态异常，无法退款")

        self._refund_funds(order)
        if order.plan_type != "balance":
            self._reclaim_rights(order)
            hold = self._clawback_commission(order)
            if hold:
                order.status = "refund_hold"
                order.refund_at = self._now()
                refund.status = "approved"
                refund.reviewed_by = reviewer_id
                refund.reviewed_at = self._now()
                refund.review_note = "佣金回扣余额不足，订单转人工处理：" + (review_note or "")
                self._commit()
                return refund
        order.status = "refunded"
        order.refund_at = self._now()
        refund.status = "approved"
        refund.reviewed_by = reviewer_id
        refund.reviewed_at = self._now()
        refund.review_note = review_note or ""
        self._commit()
        return refund

    def reject(self, request_id: UUID, reviewer_id: UUID | None = None, review_note: str = "") -> ReturnRequest:
        refund = self._find(request_id)
        if refund.status != "pending":
            raise FailException("该退款申请已处理")
        refund.status = "rejected"
        refund.reviewed_by = reviewer_id
        refund.reviewed_at = self._now()
        refund.review_note = review_note or ""
        self._commit()
        return refund

    # ------------------------------------------------------------------
    # 内部
    # ------------------------------------------------------------------
    def _refund_funds(self, order: PurchaseOrder) -> None:
        balance_service = self._get_balance_service()
        if order.plan_type == "balance":
            # 在线充值：从余额扣回并标记线退
            balance_service.debit(
                order.account_id,
                order.amount,
                source="order",
                source_id=order.id,
                amount_type="refund",
                description="退款扣回在线充值金额",
            )
        elif order.pay_method == "balance":
            # 余额购买直购：金额回补余额
            balance_service.credit(
                order.account_id,
                order.amount,
                source="order",
                source_id=order.id,
                amount_type="refund",
                description="退款回补余额",
            )
        # 在线支付直购：标记 refund_at 即可（线下/未来网关退款）

    def _reclaim_rights(self, order: PurchaseOrder) -> None:
        if order.plan_type == "membership":
            membership = (
                self.session.query(Membership)
                .filter(Membership.account_id == order.account_id)
                .order_by(Membership.expires_at.desc())
                .first()
            )
            if membership is not None and membership.source_id == order.id:
                membership.status = "expired"
                membership.updated_at = self._now()
            self._adjust_credit(order, quota=True)
        elif order.plan_type == "credits":
            self._adjust_credit(order, quota=False)

    def _adjust_credit(self, order: PurchaseOrder, *, quota: bool) -> None:
        from internal.model.billing import Plan

        plan = self.session.query(Plan).filter(Plan.id == order.plan_id).one_or_none()
        grant = int(plan.grant_token_credits or 0) if plan else 0
        credit_account = (
            self.session.query(CreditAccount)
            .filter(CreditAccount.account_id == order.account_id)
            .with_for_update()
            .one_or_none()
        )
        if credit_account is None:
            return
        if quota:
            credit_account.quota_credit = 0
        else:
            remaining = int(credit_account.permanent_credit or 0)
            credit_account.permanent_credit = max(remaining - grant, 0)
        credit_account.updated_at = self._now()

    def _clawback_commission(self, order: PurchaseOrder) -> bool:
        """上级佣金回扣；余额不足返回 True（标记 refund_hold）。"""
        commission_tx = (
            self.session.query(BalanceTransaction)
            .filter(
                BalanceTransaction.source == "order",
                BalanceTransaction.source_id == order.id,
                BalanceTransaction.amount_type == "commission",
            )
            .one_or_none()
        )
        if commission_tx is None:
            return False
        try:
            self._get_balance_service().debit(
                commission_tx.account_id,
                commission_tx.amount,
                source="order",
                source_id=order.id,
                amount_type="refund",
                description="退款回扣佣金",
            )
            return False
        except ValueError:
            return True

    def _order_rights_consumed(self, order: PurchaseOrder) -> bool:
        return (
            self.session.query(CreditTransaction.id)
            .filter(
                CreditTransaction.account_id == order.account_id,
                CreditTransaction.transaction_type == "consume",
                CreditTransaction.created_at >= order.paid_at,
            )
            .first()
            is not None
        )

    def _get_order(self, order_no: str, account_id: UUID) -> PurchaseOrder:
        order = (
            self.session.query(PurchaseOrder)
            .filter(PurchaseOrder.order_no == order_no, PurchaseOrder.account_id == account_id)
            .one_or_none()
        )
        if order is None:
            raise NotFoundException("订单不存在")
        return order

    def _find(self, request_id: UUID) -> ReturnRequest:
        refund = self.session.query(ReturnRequest).filter(ReturnRequest.id == request_id).one_or_none()
        if refund is None:
            raise NotFoundException("退款申请不存在")
        return refund

    def _commit(self) -> None:
        try:
            self.session.commit()
        except Exception:
            self.session.rollback()
            raise

    @staticmethod
    def _serialize(refund: ReturnRequest, order: PurchaseOrder, account=None) -> dict:
        return {
            "id": str(refund.id),
            "account_id": str(refund.account_id),
            "user_name": (account.name or account.username or "") if account else "",
            "user_email": (account.email or "") if account else "",
            "order_no": order.order_no,
            "plan_type": order.plan_type,
            "amount": float(refund.amount),
            "reason": refund.reason,
            "status": refund.status,
            "review_note": refund.review_note,
            "created_at": int(refund.created_at.replace(tzinfo=UTC).timestamp()) if refund.created_at else None,
        }

    @staticmethod
    def _now() -> datetime:
        return datetime.now(UTC).replace(tzinfo=None)

    @staticmethod
    def _paginator(total: int, current_page: int, page_size: int) -> dict:
        import math

        return {
            "total_record": total,
            "total_page": math.ceil(total / page_size) if total else 0,
            "current_page": current_page,
            "page_size": page_size,
        }