from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy.exc import IntegrityError

from internal.exception import FailException, NotFoundException
from internal.model.billing import CreditAccount, CreditTransaction, Membership, Plan, RedeemCode, RedeemCodeBatch
from internal.service.admin_redeem_code_service import AdminRedeemCodeService
from internal.service.redeem_code_service import RedeemCodeService


class _QueryStub:
    def __init__(self, *, one_or_none_result=None, all_result=None, count_result=None):
        self._one_or_none_result = one_or_none_result
        self._all_result = [] if all_result is None else all_result
        self._count_result = len(self._all_result) if count_result is None else count_result
        self.filters = []
        self.order_by_args = []
        self.locked = False

    def filter(self, *args, **kwargs):
        self.filters.append((args, kwargs))
        return self

    def order_by(self, *args):
        self.order_by_args.append(args)
        return self

    def with_for_update(self):
        self.locked = True
        return self

    def one_or_none(self):
        return self._one_or_none_result

    def all(self):
        return self._all_result

    def count(self):
        return self._count_result


class _SessionStub:
    def __init__(self, queries=None, commit_error=None):
        self._queries = list(queries or [])
        self._commit_error = commit_error
        self.added = []
        self.commits = 0
        self.rollbacks = 0
        self.flushes = 0

    def query(self, *_args, **_kwargs):
        if self._queries:
            return self._queries.pop(0)
        return _QueryStub()

    def add(self, value):
        self.added.append(value)

    def commit(self):
        self.commits += 1
        if self._commit_error:
            raise self._commit_error

    def rollback(self):
        self.rollbacks += 1

    def flush(self):
        self.flushes += 1


def _plan(**kwargs):
    defaults = {
        "id": uuid4(),
        "code": "pro",
        "name": "Pro",
        "duration_days": 30,
        "grant_token_credits": 100,
        "status": "active",
    }
    defaults.update(kwargs)
    return Plan(**defaults)


VALID_CODE = "OA-ABCDEFGHIJKLMNOPQRSTUVWX"
USED_CODE = "OA-USEDABCDEFGHIJKLMNOPQRST"
DISABLED_CODE = "OA-DISABLEDABCDEFGHIJKLMNOP"
EXPIRED_CODE = "OA-EXPIREDABCDEFGHIJKLMNOPQ"
MISSING_CODE = "OA-MISSINGABCDEFGHIJKLMNOPQ"


def _batch(**kwargs):
    defaults = {
        "id": uuid4(),
        "name": "Batch",
        "plan_id": uuid4(),
        "quantity": 1,
        "status": "active",
        "disabled_at": None,
    }
    defaults.update(kwargs)
    return RedeemCodeBatch(**defaults)


def _code(plain_code=VALID_CODE, **kwargs):
    defaults = {
        "id": uuid4(),
        "batch_id": uuid4(),
        "plan_id": uuid4(),
        "code_hash": AdminRedeemCodeService.hash_code(plain_code),
        "code_mask": AdminRedeemCodeService.mask_code(plain_code),
        "status": "unused",
        "redeemed_by": None,
        "redeemed_at": None,
        "expires_at": datetime.now(UTC).replace(tzinfo=None) + timedelta(days=7),
        "disabled_at": None,
    }
    defaults.update(kwargs)
    return RedeemCode(**defaults)


