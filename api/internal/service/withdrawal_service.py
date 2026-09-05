from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID

from internal.exception import FailException, NotFoundException
from internal.extension.database_extension import db
from internal.model.distribution import WithdrawalRequest

MIN_WITHDRAW_AMOUNT = Decimal("1.00")


class WithdrawalService:
    """提现申请与审核。申请即扣余额挂起；审核通过=线下打款，驳回/取消=金额回余额。"""

    def __init__(self, session=None, balance_service=None):
        self.session = session or db.session
        self._balance_service = balance_service

    def _get_balance_service(self):
        if self._balance_service is None:
            from internal.service.balance_service import BalanceService

            self._balance_service = BalanceService(session=self.session)
        return self._balance_service

    def create(self, account_id: UUID, amount) -> WithdrawalRequest:
        money = self._normalize_amount(amount)
        request = WithdrawalRequest(account_id=account_id, amount=money, status="pending")
        self.session.add(request)
        self.session.flush()
        try:
            self._get_balance_service().debit(
                account_id,
                money,
                source="withdrawal_request",
                source_id=request.id,
                amount_type="withdraw",
                description="提现申请挂起",
            )
        except ValueError as exc:
            self.session.rollback()
            raise FailException("提现金额无效或余额不足") from exc
        self.session.commit()
        return request

    def list_mine(self, account_id: UUID, current_page: int = 1, page_size: int = 20) -> dict:
        current_page = max(int(current_page or 1), 1)
        page_size = max(min(int(page_size or 20), 50), 1)
        query = (
            self.session.query(WithdrawalRequest)
            .filter(WithdrawalRequest.account_id == account_id)
            .order_by(WithdrawalRequest.created_at.desc())
        )
        total = query.count()
        rows = query.offset((current_page - 1) * page_size).limit(page_size).all()
        return {"list": [self._serialize(row) for row in rows], "paginator": self._paginator(total, current_page, page_size)}

    def cancel(self, account_id: UUID, request_id: UUID) -> WithdrawalRequest:
        row = self._get_mine(account_id, request_id)
        if row.status != "pending":
            raise FailException("仅待审核的提现申请可取消")
        row.status = "cancelled"
        self._get_balance_service().credit(
            account_id,
            row.amount,
            source="withdrawal_request",
            source_id=row.id,
            amount_type="refund",
            description="提现申请取消退款",
        )
        self.session.commit()
        return row

    def approve(self, request_id: UUID, reviewer_id: UUID | None = None, review_note: str = "") -> WithdrawalRequest:
        row = self._find(request_id)
        if row.status != "pending":
            raise FailException("该提现申请已处理")
        row.status = "approved"
        row.reviewed_by = reviewer_id
        row.reviewed_at = self._now()
        row.review_note = review_note
        try:
            self.session.commit()
        except Exception:
            self.session.rollback()
            raise
        return row

    def reject(self, request_id: UUID, reviewer_id: UUID | None = None, review_note: str = "") -> WithdrawalRequest:
        row = self._find(request_id)
        if row.status != "pending":
            raise FailException("该提现申请已处理")
        self._get_balance_service().credit(
            row.account_id,
            row.amount,
            source="withdrawal_request",
            source_id=row.id,
            amount_type="refund",
            description="提现驳回退款",
        )
        row.status = "rejected"
        row.reviewed_by = reviewer_id
        row.reviewed_at = self._now()
        row.review_note = review_note
        try:
            self.session.commit()
        except Exception:
            self.session.rollback()
            raise
        return row

    def list_all(self, status: str = "", current_page: int = 1, page_size: int = 20) -> dict:
        current_page = max(int(current_page or 1), 1)
        page_size = max(min(int(page_size or 20), 50), 1)
        query = self.session.query(WithdrawalRequest).order_by(WithdrawalRequest.created_at.desc())
        if status:
            query = query.filter(WithdrawalRequest.status == status)
        total = query.count()
        rows = query.offset((current_page - 1) * page_size).limit(page_size).all()
        accounts = self._account_map([row.account_id for row in rows])
        return {"list": [self._serialize(row, accounts) for row in rows], "paginator": self._paginator(total, current_page, page_size)}

    def _get_mine(self, account_id: UUID, request_id: UUID) -> WithdrawalRequest:
        row = (
            self.session.query(WithdrawalRequest)
            .filter(WithdrawalRequest.id == request_id, WithdrawalRequest.account_id == account_id)
            .one_or_none()
        )
        if row is None:
            raise NotFoundException("提现申请不存在")
        return row

    def _find(self, request_id: UUID) -> WithdrawalRequest:
        row = self.session.query(WithdrawalRequest).filter(WithdrawalRequest.id == request_id).one_or_none()
        if row is None:
            raise NotFoundException("提现申请不存在")
        return row

    @staticmethod
    def _normalize_amount(amount) -> Decimal:
        try:
            money = Decimal(str(amount or 0)).quantize(Decimal("0.01"))
        except Exception:
            raise FailException("提现金额无效") from None
        if money < MIN_WITHDRAW_AMOUNT:
            raise FailException(f"最低提现金额 {MIN_WITHDRAW_AMOUNT} 元")
        return money

    @staticmethod
    def _now() -> datetime:
        return datetime.now(UTC).replace(tzinfo=None)

    @staticmethod
    def _serialize(row: WithdrawalRequest, accounts: dict | None = None) -> dict:
        account = (accounts or {}).get(str(row.account_id))
        return {
            "id": str(row.id),
            "account_id": str(row.account_id),
            "user_name": (account.name or account.username or "") if account else "",
            "user_email": (account.email or "") if account else "",
            "amount": float(row.amount),
            "status": row.status,
            "review_note": row.review_note,
            "created_at": int(row.created_at.replace(tzinfo=UTC).timestamp()) if row.created_at else None,
        }

    def _account_map(self, account_ids) -> dict:
        from internal.model.account import Account

        ids = {UUID(str(aid)) for aid in account_ids if aid}
        if not ids:
            return {}
        rows = self.session.query(Account).filter(Account.id.in_(ids)).all()
        return {str(row.id): row for row in rows}

    @staticmethod
    def _paginator(total: int, current_page: int, page_size: int) -> dict:
        import math

        return {
            "total_record": total,
            "total_page": math.ceil(total / page_size) if total else 0,
            "current_page": current_page,
            "page_size": page_size,
        }