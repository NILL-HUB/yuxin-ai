from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from internal.exception import FailException, NotFoundException
from internal.model.billing import CreditAccount, Membership, Plan
from internal.model.distribution import AutoRenewal, PurchaseOrder
from internal.service.auto_renewal_service import AutoRenewalService, MAX_FAIL_COUNT


class _QueryStub:
    def __init__(self, *, one_or_none_result=None, all_result=None, first_result=None):
        self._one_or_none_result = one_or_none_result
        self._all_result = [] if all_result is None else all_result
        self._first_result = first_result

    def filter(self, *args, **kwargs):
        return self

    def order_by(self, *args, **kwargs):
        return self

    def distinct(self):
        return self

    def one_or_none(self):
        return self._one_or_none_result

    def first(self):
        return self._first_result

    def all(self):
        return self._all_result


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

    def commit(self):
        self.commits += 1

    def rollback(self):
        self.rollbacks += 1


class _OrderStub:
    def __init__(self, pay_error=None):
        self.pay_error = pay_error
        self.calls = []

    def create_order(self, account_id, plan_id, pay_method, order_source="normal"):
        order = PurchaseOrder(
            account_id=account_id,
            plan_id=plan_id,
            plan_type="membership",
            amount="100.00",
            pay_method=pay_method,
            order_source=order_source,
            status="pending",
        )
        order.order_no = "PO-AUTO-1"
        self.calls.append(("create", account_id, plan_id))
        return order

    def pay_with_balance(self, order):
        self.calls.append(("pay", order.order_no))
        if self.pay_error:
            raise FailException(self.pay_error)
        order.status = "paid"
        return order


def _plan(plan_type="membership", grant=100000, threshold=5, threshold_days=1):
    return Plan(
        id=uuid4(),
        code="pro",
        name="Pro",
        plan_type=plan_type,
        grant_token_credits=grant,
        auto_renew_threshold_percent=threshold,
        auto_renew_threshold_days=threshold_days,
        status="active",
    )


def _membership(account_id, expires_days=15):
    return Membership(
        account_id=account_id,
        plan_id=uuid4(),
        status="active",
        started_at=datetime.now(UTC).replace(tzinfo=None) - timedelta(days=10),
        expires_at=datetime.now(UTC).replace(tzinfo=None) + timedelta(days=expires_days),
        source="order",
        source_id=uuid4(),
    )


def _renewal(account_id, plan_type="membership", plan_id=None, status="active", next_renew_at=None):
    return AutoRenewal(
        account_id=account_id,
        plan_id=plan_id or uuid4(),
        plan_type=plan_type,
        pay_method="balance",
        status=status,
        next_renew_at=next_renew_at,
        renew_count=0,
        fail_count=0,
    )


class TestCreateAutoRenewal:
    def test_create_membership_should_set_next_renew_at_from_membership(self):
        account_id = uuid4()
        plan = _plan()
        membership = _membership(account_id)
        session = _SessionStub([
            _QueryStub(one_or_none_result=plan),          # plan
            _QueryStub(one_or_none_result=None),          # existing renewal
            _QueryStub(first_result=membership),          # 当前会员
        ])
        service = AutoRenewalService(session=session, order_service=_OrderStub())

        renewal = service.create(account_id, plan.id, "balance")

        assert renewal.status == "active"
        assert renewal.plan_type == "membership"
        assert renewal.next_renew_at == membership.expires_at - timedelta(days=1)

    def test_create_membership_should_use_configured_lead_days(self):
        account_id = uuid4()
        plan = _plan(threshold_days=3)
        membership = _membership(account_id)
        session = _SessionStub([
            _QueryStub(one_or_none_result=plan),          # plan
            _QueryStub(one_or_none_result=None),          # existing renewal
            _QueryStub(first_result=membership),          # 当前会员
        ])
        service = AutoRenewalService(session=session, order_service=_OrderStub())

        renewal = service.create(account_id, plan.id, "balance")

        assert renewal.next_renew_at == membership.expires_at - timedelta(days=3)

    def test_create_should_reject_online_method(self):
        plan = _plan()
        session = _SessionStub([_QueryStub(one_or_none_result=plan)])
        service = AutoRenewalService(session=session, order_service=_OrderStub())
        with pytest.raises(FailException, match="暂未开通"):
            service.create(uuid4(), plan.id, "wechatpay")

    def test_create_should_reject_duplicate_active(self):
        account_id = uuid4()
        plan = _plan()
        existing = _renewal(account_id, plan_id=plan.id)
        session = _SessionStub([
            _QueryStub(one_or_none_result=plan),
            _QueryStub(one_or_none_result=existing),
        ])
        service = AutoRenewalService(session=session, order_service=_OrderStub())
        with pytest.raises(FailException, match="已开通"):
            service.create(account_id, plan.id, "balance")


