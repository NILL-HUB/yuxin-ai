from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import uuid4

from internal.model.billing import CreditAccount, CreditTransaction, Membership
from internal.service.credit_service import CreditService

ACCOUNT_ID = uuid4()
TASK_ID = uuid4()


class _QueryStub:
    def __init__(self, *, one_or_none_result=None, all_result=None, first_result=None):
        self._one_or_none_result = one_or_none_result
        self._all_result = all_result
        self._first_result = first_result
        self.filters = []
        self.locked = False

    def filter(self, *args, **kwargs):
        self.filters.append((args, kwargs))
        return self

    def order_by(self, *args, **kwargs):
        return self

    def with_for_update(self):
        self.locked = True
        return self

    def one_or_none(self):
        return self._one_or_none_result

    def first(self):
        return self._first_result

    def all(self):
        return self._all_result or []


class _SessionStub:
    def __init__(self, queries=None):
        self._queries = list(queries or [])
        self.added = []
        self.commits = 0
        self.flushes = 0

    def query(self, *_args, **_kwargs):
        if self._queries:
            return self._queries.pop(0)
        return _QueryStub()

    def add(self, value):
        self.added.append(value)

    def commit(self):
        self.commits += 1

    def flush(self):
        self.flushes += 1


def _membership(account_id, *, expires_days=29):
    return Membership(
        account_id=account_id,
        plan_id=uuid4(),
        status="active",
        started_at=datetime.now(UTC).replace(tzinfo=None) - timedelta(days=1),
        expires_at=datetime.now(UTC).replace(tzinfo=None) + timedelta(days=expires_days),
        source="redeem_code",
        source_id=uuid4(),
    )


def _expired_membership(account_id):
    return Membership(
        account_id=account_id,
        plan_id=uuid4(),
        status="active",
        started_at=datetime.now(UTC).replace(tzinfo=None) - timedelta(days=40),
        expires_at=datetime.now(UTC).replace(tzinfo=None) - timedelta(days=10),
        source="redeem_code",
        source_id=uuid4(),
    )


def _transaction(account_id, amount=-2, balance_after=98):
    return CreditTransaction(
        account_id=account_id,
        amount=amount,
        balance_after=balance_after,
        transaction_type="consume",
        source="message",
        source_id=uuid4(),
        description="模型调用消耗算力值",
    )


def _consume_stubs(credit_account, membership):
    return [
        _QueryStub(one_or_none_result=None),   # billing config（默认汇率）
        _QueryStub(one_or_none_result=None),   # existing message consume
        _QueryStub(one_or_none_result=credit_account),  # credit account (locked)
        _QueryStub(first_result=membership),   # current membership
    ]


