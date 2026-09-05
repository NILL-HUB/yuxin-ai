from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import uuid4

import pytest

from internal.exception import FailException, NotFoundException
from internal.model.billing import CreditAccount, CreditTransaction, Membership, Plan
from internal.model.distribution import BalanceTransaction, PurchaseOrder, ReturnRequest, WithdrawalRequest
from internal.service.refund_service import RefundService
from internal.service.withdrawal_service import WithdrawalService


class _QueryStub:
    def __init__(self, *, one_or_none_result=None, all_result=None, count_result=0, first_result=None):
        self._one_or_none_result = one_or_none_result
        self._all_result = [] if all_result is None else all_result
        self._count_result = count_result
        self._first_result = first_result

    def filter(self, *args, **kwargs):
        return self

    def order_by(self, *args, **kwargs):
        return self

    def with_for_update(self):
        return self

    def join(self, *args, **kwargs):
        return self

    def offset(self, _value):
        return self

    def limit(self, _value):
        return self

    def one_or_none(self):
        return self._one_or_none_result

    def first(self):
        return self._first_result

    def all(self):
        return self._all_result

    def count(self):
        return self._count_result


class _SessionStub:
    def __init__(self, queries=None):
        self._queries = list(queries or [])
        self.added = []
        self.commits = 0
        self.rollbacks = 0

    def query(self, *_args, **_kwargs):
        if self._queries:
            return self._queries.pop(0)
        return _QueryStub()

    def add(self, value):
        self.added.append(value)

    def flush(self):
        for item in self.added:
            if getattr(item, "id", None) is None:
                item.id = uuid4()

    def commit(self):
        self.commits += 1

    def rollback(self):
        self.rollbacks += 1


class _BalanceStub:
    def __init__(self, debit_error=None):
        self.debit_error = debit_error
        self.credits = []
        self.debits = []

    def ensure_account(self, account_id):
        return object()

    def credit(self, account_id, amount, *, source, source_id, amount_type, rate=None, description=""):
        self.credits.append({"account_id": account_id, "amount": amount, "amount_type": amount_type, "source": source, "source_id": source_id})
        return object()

    def debit(self, account_id, amount, *, source, source_id, amount_type, description=""):
        if self.debit_error:
            raise ValueError(self.debit_error)
        self.debits.append({"account_id": account_id, "amount": amount, "amount_type": amount_type, "source": source, "source_id": source_id})
        return object()


def _order(account_id, plan_id=None, plan_type="membership", pay_method="balance", amount="100.00", status="paid"):
    return PurchaseOrder(
        account_id=account_id,
        order_no="PO-1",
        plan_id=plan_id or uuid4(),
        plan_type=plan_type,
        amount=amount,
        pay_method=pay_method,
        status=status,
        paid_at=datetime.now(UTC).replace(tzinfo=None) - timedelta(hours=1),
    )


def _plan(grant=100):
    return Plan(id=uuid4(), code="pro", name="Pro", plan_type="membership", grant_token_credits=grant, status="active")


def _membership(account_id, order_id):
    return Membership(
        account_id=account_id,
        plan_id=uuid4(),
        status="active",
        started_at=datetime.now(UTC).replace(tzinfo=None),
        expires_at=datetime.now(UTC).replace(tzinfo=None) + timedelta(days=30),
        source="order",
        source_id=order_id,
    )


def _credit(account_id, permanent=0, quota=0):
    return CreditAccount(account_id=account_id, permanent_credit=permanent, quota_credit=quota, total_granted=0, total_consumed=0)


def _commission_tx(account_id):
    return BalanceTransaction(account_id=account_id, amount=Decimal("30.00"), balance_after=Decimal("30.00"), amount_type="commission", source="order", source_id=uuid4())


class TestWithdrawal:
    def test_create_should_debit_and_flush_id(self):
        account_id = uuid4()
        balance_stub = _BalanceStub()
        session = _SessionStub([])
        service = WithdrawalService(session=session, balance_service=balance_stub)

        row = service.create(account_id, "50.00")

        assert row.id is not None
        assert row.status == "pending"
        assert float(row.amount) == 50.00
        assert len(balance_stub.debits) == 1
        assert balance_stub.debits[0]["amount_type"] == "withdraw"

    def test_create_should_reject_below_minimum(self):
        service = WithdrawalService(session=_SessionStub([]), balance_service=_BalanceStub())
        with pytest.raises(FailException, match="最低提现金额"):
            service.create(uuid4(), "0.50")

    def test_cancel_should_refund_balance(self):
        account_id = uuid4()
        balance_stub = _BalanceStub()
        row = WithdrawalRequest(account_id=account_id, amount=Decimal("50.00"), status="pending")
        session = _SessionStub([_QueryStub(one_or_none_result=row)])
        service = WithdrawalService(session=session, balance_service=balance_stub)

        service.cancel(account_id, row.id)

        assert row.status == "cancelled"
        assert len(balance_stub.credits) == 1
        assert balance_stub.credits[0]["amount_type"] == "refund"

    def test_reject_should_refund_and_close(self):
        account_id = uuid4()
        balance_stub = _BalanceStub()
        row = WithdrawalRequest(account_id=account_id, amount=Decimal("50.00"), status="pending")
        session = _SessionStub([_QueryStub(one_or_none_result=row)])
        service = WithdrawalService(session=session, balance_service=balance_stub)

        row = service.reject(row.id, reviewer_id=uuid4(), review_note="拒绝")

        assert row.status == "rejected"
        assert len(balance_stub.credits) == 1
        assert session.commits == 1


