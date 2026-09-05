from datetime import UTC, datetime
from uuid import uuid4

import pytest

from decimal import Decimal

from internal.exception import FailException
from internal.model.account import Account
from internal.model.billing import Plan
from internal.model.distribution import (
    BalanceAccount,
    BalanceTransaction,
    DistributionRelation,
    PurchaseOrder,
    ReferralCode,
)
from internal.service.distribution_service import DistributionService


class _QueryStub:
    def __init__(self, *, one_or_none_result=None, all_result=None, count_result=0, first_result=None):
        self._one_or_none_result = one_or_none_result
        self._all_result = [] if all_result is None else all_result
        self._count_result = count_result
        self._first_result = first_result
        self.filters = []
        self.order_by_args = []
        self.deleted = []

    def filter(self, *args, **kwargs):
        self.filters.append((args, kwargs))
        return self

    def order_by(self, *args):
        self.order_by_args.append(args)
        return self

    def with_for_update(self):
        return self

    def join(self, *args, **kwargs):
        return self

    def offset(self, value):
        return self

    def limit(self, value):
        return self

    def one_or_none(self):
        return self._one_or_none_result

    def first(self):
        return self._first_result

    def all(self):
        return self._all_result

    def count(self):
        return self._count_result

    def delete(self):
        self.deleted.append(True)


class _SessionStub:
    def __init__(self, queries=None):
        self._queries = list(queries or [])
        self.added = []
        self.deleted = []

    def query(self, *_args, **_kwargs):
        if self._queries:
            return self._queries.pop(0)
        return _QueryStub()

    def add(self, value):
        self.added.append(value)

    def delete(self, value):
        self.deleted.append(value)

    def commit(self):
        self.added.append("__commit__")


class _FlagStub:
    def __init__(self, enabled=True):
        self.enabled = enabled

    def is_enabled(self, code):
        return self.enabled


class _BalanceStub:
    def __init__(self):
        self.credits = []

    def ensure_account(self, account_id):
        return BalanceAccount(account_id=account_id)

    def get_account(self, account_id):
        return None

    def credit(self, account_id, amount, *, source, source_id, amount_type, rate=None, description=""):
        self.credits.append({
            "account_id": account_id,
            "amount": amount,
            "source": source,
            "source_id": source_id,
            "amount_type": amount_type,
            "rate": rate,
        })


def _account(status="active"):
    return Account(id=uuid4(), name="Alice", status=status)


def _plan(plan_type="membership", price="100.00"):
    return Plan(id=uuid4(), code="pro", name="Pro", plan_type=plan_type, price=price, duration_days=30, grant_token_credits=100, status="active")


def _relation(account_id, inviter_id, source="register"):
    return DistributionRelation(invitee_account_id=account_id, inviter_account_id=inviter_id, source=source)


class TestInviteCode:
    def test_validate_new_code_should_normalize_uppercase_and_enforce_format(self):
        assert DistributionService.validate_new_code(" abcd ") == "ABCD"
        assert DistributionService.validate_new_code("a-b_c1") == "A-B_C1"
        with pytest.raises(FailException, match="长度"):
            DistributionService.validate_new_code("ab")
        with pytest.raises(FailException, match="仅支持"):
            DistributionService.validate_new_code("ab@cd")

    def test_ensure_referral_code_should_generate_when_missing(self):
        session = _SessionStub([_QueryStub(one_or_none_result=None), _QueryStub(first_result=None)])
        service = DistributionService(session=session)
        referral = service.ensure_referral_code(uuid4())
        assert len(referral.code) == 8
        assert any(isinstance(item, ReferralCode) for item in session.added)

    def test_update_referral_code_should_reject_duplicate_case_insensitively(self):
        account_id = uuid4()
        existing = ReferralCode(account_id=account_id, code="ABCD1234")
        session = _SessionStub([
            _QueryStub(first_result=uuid4()),             # code exists (case-insensitive)
            _QueryStub(one_or_none_result=existing),      # own referral（未走到）
        ])
        service = DistributionService(session=session)
        with pytest.raises(FailException, match="已被使用"):
            service.update_referral_code(account_id, "abcd1234")

    def test_resolve_inviter_by_code_should_require_active_inviter(self):
        active = _account()
        disabled = _account(status="disabled")
        code = "CODE1234"

        def _build(inviter):
            referral = ReferralCode(account_id=inviter.id, code=code)
            return DistributionService(session=_SessionStub([
                _QueryStub(one_or_none_result=referral),
                _QueryStub(one_or_none_result=inviter),
            ]))

        assert _build(active).resolve_inviter_by_code("code1234") == active
        assert _build(disabled).resolve_inviter_by_code("CODE1234") is None