class TestRenewalExecution:
    def test_try_renew_membership_due_should_renew_once(self):
        account_id = uuid4()
        plan = _plan()
        renewal = _renewal(account_id, plan_id=plan.id, next_renew_at=datetime.now(UTC).replace(tzinfo=None) - timedelta(hours=1))
        session = _SessionStub([
            _QueryStub(first_result=_membership(account_id, expires_days=45)),   # 续费后会员到期日
            _QueryStub(one_or_none_result=plan),                                 # 套餐提前天数阈值
        ])
        order_stub = _OrderStub()
        service = AutoRenewalService(session=session, order_service=order_stub)

        result = service.try_renew_membership(renewal)

        assert result == "renewed"
        assert renewal.renew_count == 1
        assert renewal.last_renewed_at is not None
        assert renewal.fail_count == 0
        assert session.commits == 1

    def test_try_renew_membership_not_due_should_skip(self):
        renewal = _renewal(uuid4(), next_renew_at=datetime.now(UTC).replace(tzinfo=None) + timedelta(days=3))
        service = AutoRenewalService(session=_SessionStub(), order_service=_OrderStub())
        assert service.try_renew_membership(renewal) == "skipped"

    def test_renewal_should_count_failure_and_fail_after_threshold(self):
        account_id = uuid4()
        plan = _plan()
        renewal = _renewal(account_id, plan_id=plan.id, next_renew_at=datetime.now(UTC).replace(tzinfo=None) - timedelta(hours=1))
        renewal.fail_count = MAX_FAIL_COUNT - 1
        session = _SessionStub([])
        service = AutoRenewalService(session=session, order_service=_OrderStub(pay_error="余额不足"))

        result = service.try_renew_membership(renewal)

        assert result == "failed"
        assert renewal.fail_count == MAX_FAIL_COUNT
        assert renewal.status == "failed"
        assert session.rollbacks == 1

    def test_credits_threshold_should_renew_when_remaining_below_threshold(self):
        account_id = uuid4()
        plan = _plan(plan_type="credits", grant=10000, threshold=5)
        renewal = _renewal(account_id, plan_type="credits", plan_id=plan.id)
        credit_account = CreditAccount(account_id=account_id, permanent_credit=400, quota_credit=0, total_granted=10000, total_consumed=9600)
        session = _SessionStub([
            _QueryStub(all_result=[renewal]),     # active credits renewals
            _QueryStub(one_or_none_result=credit_account),  # credit account
            _QueryStub(one_or_none_result=plan),  # plan
        ])
        order_stub = _OrderStub()
        service = AutoRenewalService(session=session, order_service=order_stub)

        result = service.check_credits_threshold(account_id)

        assert result == "renewed"
        assert renewal.renew_count == 1
        assert any("create" in call for call in order_stub.calls)

    def test_credits_threshold_should_skip_when_remaining_above_threshold(self):
        account_id = uuid4()
        plan = _plan(plan_type="credits", grant=10000, threshold=5)
        renewal = _renewal(account_id, plan_type="credits", plan_id=plan.id)
        credit_account = CreditAccount(account_id=account_id, permanent_credit=9000, quota_credit=0, total_granted=10000, total_consumed=1000)
        session = _SessionStub([
            _QueryStub(all_result=[renewal]),
            _QueryStub(one_or_none_result=credit_account),
        ])
        order_stub = _OrderStub()
        service = AutoRenewalService(session=session, order_service=order_stub)

        result = service.check_credits_threshold(account_id)

        assert result == "skipped"
        assert renewal.renew_count == 0
        assert order_stub.calls == []


class TestRenewalManagement:
    def test_pause_resume_cancel_cycle(self):
        account_id = uuid4()
        renewal = _renewal(account_id)
        session = _SessionStub([
            _QueryStub(one_or_none_result=renewal),
            _QueryStub(one_or_none_result=renewal),
            _QueryStub(one_or_none_result=renewal),
            _QueryStub(one_or_none_result=renewal),
        ])
        service = AutoRenewalService(session=session, order_service=_OrderStub())
        assert service.set_status(account_id, renewal.id, "pause").status == "paused"
        assert service.set_status(account_id, renewal.id, "resume").status == "active"
        assert service.set_status(account_id, renewal.id, "cancel").status == "cancelled"
        with pytest.raises(FailException, match="已取消"):
            service.set_status(account_id, renewal.id, "resume")

    def test_set_status_should_404_when_not_found(self):
        session = _SessionStub([_QueryStub(one_or_none_result=None)])
        service = AutoRenewalService(session=session, order_service=_OrderStub())
        with pytest.raises(NotFoundException, match="不存在"):
            service.set_status(uuid4(), uuid4(), "pause")