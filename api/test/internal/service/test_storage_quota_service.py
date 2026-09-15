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


def test_max_file_size_falls_back_to_default_when_no_entitlement():
    service = _new_service(_SessionStub([_QueryStub(first_result=None), _QueryStub(all_result=[])]))
    assert service.resolve_max_file_size_bytes(uuid4()) == 15 * 1024 * 1024


def test_max_file_size_uses_plan_entitlement():
    plan_id = uuid4()
    membership = SimpleNamespace(plan_id=plan_id)
    entitlement = _fake_entitlement(1024)
    service = _new_service(_SessionStub([
        _QueryStub(first_result=membership),
        _QueryStub(all_result=[entitlement]),
    ]))
    assert service.resolve_max_file_size_bytes(uuid4()) == 1024 * (1024 ** 3)


def test_max_file_size_falls_back_to_default_when_entitlement_is_zero():
    """权益显式配 0 视为未配置，回退默认上限。"""
    plan_id = uuid4()
    membership = SimpleNamespace(plan_id=plan_id)
    entitlement = _fake_entitlement(0)
    service = _new_service(_SessionStub([
        _QueryStub(first_result=membership),
        _QueryStub(all_result=[entitlement]),
    ]))
    assert service.resolve_max_file_size_bytes(uuid4()) == 15 * 1024 * 1024


def test_consume_quota_increments_within_single_locked_transaction(monkeypatch):
    """原子预占：在同一把行锁内完成校验与累加，返回累加后用量。"""
    account_id = uuid4()
    usage = SimpleNamespace(used_bytes=1024)
    service = _new_service(_SessionStub([
        _QueryStub(first_result=None),
        _QueryStub(all_result=[]),
        _QueryStub(one_or_none_result=usage),
    ]))
    updated = []
    monkeypatch.setattr(service, "update",
        lambda instance, **kwargs: updated.append(kwargs) or instance)

    result = service.consume_quota(account_id, 2048)

    assert result == 3072
    assert updated[0]["used_bytes"] == 3072


def test_consume_quota_raises_and_leaves_usage_untouched_when_over_quota(monkeypatch):
    """超配额时必须抛错，且不得写入任何用量（避免超卖）。"""
    account_id = uuid4()
    usage = SimpleNamespace(used_bytes=5 * (1024 ** 3))
    service = _new_service(_SessionStub([
        _QueryStub(first_result=None),
        _QueryStub(all_result=[]),
        _QueryStub(one_or_none_result=usage),
    ]))
    updated = []
    monkeypatch.setattr(service, "update",
        lambda instance, **kwargs: updated.append(kwargs) or instance)

    with pytest.raises(ForbiddenException):
        service.consume_quota(account_id, 1024)

    assert updated == []
    assert usage.used_bytes == 5 * (1024 ** 3)


def test_consume_quota_is_noop_for_non_positive_bytes(monkeypatch):
    account_id = uuid4()
    usage = SimpleNamespace(used_bytes=1024)
    service = _new_service(_SessionStub([_QueryStub(one_or_none_result=usage)]))
    updated = []
    monkeypatch.setattr(service, "update",
        lambda instance, **kwargs: updated.append(kwargs) or instance)

    result = service.consume_quota(account_id, 0)

    assert result == 1024
    assert updated == []


def test_consume_quota_creates_record_when_absent(monkeypatch):
    """无用量记录时新建，且新记录的用量即为本次预占字节数。"""
    account_id = uuid4()
    service = _new_service(_SessionStub([
        _QueryStub(first_result=None),
        _QueryStub(all_result=[]),
        _QueryStub(one_or_none_result=None),
    ]))
    created = []
    monkeypatch.setattr(service, "create",
        lambda model, **kwargs: created.append(kwargs) or SimpleNamespace(**kwargs))

    result = service.consume_quota(account_id, 2048)

    assert result == 2048
    assert created[0]["used_bytes"] == 2048


class TestConsumeQuotaWithReserve:
    """上传准入需把「解析预留」纳入校验，但预留本身不计入已用。

    若不纳入：用户剩 2G、传 2G 视频会通过校验，随后帧留存把用量顶穿配额。
    若把预留也计入已用：用户被白扣一笔从未占用的空间。
    """

    def _service_with_usage(self, monkeypatch, used_bytes):
        account_id = uuid4()
        usage = SimpleNamespace(used_bytes=used_bytes)
        service = _new_service(_SessionStub([_QueryStub(one_or_none_result=usage)]))
        updated = []
        monkeypatch.setattr(
            service, "update",
            lambda instance, **kwargs: updated.append(kwargs) or instance,
        )
        return service, usage, updated

    def test_reserve_blocks_upload_when_total_insufficient(self, monkeypatch):
        """used=0，配额 2048；传 1024 本可通过，加预留 2048 后超额 -> 拒绝。"""
        service, usage, updated = self._service_with_usage(monkeypatch, used_bytes=0)
        monkeypatch.setattr(service, "resolve_total_quota_bytes", lambda account_id: 2048)

        with pytest.raises(ForbiddenException):
            service.consume_quota(uuid4(), 1024, reserve_bytes=2048)

        assert updated == []
        assert usage.used_bytes == 0

    def test_reserve_not_counted_into_used_bytes(self, monkeypatch):
        """累加值只含 incoming_bytes，不含 reserve。"""
        service, usage, updated = self._service_with_usage(monkeypatch, used_bytes=0)
        monkeypatch.setattr(service, "resolve_total_quota_bytes", lambda account_id: 10_000)

        result = service.consume_quota(uuid4(), 1_000, reserve_bytes=5_000)

        assert result == 1_000
        assert updated == [{"used_bytes": 1_000}]

    def test_without_reserve_behaves_as_before(self, monkeypatch):
        service, usage, updated = self._service_with_usage(monkeypatch, used_bytes=0)
        monkeypatch.setattr(service, "resolve_total_quota_bytes", lambda account_id: 1_000)

        assert service.consume_quota(uuid4(), 1_000) == 1_000
        assert updated == [{"used_bytes": 1_000}]

    def test_reserve_gate_applies_when_usage_record_absent(self, monkeypatch):
        """无用量记录时预留同样参与门槛，避免新账号传满后再被帧顶穿。"""
        service = _new_service(_SessionStub([_QueryStub(one_or_none_result=None)]))
        monkeypatch.setattr(service, "resolve_total_quota_bytes", lambda account_id: 2048)
        created = []
        monkeypatch.setattr(service, "create",
            lambda model, **kwargs: created.append(kwargs) or SimpleNamespace(**kwargs))

        with pytest.raises(ForbiddenException):
            service.consume_quota(uuid4(), 1024, reserve_bytes=2048)

        assert created == []

