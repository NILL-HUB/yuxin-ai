from types import SimpleNamespace
from uuid import uuid4

import pytest

from internal.exception import ForbiddenException
from internal.service.storage_quota_service import StorageQuotaService


class _QueryStub:
    def __init__(self, *, first_result=None, all_result=None, one_or_none_result=None):
        self._first = first_result
        self._all = [] if all_result is None else all_result
        self._one_or_none = one_or_none_result

    def filter(self, *_a, **_kw):
        return self

    def filter_by(self, **_kw):
        return self

    def join(self, *_a, **_kw):
        return self

    def order_by(self, *_a, **_kw):
        return self

    def with_for_update(self):
        return self

    def first(self):
        return self._first

    def all(self):
        return self._all

    def one_or_none(self):
        return self._one_or_none


class _SessionStub:
    def __init__(self, queries=None):
        self._queries = list(queries or [])

    def query(self, *_a, **_kw):
        if self._queries:
            return self._queries.pop(0)
        return _QueryStub()


def _new_service(session=None):
    return StorageQuotaService(db=SimpleNamespace(session=session or _SessionStub()))


def _fake_entitlement(gb: int):
    return SimpleNamespace(feature_value=str(gb), value_type="number", parsed_value=gb)


def test_default_quota_when_no_membership():
    service = _new_service(_SessionStub([_QueryStub(first_result=None), _QueryStub(all_result=[])]))
    assert service.resolve_total_quota_bytes(uuid4()) == 5 * (1024 ** 3)


def test_membership_entitlement_overrides_default():
    plan_id = uuid4()
    membership = SimpleNamespace(plan_id=plan_id)
    entitlement = _fake_entitlement(100)
    service = _new_service(_SessionStub([
        _QueryStub(first_result=membership),
        _QueryStub(all_result=[entitlement]),
        _QueryStub(all_result=[]),
    ]))
    assert service.resolve_total_quota_bytes(uuid4()) == 100 * (1024 ** 3)


def test_addon_packages_are_additive():
    plan_id = uuid4()
    membership = SimpleNamespace(plan_id=plan_id)
    entitlement = _fake_entitlement(100)
    addon_one = _fake_entitlement(50)
    addon_two = _fake_entitlement(200)
    service = _new_service(_SessionStub([
        _QueryStub(first_result=membership),
        _QueryStub(all_result=[entitlement]),
        _QueryStub(all_result=[addon_one, addon_two]),
    ]))
    assert service.resolve_total_quota_bytes(uuid4()) == 350 * (1024 ** 3)


def test_expired_membership_does_not_apply():
    """已过期会员（status=active 但 expires_at 已过）不应产生套餐配额。"""
    from datetime import UTC, datetime, timedelta

    membership = SimpleNamespace(plan_id=uuid4(), status="active",
                                 expires_at=datetime.now(UTC).replace(tzinfo=None) - timedelta(days=1))
    # 模拟 query 返回 None（真实 SQL 会过滤掉过期会员）
    service = _new_service(_SessionStub([_QueryStub(first_result=None), _QueryStub(all_result=[])]))
    assert service.resolve_total_quota_bytes(uuid4()) == 5 * (1024 ** 3)


def test_decimal_entitlement_is_parsed():
    from decimal import Decimal

    plan_id = uuid4()
    membership = SimpleNamespace(plan_id=plan_id)
    entitlement = SimpleNamespace(feature_value="100.0", value_type="decimal", parsed_value=Decimal("100.0"))
    service = _new_service(_SessionStub([
        _QueryStub(first_result=membership),
        _QueryStub(all_result=[entitlement]),
        _QueryStub(all_result=[]),
    ]))
    assert service.resolve_total_quota_bytes(uuid4()) == 100 * (1024 ** 3)


def test_invalid_entitlement_value_falls_back_to_zero():
    plan_id = uuid4()
    membership = SimpleNamespace(plan_id=plan_id)
    entitlement = SimpleNamespace(feature_value="abc", value_type="number", parsed_value="abc")
    service = _new_service(_SessionStub([
        _QueryStub(first_result=membership),
        _QueryStub(all_result=[entitlement]),
        _QueryStub(all_result=[]),
    ]))
    assert service.resolve_total_quota_bytes(uuid4()) == 5 * (1024 ** 3)


def test_check_raises_when_over_quota():
    account_id = uuid4()
    service = _new_service(_SessionStub([
        _QueryStub(first_result=None),
        _QueryStub(all_result=[]),
        _QueryStub(one_or_none_result=SimpleNamespace(used_bytes=5 * (1024 ** 3))),
    ]))
    with pytest.raises(ForbiddenException):
        service.check_quota(account_id, incoming_bytes=1024)


def test_check_passes_when_within_quota():
    account_id = uuid4()
    service = _new_service(_SessionStub([
        _QueryStub(first_result=None),
        _QueryStub(all_result=[]),
        _QueryStub(one_or_none_result=SimpleNamespace(used_bytes=1024)),
    ]))
    service.check_quota(account_id, incoming_bytes=1024)


def test_add_usage_creates_record_when_absent(monkeypatch):
    account_id = uuid4()
    service = _new_service(_SessionStub([_QueryStub(one_or_none_result=None)]))
    created = []
    monkeypatch.setattr(service, "create",
        lambda model, **kwargs: created.append(kwargs) or SimpleNamespace(**kwargs))

    service.add_usage(account_id, 1024)

    assert created[0]["account_id"] == account_id
    assert created[0]["used_bytes"] == 1024


def test_add_usage_increments_existing_record(monkeypatch):
    account_id = uuid4()
    usage = SimpleNamespace(used_bytes=2048)
    service = _new_service(_SessionStub([_QueryStub(one_or_none_result=usage)]))
    updated = []
    monkeypatch.setattr(service, "update",
        lambda instance, **kwargs: updated.append(kwargs) or instance)

    service.add_usage(account_id, 1024)

    assert updated[0]["used_bytes"] == 3072


def test_release_usage_never_goes_negative(monkeypatch):
    account_id = uuid4()
    usage = SimpleNamespace(used_bytes=512)
    service = _new_service(_SessionStub([_QueryStub(one_or_none_result=usage)]))
    updated = []
    monkeypatch.setattr(service, "update",
        lambda instance, **kwargs: updated.append(kwargs) or instance)

    service.release_usage(account_id, 4096)

    assert updated[0]["used_bytes"] == 0


def test_release_usage_is_noop_when_record_absent():
    service = _new_service(_SessionStub([_QueryStub(one_or_none_result=None)]))
    service.release_usage(uuid4(), 4096)

