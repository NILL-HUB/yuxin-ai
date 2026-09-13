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


def test_default_quota_when_no_membership():
    service = _new_service(_SessionStub([_QueryStub(first_result=None), _QueryStub(all_result=[])]))
    assert service.resolve_total_quota_bytes(uuid4()) == 5 * (1024 ** 3)


def test_membership_entitlement_overrides_default():
    plan_id = uuid4()
    membership = SimpleNamespace(plan_id=plan_id)
    entitlement = SimpleNamespace(feature_value="100", value_type="number")
    service = _new_service(_SessionStub([
        _QueryStub(first_result=membership),
        _QueryStub(all_result=[entitlement]),
        _QueryStub(all_result=[]),
    ]))
    assert service.resolve_total_quota_bytes(uuid4()) == 100 * (1024 ** 3)


def test_addon_packages_are_additive():
    plan_id = uuid4()
    membership = SimpleNamespace(plan_id=plan_id)
    entitlement = SimpleNamespace(feature_value="100", value_type="number")
    addon_one = SimpleNamespace(feature_value="50", value_type="number")
    addon_two = SimpleNamespace(feature_value="200", value_type="number")
    service = _new_service(_SessionStub([
        _QueryStub(first_result=membership),
        _QueryStub(all_result=[entitlement]),
        _QueryStub(all_result=[addon_one, addon_two]),
    ]))
    assert service.resolve_total_quota_bytes(uuid4()) == 350 * (1024 ** 3)


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
