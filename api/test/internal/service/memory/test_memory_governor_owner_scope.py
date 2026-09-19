"""治理层主体化（ADMIN-P3c-2）。

不变量：
1. `_verify_owner` 必须按主体属性判定（admin 不得恒 False）；
2. `_delete_all_pgvector_rows` 必须带 owner_type 谓词（否则 admin 行漏删）。
"""
from uuid import uuid4

import pytest

from internal.entity.memory_owner_entity import MemoryOwnerKey
from internal.service.memory.memory_governor import MemoryGovernor


class _Session:
    def __init__(self, sink):
        self._sink = sink

    def run(self, cypher, params=None, **kwargs):
        self._sink.append((cypher, params or kwargs))
        return self

    def single(self):
        return None

    def consume(self):
        return self

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class _Driver:
    def __init__(self):
        self.calls = []

    def session(self):
        return _Session(self.calls)


def test_verify_owner_admin_uses_admin_props():
    """admin 主体：校验谓词必须含 admin_user_id，而非只读 user_id。"""
    driver = _Driver()
    gov = MemoryGovernor(neo4j_driver=driver)
    admin_id = uuid4()

    gov._verify_owner("m-1", MemoryOwnerKey.for_admin(admin_id).to_key(), driver)

    cypher, params = driver.calls[0]
    assert "admin_user_id" in cypher
    assert params.get("admin_user_id") == str(admin_id)
    assert "user_id" not in params


def test_verify_owner_user_unchanged():
    driver = _Driver()
    gov = MemoryGovernor(neo4j_driver=driver)
    account_id = uuid4()

    gov._verify_owner("m-1", MemoryOwnerKey.for_user(account_id).to_key(), driver)

    cypher, params = driver.calls[0]
    assert params.get("user_id") == str(account_id)


def test_verify_owner_admin_agent_level_uses_sentinel():
    """管理员级（无 agent）：绑定值必须是哨兵（与写入侧同源）。"""
    from internal.entity.memory_owner_entity import NEO4J_ADMIN_LEVEL_AGENT_SENTINEL

    driver = _Driver()
    gov = MemoryGovernor(neo4j_driver=driver)

    gov._verify_owner("m-1", MemoryOwnerKey.for_admin(uuid4()).to_key(), driver)

    _cypher, params = driver.calls[0]
    assert params.get("agent_id") == NEO4J_ADMIN_LEVEL_AGENT_SENTINEL


def test_verify_owner_invalid_key_returns_false():
    """非法主体键必须 fail-closed（不查库、返回 False）。"""
    driver = _Driver()
    gov = MemoryGovernor(neo4j_driver=driver)

    assert gov._verify_owner("m-1", "not-a-valid-key", driver) is False
    assert driver.calls == []


def test_delete_all_pgvector_rows_filters_owner_type():
    """删除必须带 owner_type 谓词（admin 行 owner_account_id 为 NULL）。"""
    captured = {}

    class _Q:
        def filter(self, *conds):
            captured["conds"] = [str(c) for c in conds]
            return self

        def delete(self):
            return 3

    class _S:
        def query(self, *a, **k):
            return _Q()

        def commit(self):
            captured["committed"] = True

    gov = MemoryGovernor(db=type("D", (), {"session": _S()})())

    count = gov._delete_all_pgvector_rows(
        MemoryOwnerKey.for_admin(uuid4()).to_key()
    )

    assert count == 3
    rendered = " ".join(captured["conds"])
    assert "owner_type" in rendered
    assert "owner_admin_user_id" in rendered


def test_delete_all_pgvector_rows_user_keeps_account_predicate():
    captured = {}

    class _Q:
        def filter(self, *conds):
            captured["conds"] = [str(c) for c in conds]
            return self

        def delete(self):
            return 1

    class _S:
        def query(self, *a, **k):
            return _Q()

        def commit(self):
            pass

    gov = MemoryGovernor(db=type("D", (), {"session": _S()})())
    account_id = uuid4()

    gov._delete_all_pgvector_rows(MemoryOwnerKey.for_user(account_id).to_key())

    rendered = " ".join(captured["conds"])
    assert "owner_type" in rendered
    assert "owner_account_id" in rendered