class TestDistributionRelation:
    def test_bind_superior_should_reject_self_binding(self):
        account_id = uuid4()
        service = DistributionService(session=_SessionStub())
        with pytest.raises(FailException, match="不能绑定自己"):
            service.bind_superior(account_id, account_id)

    def test_bind_superior_should_create_relation(self):
        invitee_id = uuid4()
        inviter = _account()
        session = _SessionStub([
            _QueryStub(one_or_none_result=inviter),   # inviter account
            _QueryStub(one_or_none_result=None),      # reverse relation
            _QueryStub(one_or_none_result=None),      # existing relation
        ])
        service = DistributionService(session=session)
        relation = service.bind_superior(invitee_id, inviter.id, source="register")
        assert relation.inviter_account_id == inviter.id
        assert relation.source == "register"
        assert any(isinstance(item, DistributionRelation) for item in session.added)

    def test_bind_superior_should_reject_mutual_superior(self):
        invitee_id = uuid4()
        inviter_id = uuid4()
        inviter = _account()
        reverse = _relation(inviter_id, invitee_id)
        session = _SessionStub([
            _QueryStub(one_or_none_result=inviter),
            _QueryStub(one_or_none_result=reverse),
        ])
        service = DistributionService(session=session)
        with pytest.raises(FailException, match="互为上下级"):
            service.bind_superior(invitee_id, inviter.id)

    def test_unbind_superior_should_delete_relation(self):
        invitee_id = uuid4()
        relation = _relation(invitee_id, uuid4())
        session = _SessionStub([_QueryStub(one_or_none_result=relation)])
        service = DistributionService(session=session)
        assert service.unbind_superior(invitee_id) is True
        assert session.deleted == [relation]


class TestCommissionRate:
    def test_rate_should_be_20_percent_until_five_subordinates(self):
        account = BalanceAccount(account_id=uuid4(), high_rate_locked=False)
        service = DistributionService(session=_SessionStub())
        assert service.commission_rate(account, 4) == Decimal("0.20")
        assert account.high_rate_locked is False

    def test_rate_should_lock_30_percent_at_five_subordinates(self):
        account = BalanceAccount(account_id=uuid4(), high_rate_locked=False)
        service = DistributionService(session=_SessionStub())
        rate = service.commission_rate(account, 5)
        assert rate == Decimal("0.30")
        assert account.high_rate_locked is True
        assert service.commission_rate(account, 2) == Decimal("0.30")


class TestSettleCommission:
    def test_settle_redeem_should_credit_inviter_at_20_percent(self):
        account_id = uuid4()
        inviter_id = uuid4()
        plan = _plan()
        source_id = uuid4()
        balance_stub = _BalanceStub()
        service = DistributionService(
            session=_SessionStub([
                _QueryStub(one_or_none_result=_relation(account_id, inviter_id)),
                _QueryStub(count_result=2),
            ]),
            balance_service=balance_stub,
            feature_flag_service=_FlagStub(enabled=True),
        )
        service.settle_commission_for_redeem(account_id, plan, source_id)
        assert len(balance_stub.credits) == 1
        credit = balance_stub.credits[0]
        assert credit["account_id"] == inviter_id
        assert float(credit["amount"]) == 20.00
        assert credit["amount_type"] == "commission"
        assert credit["source"] == "redeem_code"
        assert credit["source_id"] == source_id
        assert float(credit["rate"]) == 0.20

    def test_settle_redeem_should_credit_inviter_at_30_percent_when_locked(self):
        account_id = uuid4()
        inviter_id = uuid4()
        plan = _plan()
        balance_stub = _BalanceStub()
        relation = _relation(account_id, inviter_id)
        locked_account = BalanceAccount(account_id=inviter_id, high_rate_locked=True)
        session = _SessionStub([
            _QueryStub(one_or_none_result=relation),
        ])
        balance_stub = _BalanceStub()
        balance_stub.ensure_account = lambda _aid: locked_account
        service = DistributionService(
            session=session,
            balance_service=balance_stub,
            feature_flag_service=_FlagStub(enabled=True),
        )
        service.settle_commission_for_redeem(account_id, plan, uuid4())
        assert float(balance_stub.credits[0]["amount"]) == 30.00
        assert float(balance_stub.credits[0]["rate"]) == 0.30


