from decimal import Decimal
from typing import Any
from uuid import UUID

from internal.extension.database_extension import db
from internal.model.distribution import BalanceAccount, BalanceTransaction

MONEY_QUANTUM = Decimal("0.01")


def _money(value: Any) -> Decimal:
    """标准化金额为两位小数的 Decimal。"""
    try:
        return Decimal(str(value or 0)).quantize(MONEY_QUANTUM)
    except Exception:
        return Decimal("0.00")


class BalanceService:
    """共享余额钱包记账服务。

    余额 = 充值(recharge) + 佣金(commission) - 购买(purchase) - 提现(withdraw)
    ± 退款(refund) ± 调整(adjust)，全部以流水（balance_transaction）落账，
    金额金额以 amount_type 区分展示与对账。
    """

    def __init__(self, session=None):
        self.session = session or db.session

    def ensure_account(self, account_id: UUID) -> BalanceAccount:
        account = (
            self.session.query(BalanceAccount)
            .filter(BalanceAccount.account_id == account_id)
            .with_for_update()
            .one_or_none()
        )
        if account is None:
            account = BalanceAccount(account_id=account_id, balance=Decimal("0.00"), high_rate_locked=False)
            self.session.add(account)
        return account

    def get_account(self, account_id) -> BalanceAccount | None:
        return (
            self.session.query(BalanceAccount)
            .filter(BalanceAccount.account_id == account_id)
            .one_or_none()
        )

    def find_transaction(self, account_id, source: str, source_id, amount_type: str) -> BalanceTransaction | None:
        return (
            self.session.query(BalanceTransaction)
            .filter(
                BalanceTransaction.account_id == account_id,
                BalanceTransaction.source == source,
                BalanceTransaction.source_id == source_id,
                BalanceTransaction.amount_type == amount_type,
            )
            .one_or_none()
        )

    def get_balance(self, account_id) -> Decimal:
        account = self.get_account(account_id)
        return _money(account.balance) if account else Decimal("0.00")

    def credit(
        self,
        account_id: UUID,
        amount: Any,
        *,
        source: str,
        source_id,
        amount_type: str,
        rate: Any = None,
        description: str = "",
    ) -> BalanceTransaction:
        """余额入账（充值/佣金/退款回补等）。幂等：同 (source, source_id, amount_type) 只记一笔。"""
        money = _money(amount)
        if money <= 0:
            raise ValueError("credit 金额必须为正")
        existing = self.find_transaction(account_id, source, source_id, amount_type)
        if existing is not None:
            return existing

        account = self.ensure_account(account_id)
        account.balance = _money(account.balance) + money
        account.updated_at = _now()
        if amount_type == "recharge":
            account.total_recharged = _money(account.total_recharged) + money
        elif amount_type == "commission":
            account.total_commission = _money(account.total_commission) + money

        transaction = BalanceTransaction(
            account_id=account_id,
            amount=money,
            balance_after=account.balance,
            amount_type=amount_type,
            rate=_money(rate) if rate is not None else None,
            source=source,
            source_id=source_id,
            description=description or "",
        )
        self.session.add(transaction)
        return transaction

    def debit(
        self,
        account_id: UUID,
        amount: Any,
        *,
        source: str,
        source_id,
        amount_type: str,
        description: str = "",
    ) -> BalanceTransaction:
        """余额扣款（购买/提现挂起/退款扣回）。余额不足抛 ValueError。"""
        money = _money(amount)
        if money <= 0:
            raise ValueError("debit 金额必须为正")
        account = self.ensure_account(account_id)
        if _money(account.balance) < money:
            raise ValueError("余额不足")
        account.balance = _money(account.balance) - money
        account.updated_at = _now()
        if amount_type == "purchase":
            account.total_purchased = _money(account.total_purchased) + money
        elif amount_type == "withdraw":
            account.total_withdrawn = _money(account.total_withdrawn) + money
        transaction = BalanceTransaction(
            account_id=account_id,
            amount=-money,
            balance_after=account.balance,
            amount_type=amount_type,
            source=source,
            source_id=source_id,
            description=description or "",
        )
        self.session.add(transaction)
        return transaction

    def profile(self, account_id) -> dict:
        account = self.get_account(account_id)
        return {
            "account_id": str(account_id),
            "balance": float(_money(account.balance)) if account else 0.0,
            "recharge_balance": float(_money(account.total_recharged)) if account else 0.0,
            "commission_balance": float(_money(account.total_commission)) if account else 0.0,
            "total_withdrawn": float(_money(account.total_withdrawn)) if account else 0.0,
            "total_purchased": float(_money(account.total_purchased)) if account else 0.0,
            "high_rate_locked": bool(account.high_rate_locked) if account else False,
        }


def _now():
    from datetime import UTC, datetime

    return datetime.now(UTC).replace(tzinfo=None)