class TestRedeemCodeService:
    def test_redeem_code_should_create_membership_credit_account_and_transaction(self):
        account_id = uuid4()
        plain_code = VALID_CODE
        plan = _plan()
        batch = _batch(plan_id=plan.id)
        redeem_code = _code(plain_code, batch_id=batch.id, plan_id=plan.id)
        session = _SessionStub([
            _QueryStub(one_or_none_result=redeem_code),
            _QueryStub(one_or_none_result=batch),
            _QueryStub(one_or_none_result=plan),
            _QueryStub(one_or_none_result=None),
            _QueryStub(one_or_none_result=None),
        ])
        service = RedeemCodeService(session=session)

        result = service.redeem(account_id, plain_code)

        assert result["plan"]["code"] == "pro"
        assert result["credit_account"]["balance"] == 100
        assert redeem_code.status == "used"
        assert redeem_code.redeemed_by == account_id
        assert redeem_code.redeemed_at is not None
        assert any(isinstance(item, Membership) for item in session.added)
        assert any(isinstance(item, CreditAccount) for item in session.added)
        assert any(isinstance(item, CreditTransaction) for item in session.added)
        assert session.commits == 1

    def test_redeem_code_should_lock_code_row_before_granting_benefits(self):
        account_id = uuid4()
        plan = _plan()
        batch = _batch(plan_id=plan.id)
        redeem_code = _code(VALID_CODE, batch_id=batch.id, plan_id=plan.id)
        code_query = _QueryStub(one_or_none_result=redeem_code)
        service = RedeemCodeService(session=_SessionStub([
            code_query,
            _QueryStub(one_or_none_result=batch),
            _QueryStub(one_or_none_result=plan),
            _QueryStub(one_or_none_result=None),
            _QueryStub(one_or_none_result=None),
            _QueryStub(one_or_none_result=None),
        ]))

        service.redeem(account_id, VALID_CODE)

        assert code_query.locked is True

    def test_redeem_code_should_reject_when_credit_transaction_already_exists(self):
        account_id = uuid4()
        plan = _plan()
        batch = _batch(plan_id=plan.id)
        redeem_code = _code(VALID_CODE, batch_id=batch.id, plan_id=plan.id)
        existing_transaction = CreditTransaction(
            account_id=account_id,
            amount=plan.grant_token_credits,
            balance_after=100,
            transaction_type="redeem_grant",
            source="redeem_code",
            source_id=redeem_code.id,
            description="卡密兑换赠送算力值",
        )
        credit_account = CreditAccount(account_id=account_id, balance=100, total_granted=100, total_consumed=0)
        session = _SessionStub([
            _QueryStub(one_or_none_result=redeem_code),
            _QueryStub(one_or_none_result=batch),
            _QueryStub(one_or_none_result=plan),
            _QueryStub(one_or_none_result=existing_transaction),
            _QueryStub(one_or_none_result=None),
            _QueryStub(one_or_none_result=credit_account),
        ])
        service = RedeemCodeService(session=session)

        with pytest.raises(FailException, match="该卡密已被兑换"):
            service.redeem(account_id, VALID_CODE)

        assert credit_account.balance == 100
        assert not any(isinstance(item, CreditTransaction) for item in session.added)
        assert session.commits == 0

    def test_redeem_code_should_rollback_and_raise_clear_message_on_idempotent_conflict(self):
        account_id = uuid4()
        plan = _plan()
        batch = _batch(plan_id=plan.id)
        redeem_code = _code(VALID_CODE, batch_id=batch.id, plan_id=plan.id)
        session = _SessionStub([
            _QueryStub(one_or_none_result=redeem_code),
            _QueryStub(one_or_none_result=batch),
            _QueryStub(one_or_none_result=plan),
            _QueryStub(one_or_none_result=None),
            _QueryStub(one_or_none_result=None),
            _QueryStub(one_or_none_result=None),
        ], commit_error=IntegrityError("insert", {}, Exception("credit_transaction_source_type_unique_idx")))
        service = RedeemCodeService(session=session)

        with pytest.raises(FailException, match="该卡密已被兑换"):
            service.redeem(account_id, VALID_CODE)

        assert session.rollbacks == 1

    def test_redeem_code_should_extend_existing_same_plan_membership(self):
        account_id = uuid4()
        plain_code = VALID_CODE
        plan = _plan(duration_days=30)
        batch = _batch(plan_id=plan.id)
        redeem_code = _code(plain_code, batch_id=batch.id, plan_id=plan.id)
        existing_membership = Membership(
            account_id=account_id,
            plan_id=plan.id,
            status="active",
            started_at=datetime.now(UTC).replace(tzinfo=None) - timedelta(days=1),
            expires_at=datetime.now(UTC).replace(tzinfo=None) + timedelta(days=10),
        )
        credit_account = CreditAccount(account_id=account_id, balance=50, total_granted=50, total_consumed=0)
        service = RedeemCodeService(session=_SessionStub([
            _QueryStub(one_or_none_result=redeem_code),
            _QueryStub(one_or_none_result=batch),
            _QueryStub(one_or_none_result=plan),
            _QueryStub(one_or_none_result=None),
            _QueryStub(one_or_none_result=existing_membership),
            _QueryStub(one_or_none_result=credit_account),
        ]))
        before_expires_at = existing_membership.expires_at

        result = service.redeem(account_id, plain_code)

        assert existing_membership.expires_at > before_expires_at + timedelta(days=29)
        assert credit_account.balance == 150
        assert result["credit_account"]["balance"] == 150

    @pytest.mark.parametrize(
        ("plain_code", "expected_message"),
        [
            ("", "请输入卡密"),
            ("   ", "请输入卡密"),
        ],
    )
    def test_redeem_code_should_reject_blank_code_with_clear_message(self, plain_code, expected_message):
        service = RedeemCodeService(session=_SessionStub())

        with pytest.raises(FailException, match=expected_message):
            service.redeem(uuid4(), plain_code)

    @pytest.mark.parametrize(
        ("plain_code", "expected_message"),
        [
            ("OA-INVALID", "卡密格式错误，请检查后重新输入"),
            ("这不是卡密", "卡密格式错误，请检查后重新输入"),
        ],
    )
    def test_redeem_code_should_reject_invalid_format_with_clear_message(self, plain_code, expected_message):
        service = RedeemCodeService(session=_SessionStub())

        with pytest.raises(FailException, match=expected_message):
            service.redeem(uuid4(), plain_code)

    @pytest.mark.parametrize(
        ("plain_code", "redeem_code", "expected_message"),
        [
            (USED_CODE, _code(USED_CODE, status="used"), "该卡密已被兑换"),
            (DISABLED_CODE, _code(DISABLED_CODE, status="disabled"), "该卡密已被禁用，请联系客服"),
            (DISABLED_CODE, _code(DISABLED_CODE, disabled_at=datetime.now(UTC).replace(tzinfo=None)), "该卡密已被禁用，请联系客服"),
            (EXPIRED_CODE, _code(EXPIRED_CODE, expires_at=datetime.now(UTC).replace(tzinfo=None) - timedelta(days=1)), "该卡密已过期"),
        ],
    )
    def test_redeem_code_should_reject_unredeemable_code_with_clear_message(self, plain_code, redeem_code, expected_message):
        account_id = uuid4()
        service = RedeemCodeService(session=_SessionStub([_QueryStub(one_or_none_result=redeem_code)]))

        with pytest.raises(FailException, match=expected_message):
            service.redeem(account_id, plain_code)

    def test_redeem_code_should_reject_disabled_batch_with_clear_message(self):
        batch = _batch(status="disabled", disabled_at=datetime.now(UTC).replace(tzinfo=None))
        redeem_code = _code(VALID_CODE, batch_id=batch.id)
        service = RedeemCodeService(session=_SessionStub([
            _QueryStub(one_or_none_result=redeem_code),
            _QueryStub(one_or_none_result=batch),
        ]))

        with pytest.raises(FailException, match="该批次已被禁用，请联系客服"):
            service.redeem(uuid4(), VALID_CODE)

    def test_redeem_code_should_raise_not_found_when_code_missing(self):
        service = RedeemCodeService(session=_SessionStub([_QueryStub(one_or_none_result=None)]))

        with pytest.raises(NotFoundException, match="卡密不存在，请检查后重新输入"):
            service.redeem(uuid4(), MISSING_CODE)

    def test_redeem_code_should_raise_clear_message_when_plan_missing(self):
        batch = _batch()
        redeem_code = _code(VALID_CODE, batch_id=batch.id)
        service = RedeemCodeService(session=_SessionStub([
            _QueryStub(one_or_none_result=redeem_code),
            _QueryStub(one_or_none_result=batch),
            _QueryStub(one_or_none_result=None),
        ]))

        with pytest.raises(NotFoundException, match="关联套餐不存在，请联系客服"):
            service.redeem(uuid4(), VALID_CODE)

    def test_redeem_code_should_raise_clear_message_when_plan_disabled(self):
        plan = _plan(status="disabled")
        batch = _batch(plan_id=plan.id)
        redeem_code = _code(VALID_CODE, batch_id=batch.id, plan_id=plan.id)
        service = RedeemCodeService(session=_SessionStub([
            _QueryStub(one_or_none_result=redeem_code),
            _QueryStub(one_or_none_result=batch),
            _QueryStub(one_or_none_result=plan),
        ]))

        with pytest.raises(FailException, match="关联套餐已禁用，请联系客服"):
            service.redeem(uuid4(), VALID_CODE)

    def test_list_redeem_records_should_return_user_redeemed_codes_with_plan_and_membership(self):
        account_id = uuid4()
        plan = _plan(name="Pro", grant_token_credits=100000)
        redeemed_at = datetime(2030, 1, 1, 0, 0, 0)
        membership = Membership(
            account_id=account_id,
            plan_id=plan.id,
            status="active",
            started_at=redeemed_at,
            expires_at=datetime(2030, 2, 1, 0, 0, 0),
            source="redeem_code",
            source_id=None,
        )
        redeem_code = _code(VALID_CODE, plan_id=plan.id, status="used", redeemed_by=account_id, redeemed_at=redeemed_at)
        membership.source_id = redeem_code.id
        service = RedeemCodeService(session=_SessionStub([
            _QueryStub(all_result=[redeem_code]),
            _QueryStub(one_or_none_result=plan),
            _QueryStub(one_or_none_result=membership),
        ]))

        result = service.list_redeem_records(account_id)

        assert result["list"][0]["code_mask"] == redeem_code.code_mask
        assert result["list"][0]["redeemed_at"] == 1893456000
        assert result["list"][0]["plan"]["name"] == "Pro"
        assert result["list"][0]["grant_token_credits"] == 100000
        assert result["list"][0]["membership_expires_at"] == 1896134400

    def test_get_membership_summary_should_return_current_membership_and_credit_account(self):
        account_id = uuid4()
        plan = _plan()
        membership = Membership(
            account_id=account_id,
            plan_id=plan.id,
            status="active",
            started_at=datetime(2030, 1, 1, 0, 0, 0),
            expires_at=datetime(2030, 2, 1, 0, 0, 0),
        )
        credit_account = CreditAccount(account_id=account_id, balance=100, total_granted=120, total_consumed=20)
        service = RedeemCodeService(session=_SessionStub([
            _QueryStub(one_or_none_result=membership),
            _QueryStub(one_or_none_result=plan),
            _QueryStub(one_or_none_result=credit_account),
            _QueryStub(all_result=[]),
        ]))

        result = service.get_membership_summary(account_id)

        assert result["membership"]["plan"]["code"] == "pro"
        assert result["credit_account"]["balance"] == 100
        assert result["recent_transactions"] == []