class TestRefundCreate:
    def test_create_should_require_paid_order(self):
        account_id = uuid4()
        order = _order(account_id, status="pending")
        session = _SessionStub([_QueryStub(one_or_none_result=order)])
        service = RefundService(session=session, balance_service=_BalanceStub())
        with pytest.raises(FailException, match="仅已支付"):
            service.create(account_id, "PO-1")

    def test_create_should_reject_when_rights_consumed(self):
        account_id = uuid4()
        order = _order(account_id)
        session = _SessionStub([
            _QueryStub(one_or_none_result=order),          # order
            _QueryStub(one_or_none_result=None),          # 待处理申请
            _QueryStub(first_result=uuid4()),             # 支付后的 consume 记录存在
        ])
        service = RefundService(session=session, balance_service=_BalanceStub())
        with pytest.raises(FailException, match="已发生消耗"):
            service.create(account_id, "PO-1")

    def test_create_should_allow_when_unconsumed(self):
        account_id = uuid4()
        order = _order(account_id)
        session = _SessionStub([
            _QueryStub(one_or_none_result=order),
            _QueryStub(one_or_none_result=None),
            _QueryStub(first_result=None),
        ])
        service = RefundService(session=session, balance_service=_BalanceStub())
        refund = service.create(account_id, "PO-1", reason="不想要了")
        assert refund.status == "pending"
        assert any(isinstance(item, ReturnRequest) for item in session.added)


class TestRefundApprove:
    def _approve_stubs(self, refund, account_id, order, membership, credit_account, commission_tx):
        return _SessionStub([
            _QueryStub(one_or_none_result=refund),       # 退款申请
            _QueryStub(one_or_none_result=order),        # order
            _QueryStub(first_result=membership),         # membership
            _QueryStub(one_or_none_result=_plan()),      # plan
            _QueryStub(one_or_none_result=credit_account),  # credit account
            _QueryStub(one_or_none_result=commission_tx),   # commission tx
        ])

    def test_approve_balance_membership_order_should_refund_and_clawback(self):
        account_id = uuid4()
        inviter_id = uuid4()
        order = _order(account_id)
        member = _membership(account_id, order.id)
        credit = _credit(account_id, permanent=0, quota=100)
        commission = _commission_tx(inviter_id)
        refund = ReturnRequest(account_id=account_id, order_id=order.id, amount=order.amount, status="pending")
        session = self._approve_stubs(refund, account_id, order, member, credit, commission)
        balance_stub = _BalanceStub()
        service = RefundService(session=session, balance_service=balance_stub)

        refund = service.approve(refund.id)

        assert refund.status == "approved"
        assert order.status == "refunded"
        assert member.status == "expired"
        assert credit.quota_credit == 0
        assert len(balance_stub.credits) == 1
        assert balance_stub.credits[0]["amount_type"] == "refund"
        assert len(balance_stub.debits) == 1
        assert balance_stub.debits[0]["amount_type"] == "refund"
        assert session.commits == 1

    def test_approve_should_hold_when_clawback_insufficient(self):
        account_id = uuid4()
        inviter_id = uuid4()
        order = _order(account_id)
        member = _membership(account_id, order.id)
        credit = _credit(account_id, permanent=0, quota=100)
        commission = _commission_tx(inviter_id)
        refund = ReturnRequest(account_id=account_id, order_id=order.id, amount=order.amount, status="pending")
        session = self._approve_stubs(refund, account_id, order, member, credit, commission)
        balance_stub = _BalanceStub(debit_error="余额不足")
        service = RefundService(session=session, balance_service=balance_stub)

        refund = service.approve(refund.id)

        assert refund.status == "approved"
        assert order.status == "refund_hold"
        assert "人工" in refund.review_note

    def test_approve_balance_topup_order_should_deduct_balance(self):
        account_id = uuid4()
        order = _order(account_id, plan_type="balance", pay_method="alipay", amount="50.00")
        refund = ReturnRequest(account_id=account_id, order_id=order.id, amount=order.amount, status="pending")
        session = _SessionStub([
            _QueryStub(one_or_none_result=refund),
            _QueryStub(one_or_none_result=order),
        ])
        balance_stub = _BalanceStub()
        service = RefundService(session=session, balance_service=balance_stub)

        refund = service.approve(refund.id)

        assert order.status == "refunded"
        assert len(balance_stub.debits) == 1
        assert balance_stub.debits[0]["amount_type"] == "refund"

    def test_reject_should_close_request(self):
        account_id = uuid4()
        order = _order(account_id)
        refund = ReturnRequest(account_id=account_id, order_id=order.id, amount=order.amount, status="pending")
        session = _SessionStub([_QueryStub(one_or_none_result=refund)])
        service = RefundService(session=session, balance_service=_BalanceStub())

        refund = service.reject(refund.id, review_note="不符合退款条件")

        assert refund.status == "rejected"
        assert session.commits == 1