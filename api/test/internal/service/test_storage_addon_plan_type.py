from uuid import uuid4

import pytest
from werkzeug.datastructures import MultiDict

from internal.entity.storage_quota_entity import StorageAddonPlanType
from internal.exception import FailException
from internal.model.billing import CreditAccount, CreditTransaction, Membership, Plan
from internal.model.distribution import PurchaseOrder
from internal.schema.admin_billing_plan_schema import UpsertAdminPlanReq
from internal.service.order_service import OrderService

STORAGE_ADDON = StorageAddonPlanType.STORAGE_ADDON.value


def test_schema_accepts_storage_addon_plan_type():
    form = UpsertAdminPlanReq(MultiDict({"plan_type": "storage_addon"}))
    assert form.validate(), form.errors


def test_schema_still_rejects_unknown_plan_type():
    form = UpsertAdminPlanReq(MultiDict({"plan_type": "unknown_type"}))
    assert not form.validate()


class _QueryStub:
    def __init__(self, *, one_or_none_result=None, first_result=None, count_result=0, all_result=None):
        self._one_or_none_result = one_or_none_result
        self._first_result = first_result
        self._count_result = count_result
        self._all_result = [] if all_result is None else all_result

    def filter(self, *args, **kwargs):
        return self

    def order_by(self, *args, **kwargs):
        return self

    def with_for_update(self):
        return self

    def one_or_none(self):
        return self._one_or_none_result

    def first(self):
        return self._first_result

    def all(self):
        return self._all_result

    def count(self):
        return self._count_result

    def offset(self, _value):
        return self

    def limit(self, _value):
        return self


class _SessionStub:
    def __init__(self, queries=None):
        self._queries = list(queries or [])
        self.added = []
        self.commits = 0

    def query(self, *_args, **_kwargs):
        if self._queries:
            return self._queries.pop(0)
        return _QueryStub()

    def add(self, value):
        self.added.append(value)

    def commit(self):
        self.commits += 1

    def rollback(self):
        pass


class _PaymentConfigStub:
    def __init__(self, enabled=True):
        self.enabled = enabled

    def is_enabled(self, provider):
        return self.enabled

    def get(self, provider):
        return None

    def decrypt_payload(self, config):
        return config or {}


class _DistributionStub:
    def __init__(self):
        self.settles = []

    def settle_commission_for_order(self, account_id, order):
        self.settles.append({"account_id": account_id, "plan_type": order.plan_type})


class _BalanceStub:
    def __init__(self):
        self.credits = []

    def ensure_account(self, account_id):
        raise AssertionError("storage_addon 不应触发余额账户操作")

    def credit(self, *args, **kwargs):
        self.credits.append((args, kwargs))
        return object()


def _plan(plan_type=STORAGE_ADDON, price="30.00", duration_days=0, grant=0):
    return Plan(
        id=uuid4(),
        code="storage-100g",
        name="存储扩展包 100G",
        plan_type=plan_type,
        price=price,
        duration_days=duration_days,
        grant_token_credits=grant,
        status="active",
    )


def _make_service(session, distribution_service=None):
    return OrderService(
        session=session,
        balance_service=_BalanceStub(),
        distribution_service=distribution_service,
        payment_config_service=_PaymentConfigStub(),
    )


def test_create_order_accepts_storage_addon_plan_type():
    account_id = uuid4()
    plan = _plan()
    session = _SessionStub([
        _QueryStub(one_or_none_result=plan),   # create_order: 查套餐
        _QueryStub(first_result=None),         # order_no 唯一性
    ])
    service = _make_service(session)

    order = service.create_order(account_id, plan.id, "balance")

    assert order.plan_type == STORAGE_ADDON
    assert order.status == "pending"
    assert order.pay_method == "balance"
    assert float(order.amount) == 30.00


def test_create_order_rejects_unknown_plan_type():
    plan = _plan(plan_type="unknown_type")
    session = _SessionStub([_QueryStub(one_or_none_result=plan)])
    service = _make_service(session)

    with pytest.raises(FailException, match="套餐类型无效"):
        service.create_order(uuid4(), plan.id, "balance")


def test_fulfill_rights_should_skip_membership_and_credits_for_storage_addon(monkeypatch):
    account_id = uuid4()
    plan = _plan()
    order = PurchaseOrder(
        account_id=account_id,
        plan_id=plan.id,
        plan_type=STORAGE_ADDON,
        amount="30.00",
        status="paid",
    )
    session = _SessionStub([_QueryStub(one_or_none_result=plan)])   # _fulfill_rights 查套餐
    service = _make_service(session)

    calls = {"membership": 0, "credits": 0}
    monkeypatch.setattr(service, "_upsert_membership", lambda *a, **k: calls.__setitem__("membership", calls["membership"] + 1))
    monkeypatch.setattr(service, "_grant_credits", lambda *a, **k: calls.__setitem__("credits", calls["credits"] + 1))

    service._fulfill_rights(order)

    assert calls == {"membership": 0, "credits": 0}


def test_fulfill_rights_still_grants_membership_for_membership_plan(monkeypatch):
    account_id = uuid4()
    plan = _plan(plan_type="membership", price="100.00", duration_days=30, grant=5000)
    order = PurchaseOrder(
        account_id=account_id,
        plan_id=plan.id,
        plan_type="membership",
        amount="100.00",
        status="paid",
    )
    session = _SessionStub([_QueryStub(one_or_none_result=plan)])
    service = _make_service(session)

    calls = {"membership": 0, "credits": 0}
    monkeypatch.setattr(service, "_upsert_membership", lambda *a, **k: calls.__setitem__("membership", calls["membership"] + 1))
    monkeypatch.setattr(service, "_grant_credits", lambda *a, **k: calls.__setitem__("credits", calls["credits"] + 1))

    service._fulfill_rights(order)

    assert calls == {"membership": 1, "credits": 1}


def test_confirm_paid_storage_addon_should_not_add_membership_or_credit_rows():
    account_id = uuid4()
    plan = _plan()
    order = PurchaseOrder(
        account_id=account_id,
        order_no="PO-ADDON-1",
        plan_id=plan.id,
        plan_type=STORAGE_ADDON,
        amount="30.00",
        pay_method="balance",
        status="pending",
    )
    session = _SessionStub([
        _QueryStub(one_or_none_result=plan),   # _fulfill_rights 查套餐
        _QueryStub(one_or_none_result=plan),   # _maybe_enable_auto_renewal 查套餐
    ])
    service = _make_service(session, distribution_service=_DistributionStub())

    result = service.confirm_paid(order, transaction_id="T-ADDON")

    assert result is order
    assert order.status == "paid"
    assert order.transaction_id == "T-ADDON"
    assert all(not isinstance(item, (Membership, CreditAccount, CreditTransaction)) for item in session.added)
    assert session.commits == 1