class TestListCommissions:
    @staticmethod
    def _tx(account_id, amount):
        return BalanceTransaction(
            id=uuid4(),
            account_id=account_id,
            amount=amount,
            balance_after=Decimal("0.00"),
            amount_type="commission",
            rate=Decimal("0.20"),
            source="order",
            source_id=uuid4(),
            description="下级购买返佣 20%",
            created_at=datetime(2026, 8, 1, 0, 0, 0),
        )

    def test_without_user_should_return_all_commissions_with_account_names(self):
        account_id = uuid4()
        tx = self._tx(account_id, Decimal("20.00"))
        account = Account(
            id=account_id,
            name="DistA",
            username="distA",
            email="",
        )
        session = _SessionStub([
            _QueryStub(count_result=1, all_result=[tx]),
            _QueryStub(all_result=[account]),
        ])
        service = DistributionService(session=session)

        result = service.list_commissions(current_page=1, page_size=20)

        assert result["paginator"]["total_record"] == 1
        assert result["list"][0]["account_name"] == "DistA"
        assert float(result["list"][0]["amount"]) == 20.00
        assert result["list"][0]["rate"] == 20.0

    def test_with_user_should_filter_by_account(self):
        account_id = uuid4()
        tx = self._tx(account_id, Decimal("12.00"))
        session = _SessionStub([
            _QueryStub(count_result=1, all_result=[tx]),
            _QueryStub(all_result=[]),
        ])
        service = DistributionService(session=session)

        result = service.list_commissions(account_id, current_page=1, page_size=20)

        assert result["list"][0]["account_id"] == str(account_id)
        assert result["list"][0]["account_name"] is None

    def test_settle_should_skip_when_disabled_or_no_relation(self):
        account_id = uuid4()
        plan = _plan()
        source_id = uuid4()
        balance_stub = _BalanceStub()
        service = DistributionService(
            session=_SessionStub([_QueryStub(one_or_none_result=None)]),
            balance_service=balance_stub,
            feature_flag_service=_FlagStub(enabled=False),
        )
        service.settle_commission_for_redeem(account_id, plan, source_id)
        assert balance_stub.credits == []

    def test_settle_order_should_only_tax_direct_purchases(self):
        account_id = uuid4()
        inviter_id = uuid4()
        balance_stub = _BalanceStub()
        service = DistributionService(
            session=_SessionStub([
                _QueryStub(one_or_none_result=_relation(account_id, inviter_id)),
            ]),
            balance_service=balance_stub,
            feature_flag_service=_FlagStub(enabled=True),
        )
        membership_order = PurchaseOrder(account_id=account_id, plan_type="membership", amount="100.00", status="paid")
        balance_order = PurchaseOrder(account_id=account_id, plan_type="balance", amount="100.00", status="paid")
        service.settle_commission_for_order(account_id, membership_order)
        assert len(balance_stub.credits) == 1
        service.settle_commission_for_order(account_id, balance_order)
        assert len(balance_stub.credits) == 1


class TestDistributionQueries:
    def test_my_distribution_summary_should_return_shape(self):
        account_id = uuid4()
        referral = ReferralCode(account_id=account_id, code="CODE1234")
        session = _SessionStub([
            _QueryStub(one_or_none_result=referral),
            _QueryStub(one_or_none_result=None),   # relation
            _QueryStub(count_result=3),            # subordinate count
        ])
        balance_stub = _BalanceStub()
        service = DistributionService(session=session, balance_service=balance_stub)
        summary = service.my_distribution_summary(account_id, base_url="http://localhost/")
        assert summary["referral_code"] == "CODE1234"
        assert summary["share_url"] == "http://localhost/register?invite=CODE1234"
        assert summary["superior"] is None
        assert summary["subordinate_count"] == 3
        assert summary["commission_rate"] == "20"

    def test_timestamp_helper(self):
        value = datetime(2030, 1, 1, 0, 0, 0)
        assert DistributionService._timestamp(value) == int(value.replace(tzinfo=UTC).timestamp())