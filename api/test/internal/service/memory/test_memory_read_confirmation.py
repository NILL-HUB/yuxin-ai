"""机密记忆读取确认服务（Redis 承载的 pending + 授权白名单）单元测试。

不变量：
1. 确认记录按 ``owner_key`` 隔离：他人/过期/不存在一律 NotFound（不泄露存在性）；
2. 批准后写入授权白名单（带 TTL），重复批准幂等；
3. 拒绝不写任何授权；
4. Redis 异常不得让调用方崩（读取授权返回空集 = 按未授权处理）。
"""
import json

import pytest


class _FakeRedis:
    """内存版 Redis（只覆盖确认服务用到的命令，支持注入故障）。"""

    def __init__(self, fail=False):
        self.store: dict = {}
        self.sets: dict = {}
        self.fail = fail

    def _maybe_fail(self):
        if self.fail:
            raise ConnectionError("redis down")

    def setex(self, key, ttl, value):
        self._maybe_fail()
        self.store[key] = value

    def get(self, key):
        self._maybe_fail()
        return self.store.get(key)

    def sadd(self, key, *members):
        self._maybe_fail()
        self.sets.setdefault(key, set()).update(members)

    def smembers(self, key):
        self._maybe_fail()
        return self.sets.get(key, set())

    def expire(self, key, ttl):
        self._maybe_fail()
        return True

    def delete(self, key):
        self._maybe_fail()
        self.store.pop(key, None)
        self.sets.pop(key, None)


def _service(fake=None):
    from internal.service.memory.read_confirmation_service import (
        MemoryReadConfirmationService,
    )

    return MemoryReadConfirmationService(redis_client=fake or _FakeRedis())


def _items():
    return [
        {"memory_id": "m1", "types": ["phone"], "label": "手机号", "preview": "[PHONE_REDACTED]"},
        {"memory_id": "m2", "types": ["id_card"], "label": "身份证号", "preview": "[ID_REDACTED]"},
    ]


class TestCreateAndGet:
    def test_create_then_get_returns_pending_items(self):
        service = _service()
        confirmation_id = service.create(owner_key="u-1", items=_items())

        record = service.get(confirmation_id, owner_key="u-1")
        assert record["status"] == "pending"
        assert [item["memory_id"] for item in record["items"]] == ["m1", "m2"]

    def test_get_rejects_other_owner(self):
        from internal.exception import NotFoundException

        service = _service()
        confirmation_id = service.create(owner_key="u-1", items=_items())

        with pytest.raises(NotFoundException):
            service.get(confirmation_id, owner_key="u-2")

    def test_get_unknown_id_raises_not_found(self):
        from internal.exception import NotFoundException

        service = _service()
        with pytest.raises(NotFoundException):
            service.get("does-not-exist", owner_key="u-1")

    def test_create_writes_json_record_with_ttl(self):
        fake = _FakeRedis()
        service = _service(fake)
        confirmation_id = service.create(owner_key="u-1", items=_items())

        raw = fake.store[f"memory:read-confirm:{confirmation_id}"]
        record = json.loads(raw)
        assert record["owner_key"] == "u-1"
        assert record["status"] == "pending"


class TestConfirmAndCancel:
    def test_confirm_grants_ids_and_marks_confirmed(self):
        fake = _FakeRedis()
        service = _service(fake)
        confirmation_id = service.create(owner_key="u-1", items=_items())

        granted = service.confirm(confirmation_id, owner_key="u-1")

        assert granted == ["m1", "m2"]
        assert service.get(confirmation_id, owner_key="u-1")["status"] == "confirmed"
        assert service.authorized_ids("u-1") == frozenset({"m1", "m2"})

    def test_confirm_is_idempotent(self):
        service = _service()
        confirmation_id = service.create(owner_key="u-1", items=_items())

        first = service.confirm(confirmation_id, owner_key="u-1")
        second = service.confirm(confirmation_id, owner_key="u-1")

        assert first == second == ["m1", "m2"]

    def test_confirm_rejects_other_owner(self):
        from internal.exception import NotFoundException

        service = _service()
        confirmation_id = service.create(owner_key="u-1", items=_items())

        with pytest.raises(NotFoundException):
            service.confirm(confirmation_id, owner_key="u-2")
        assert service.authorized_ids("u-2") == frozenset()

    def test_cancel_grants_nothing(self):
        service = _service()
        confirmation_id = service.create(owner_key="u-1", items=_items())

        assert service.cancel(confirmation_id, owner_key="u-1") == "cancelled"
        assert service.get(confirmation_id, owner_key="u-1")["status"] == "cancelled"
        assert service.authorized_ids("u-1") == frozenset()

    def test_authorized_ids_scoped_per_owner(self):
        service = _service()
        confirmation_id = service.create(owner_key="u-1", items=_items())
        service.confirm(confirmation_id, owner_key="u-1")

        assert service.authorized_ids("u-1") == frozenset({"m1", "m2"})
        assert service.authorized_ids("u-2") == frozenset()


class TestFailOpen:
    def test_authorized_ids_returns_empty_on_redis_error(self):
        service = _service(_FakeRedis(fail=True))
        assert service.authorized_ids("u-1") == frozenset()

    def test_confirm_raises_not_found_on_redis_error(self):
        """Redis 不可用时确认记录读不到 → NotFound（上层映射 404，不 500）。"""
        from internal.exception import NotFoundException

        service = _service(_FakeRedis(fail=True))
        with pytest.raises(NotFoundException):
            service.confirm("any-id", owner_key="u-1")
