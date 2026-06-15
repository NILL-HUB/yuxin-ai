from datetime import datetime
from uuid import uuid4

from internal.model.billing import CreditAccount, CreditTransaction
from internal.service.credit_service import CreditService


class _QueryStub:
    def __init__(self, *, one_or_none_result=None):
        self._one_or_none_result = one_or_none_result
        self.filters = []
        self.locked = False

    def filter(self, *args, **kwargs):
        self.filters.append((args, kwargs))
        return self

    def with_for_update(self):
        self.locked = True
        return self

    def one_or_none(self):
        return self._one_or_none_result


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


def _account(balance=100, total_consumed=0):
    return CreditAccount(account_id=uuid4(), balance=balance, total_granted=balance, total_consumed=total_consumed)


def _transaction(account_id, amount=-2, balance_after=98):
    return CreditTransaction(
        account_id=account_id,
        amount=amount,
        balance_after=balance_after,
        transaction_type="consume",
        source="message",
        source_id=uuid4(),
        description="模型调用消耗算力值",
        created_at=datetime(2030, 1, 1, 0, 0, 0),
    )


class TestCreditService:
    def test_compute_units_should_round_up_per_1000_tokens(self):
        assert CreditService.compute_units_from_tokens(0) == 0
        assert CreditService.compute_units_from_tokens(1) == 1
        assert CreditService.compute_units_from_tokens(999) == 1
        assert CreditService.compute_units_from_tokens(1000) == 1
        assert CreditService.compute_units_from_tokens(1001) == 2
        assert CreditService.compute_units_from_tokens(2500) == 3

    def test_consume_for_message_should_deduct_compute_units_and_write_transaction(self):
        account_id = uuid4()
        message_id = uuid4()
        credit_account = CreditAccount(account_id=account_id, balance=100, total_granted=100, total_consumed=0)
        account_query = _QueryStub(one_or_none_result=credit_account)
        session = _SessionStub([
            _QueryStub(one_or_none_result=None),
            account_query,
        ])
        service = CreditService(session=session)

        result = service.consume_for_message(account_id, message_id, token_count=2500)

        assert account_query.locked is True
        assert credit_account.balance == 97
        assert credit_account.total_consumed == 3
        assert result["amount"] == -3
        assert result["balance_after"] == 97
        assert result["compute_units"] == 3
        assert result["token_count"] == 2500
        assert result["idempotent"] is False
        assert len(session.added) == 1
        assert isinstance(session.added[0], CreditTransaction)
        assert session.added[0].amount == -3
        assert session.added[0].transaction_type == "consume"
        assert session.added[0].source == "message"
        assert session.added[0].source_id == message_id
        assert "2500 token" in session.added[0].description

    def test_consume_for_message_should_be_idempotent_by_message_id(self):
        account_id = uuid4()
        message_id = uuid4()
        existing = _transaction(account_id=account_id)
        existing.source_id = message_id
        service = CreditService(session=_SessionStub([_QueryStub(one_or_none_result=existing)]))

        result = service.consume_for_message(account_id, message_id, token_count=2500)

        assert result["idempotent"] is True
        assert result["amount"] == existing.amount
        assert result["balance_after"] == existing.balance_after

    def test_consume_for_message_should_deduct_available_balance_only_when_insufficient(self):
        account_id = uuid4()
        message_id = uuid4()
        credit_account = CreditAccount(account_id=account_id, balance=2, total_granted=2, total_consumed=0)
        service = CreditService(session=_SessionStub([
            _QueryStub(one_or_none_result=None),
            _QueryStub(one_or_none_result=credit_account),
        ]))

        result = service.consume_for_message(account_id, message_id, token_count=5000)

        assert credit_account.balance == 0
        assert credit_account.total_consumed == 2
        assert result["amount"] == -2
        assert result["balance_after"] == 0
        assert result["compute_units"] == 5
        assert result["actual_compute_units"] == 2
        assert result["insufficient"] is True

    def test_consume_for_message_should_create_zero_balance_account_when_missing(self):
        account_id = uuid4()
        message_id = uuid4()
        session = _SessionStub([
            _QueryStub(one_or_none_result=None),
            _QueryStub(one_or_none_result=None),
        ])
        service = CreditService(session=session)

        result = service.consume_for_message(account_id, message_id, token_count=1000)

        created_account = next(item for item in session.added if isinstance(item, CreditAccount))
        transaction = next(item for item in session.added if isinstance(item, CreditTransaction))
        assert created_account.account_id == account_id
        assert created_account.balance == 0
        assert transaction.amount == 0
        assert result["amount"] == 0
        assert result["insufficient"] is True

    def test_consume_for_message_should_skip_zero_token_usage(self):
        service = CreditService(session=_SessionStub())

        result = service.consume_for_message(uuid4(), uuid4(), token_count=0)

        assert result == {"skipped": True, "reason": "zero_token_usage"}