class TestCreditService:
    def test_compute_units_should_round_up_per_1000_tokens(self):
        assert CreditService.compute_units_from_tokens(0) == 0
        assert CreditService.compute_units_from_tokens(1) == 1
        assert CreditService.compute_units_from_tokens(999) == 1
        assert CreditService.compute_units_from_tokens(1000) == 1
        assert CreditService.compute_units_from_tokens(1001) == 2
        assert CreditService.compute_units_from_tokens(2500) == 3

    def test_consume_should_refresh_quota_when_cycle_due(self):
        account_id = uuid4()
        message_id = uuid4()
        now = datetime.now(UTC).replace(tzinfo=None)
        credit_account = CreditAccount(
            account_id=account_id,
            permanent_credit=0,
            quota_credit=10,
            total_granted=100,
            total_consumed=50,
            quota_granted=100,
            quota_cycle_days=30,
            quota_reset_at=now - timedelta(days=1),
        )
        account_query = _QueryStub(one_or_none_result=credit_account)
        session = _SessionStub([
            _QueryStub(one_or_none_result=None),                      # billing config（默认汇率）
            _QueryStub(one_or_none_result=None),                      # existing message consume
            account_query,                                            # credit account (locked)
            _QueryStub(first_result=_membership(account_id)),         # current membership
        ])
        service = CreditService(session=session)

        result = service.consume_for_message(account_id, message_id, token_count=2500)

        assert credit_account.quota_credit == 97          # 回满 100 后扣 3
        assert credit_account.quota_reset_at >= now + timedelta(days=29)
        assert result["amount"] == -3
        assert result["balance_after"] == 97

    def test_consume_should_not_refresh_when_cycle_not_due(self):
        account_id = uuid4()
        message_id = uuid4()
        now = datetime.now(UTC).replace(tzinfo=None)
        credit_account = CreditAccount(
            account_id=account_id,
            permanent_credit=0,
            quota_credit=10,
            total_granted=100,
            total_consumed=50,
            quota_granted=100,
            quota_cycle_days=30,
            quota_reset_at=now + timedelta(days=5),
        )
        session = _SessionStub([
            _QueryStub(one_or_none_result=None),                      # billing config（默认汇率）
            _QueryStub(one_or_none_result=None),
            _QueryStub(one_or_none_result=credit_account),
            _QueryStub(first_result=_membership(account_id)),
        ])
        service = CreditService(session=session)

        result = service.consume_for_message(account_id, message_id, token_count=2500)

        assert credit_account.quota_credit == 7           # 未到周期，不刷新直接扣
        assert credit_account.quota_reset_at > now + timedelta(days=4)
        assert result["quota_used"] == 3
        assert result["permanent_used"] == 0
        assert result["insufficient"] is False
        assert result["idempotent"] is False
        assert len(session.added) == 1
        assert isinstance(session.added[0], CreditTransaction)
        assert session.added[0].amount == -3
        assert session.added[0].transaction_type == "consume"
        assert session.added[0].source == "message"
        assert session.added[0].source_id == message_id
        assert "2500 token" in session.added[0].description

    def test_consume_should_switch_to_permanent_when_quota_exhausted(self):
        account_id = uuid4()
        message_id = uuid4()
        credit_account = CreditAccount(account_id=account_id, permanent_credit=50, quota_credit=2, total_granted=52, total_consumed=0)
        service = CreditService(session=_SessionStub(_consume_stubs(credit_account, _membership(account_id))))

        result = service.consume_for_message(account_id, message_id, token_count=5000)

        assert credit_account.quota_credit == 0
        assert credit_account.permanent_credit == 47
        assert result["quota_used"] == 2
        assert result["permanent_used"] == 3
        assert result["amount"] == -5
        assert result["insufficient"] is False

    def test_consume_should_use_permanent_when_membership_expired(self):
        account_id = uuid4()
        message_id = uuid4()
        credit_account = CreditAccount(account_id=account_id, permanent_credit=100, quota_credit=100, total_granted=200, total_consumed=0)
        service = CreditService(session=_SessionStub(_consume_stubs(credit_account, _expired_membership(account_id))))

        result = service.consume_for_message(account_id, message_id, token_count=2500)

        assert credit_account.quota_credit == 100
        assert credit_account.permanent_credit == 97
        assert result["quota_used"] == 0
        assert result["permanent_used"] == 3
        assert result["insufficient"] is False

    def test_consume_for_message_should_be_idempotent_by_message_id(self):
        account_id = uuid4()
        message_id = uuid4()
        existing = _transaction(account_id=account_id)
        existing.source_id = message_id
        service = CreditService(session=_SessionStub([
            _QueryStub(one_or_none_result=None),   # billing config（默认汇率）
            _QueryStub(one_or_none_result=existing),
        ]))

        result = service.consume_for_message(account_id, message_id, token_count=2500)

        assert result["idempotent"] is True
        assert result["amount"] == existing.amount
        assert result["balance_after"] == existing.balance_after

    def test_consume_should_stop_when_both_pools_empty(self):
        account_id = uuid4()
        message_id = uuid4()
        credit_account = CreditAccount(account_id=account_id, permanent_credit=2, quota_credit=0, total_granted=2, total_consumed=0)
        service = CreditService(session=_SessionStub(_consume_stubs(credit_account, _membership(account_id))))

        result = service.consume_for_message(account_id, message_id, token_count=5000)

        assert credit_account.permanent_credit == 0
        assert credit_account.total_consumed == 2
        assert result["amount"] == -2
        assert result["balance_after"] == 0
        assert result["compute_units"] == 5
        assert result["actual_compute_units"] == 2
        assert result["insufficient"] is True
        assert result["reason"] == "credits_exhausted"

    def test_consume_should_create_zero_pools_account_when_missing(self):
        account_id = uuid4()
        message_id = uuid4()
        session = _SessionStub([
            _QueryStub(one_or_none_result=None),   # billing config（默认汇率）
            _QueryStub(one_or_none_result=None),   # existing consume
            _QueryStub(one_or_none_result=None),   # credit account
            _QueryStub(first_result=None),         # membership
        ])
        service = CreditService(session=session)

        result = service.consume_for_message(account_id, message_id, token_count=1000)

        created_account = next(item for item in session.added if isinstance(item, CreditAccount))
        transaction = next(item for item in session.added if isinstance(item, CreditTransaction))
        assert created_account.account_id == account_id
        assert created_account.permanent_credit == 0
        assert created_account.quota_credit == 0
        assert transaction.amount == 0
        assert result["amount"] == 0
        assert result["insufficient"] is True
        assert result["reason"] == "credits_exhausted"

    def test_consume_for_message_should_skip_zero_token_usage(self):
        service = CreditService(session=_SessionStub())

        result = service.consume_for_message(uuid4(), uuid4(), token_count=0)

        assert result == {"skipped": True, "reason": "zero_token_usage"}

    def test_consume_should_apply_configured_rate(self):
        account_id = uuid4()
        message_id = uuid4()
        credit_account = CreditAccount(account_id=account_id, permanent_credit=0, quota_credit=2000, total_granted=2000, total_consumed=0)
        config = SimpleNamespace(value_numeric=2)
        session = _SessionStub([
            _QueryStub(one_or_none_result=config),   # billing config（2 算力/1k token）
            _QueryStub(one_or_none_result=None),     # existing consume
            _QueryStub(one_or_none_result=credit_account),
            _QueryStub(first_result=_membership(account_id)),
        ])
        service = CreditService(session=session)

        result = service.consume_for_message(account_id, message_id, token_count=2500)

        assert credit_account.quota_credit == 1995       # 2500 × 2 / 1000 = 5
        assert result["compute_units"] == 5
        assert result["quota_used"] == 5
        assert result["permanent_used"] == 0
        assert result["credits_per_1k"] == 2
        assert "2 算力/1k token" in session.added[0].description

    def test_consume_for_feature_should_skip_system_borne_features(self):
        feature_config = SimpleNamespace(billable=False)
        session = _SessionStub([
            _QueryStub(one_or_none_result=feature_config),
        ])
        service = CreditService(session=session)

        result = service.consume_for_feature(
            uuid4(),
            "conductor",
            token_count=1000,
        )

        assert result == {
            "consumed": False,
            "reason": "system_borne",
            "token_count": 1000,
        }

    def test_consume_for_message_with_engine_fallback_keeps_existing_rate(self):
        account_id = uuid4()
        message_id = uuid4()
        credit_account = CreditAccount(account_id=account_id, permanent_credit=100, quota_credit=0, total_granted=100, total_consumed=0)
        session = _SessionStub(_consume_stubs(credit_account, _membership(account_id)))
        svc = CreditService(session=session)
        svc.pricing_engine = SimpleNamespace(
            plan_usage=lambda model_id, **kw: SimpleNamespace(
                sell_credits=2, cost_credits=0, margin_credits=2, billing_basis="global_rate"
            )
        )

        result = svc.consume_for_message(account_id, message_id, token_count=2500)

        assert result["compute_units"] >= 2
        assert result["compute_units"] == 3          # 无模型明细 → 兜底汇率 1:1：2500/1000 → 3
        assert result["billing_basis"] == "global_rate"
        assert result["credits_per_1k"] == 1
        assert result["cost_credits"] is None
        assert result["margin_credits"] is None
        assert result["permanent_used"] == 3

    def test_compute_units_with_model_id_routes_through_pricing_engine(self):
        svc = CreditService(session=_SessionStub())
        svc.pricing_engine = SimpleNamespace(
            plan_usage=lambda model_id, **kw: SimpleNamespace(
                sell_credits=5, cost_credits=2, margin_credits=3, billing_basis="model_price"
            )
        )

        units, basis, detail = svc._compute_units(0, model_id="model-1", input_tokens=1500, output_tokens=500)

        assert units == 5
        assert basis == "model_price"
        assert detail == {"cost_credits": 2, "margin_credits": 3}

    def test_compute_units_fallback_global_rate_without_model_id(self):
        session = _SessionStub([
            _QueryStub(one_or_none_result=SimpleNamespace(value_numeric=2)),
        ])
        svc = CreditService(session=session)

        units, basis, detail = svc._compute_units(2500)

        assert units == 5
        assert basis == "global_rate"
        assert detail == {"credits_per_1k": 2}

    def test_adjust_credits_positive_refunds(self):
        credit_account = CreditAccount(account_id=ACCOUNT_ID, permanent_credit=100, quota_credit=50, total_granted=150, total_consumed=0)
        session = _SessionStub([
            _QueryStub(one_or_none_result=None),            # 幂等查询：无已存在 adjust
            _QueryStub(one_or_none_result=credit_account),  # credit account（for update）
        ])
        svc = CreditService(session=session)

        result = svc.adjust_credits(
            ACCOUNT_ID,
            diff_credits=-5,          # 负 = 多扣，退还
            source="reconciliation",
            source_id=TASK_ID,
            description="对账退还",
        )

        assert result["amount"] == 5         # 退还为正
        assert result["reconciliation"] is True
        assert result["idempotent"] is False
        assert credit_account.permanent_credit == 105
        transaction = session.added[0]
        assert isinstance(transaction, CreditTransaction)
        assert transaction.amount == 5
        assert transaction.transaction_type == "adjust"
        assert transaction.source == "reconciliation"
        assert str(transaction.source_id) == str(TASK_ID)

    def test_adjust_credits_negative_charges_more(self):
        credit_account = CreditAccount(account_id=ACCOUNT_ID, permanent_credit=10, quota_credit=20, total_granted=30, total_consumed=0)
        session = _SessionStub([
            _QueryStub(one_or_none_result=None),              # 幂等查询：无已存在 adjust
            _QueryStub(one_or_none_result=credit_account),    # credit account（for update）
            _QueryStub(first_result=_membership(ACCOUNT_ID)),  # current membership
        ])
        svc = CreditService(session=session)

        result = svc.adjust_credits(
            ACCOUNT_ID,
            diff_credits=3,           # 正 = 少扣，补扣
            source="reconciliation",
            source_id=TASK_ID,
            description="对账补扣",
        )

        assert result["amount"] == -3
        assert credit_account.quota_credit == 17
        assert credit_account.permanent_credit == 10
        assert session.added[0].amount == -3
        assert session.added[0].transaction_type == "adjust"

    def test_adjust_credits_idempotent(self):
        credit_account = CreditAccount(account_id=ACCOUNT_ID, permanent_credit=10, quota_credit=20, total_granted=30, total_consumed=0)
        existing_stub = _QueryStub(one_or_none_result=None)
        session = _SessionStub([
            _QueryStub(one_or_none_result=None),              # 幂等查询：第一次无已存在 adjust
            _QueryStub(one_or_none_result=credit_account),    # credit account（for update）
            _QueryStub(first_result=_membership(ACCOUNT_ID)),  # current membership
            existing_stub,                                    # 幂等查询：第二次命中第一次的交易
        ])
        svc = CreditService(session=session)

        first = svc.adjust_credits(ACCOUNT_ID, diff_credits=3, source="reconciliation", source_id=TASK_ID, description="")
        existing_stub._one_or_none_result = session.added[0]
        second = svc.adjust_credits(ACCOUNT_ID, diff_credits=3, source="reconciliation", source_id=TASK_ID, description="")

        assert second["idempotent"] is True
        assert second["amount"] == first["amount"]
        assert second["amount"] == -3
        assert len(session.added) == 1