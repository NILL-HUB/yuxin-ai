"""admin 主体巩固派发（ADMIN-P3c-3）。

不变量：
1. 主体键构造必须兼容裸 UUID（用户）与 admin 键——不得对 admin 抛错；
2. admin 归属节点扫描必须产出规范主体键（管理员级无 agent 段）；
3. 扫描 Cypher 必须按 admin_user_id 过滤（不得退回扫全部节点）。
"""
from uuid import uuid4

import pytest

from internal.entity.memory_owner_entity import (
    NEO4J_ADMIN_LEVEL_AGENT_SENTINEL,
    MemoryOwnerKey,
)


def test_subject_key_accepts_user_and_admin():
    """任务内主体键构造：裸 UUID 与 admin 键都必须可用。"""
    from internal.task.consolidation_tasks import _subject_key_of

    account_id, admin_id, agent_id = uuid4(), uuid4(), uuid4()
    assert _subject_key_of(str(account_id)) == str(account_id)
    assert _subject_key_of(f"admin:{admin_id}") == f"admin:{admin_id}"
    assert _subject_key_of(f"admin:{admin_id}:{agent_id}") == f"admin:{admin_id}:{agent_id}"


def test_subject_key_rejects_garbage():
    """非法主体键 fail-closed（不猜主体）。"""
    from internal.entity.memory_owner_entity import MemoryOwnerKeyError
    from internal.task.consolidation_tasks import _subject_key_of

    with pytest.raises(MemoryOwnerKeyError):
        _subject_key_of("not-a-uuid")


def test_admin_subject_rows_build_canonical_keys():
    """扫描结果（admin_id, agent_id）→ 规范主体键。"""
    from internal.task.consolidation_tasks import _admin_key_from_row

    admin_id, agent_id = uuid4(), uuid4()
    assert _admin_key_from_row(str(admin_id), None) == f"admin:{admin_id}"
    assert (
        _admin_key_from_row(str(admin_id), NEO4J_ADMIN_LEVEL_AGENT_SENTINEL)
        == f"admin:{admin_id}"
    )
    assert _admin_key_from_row(str(admin_id), str(agent_id)) == (
        f"admin:{admin_id}:{agent_id}"
    )


def test_query_active_admin_subjects_scopes_by_admin_property(monkeypatch):
    """扫描 Cypher 必须按 admin_user_id 过滤（不得退回扫全部节点）。"""
    from internal.task import consolidation_tasks as ct

    captured = {}

    class _Result(list):
        pass

    class _S:
        def run(self, cypher, *a, **k):
            captured["cypher"] = cypher
            return _Result()

        def __enter__(self):
            return self

        def __exit__(self, *e):
            return False

    class _D:
        def session(self):
            return _S()

    monkeypatch.setattr(ct, "_get_neo4j_driver", lambda: _D())

    ct._query_active_admin_subjects()

    assert "admin_user_id IS NOT NULL" in captured["cypher"]
    assert "DISTINCT" in captured["cypher"].upper()


def test_query_active_admin_subjects_builds_keys(monkeypatch):
    """扫描结果行 → 规范主体键（管理员级与 Agent 级并存）。"""
    from internal.task import consolidation_tasks as ct

    admin_a, admin_b, agent_b = uuid4(), uuid4(), uuid4()

    class _S:
        def run(self, cypher, *a, **k):
            return [
                {"admin_user_id": str(admin_a), "agent_id": None},
                {"admin_user_id": str(admin_b), "agent_id": str(agent_b)},
            ]

        def __enter__(self):
            return self

        def __exit__(self, *e):
            return False

    class _D:
        def session(self):
            return _S()

    monkeypatch.setattr(ct, "_get_neo4j_driver", lambda: _D())

    keys = ct._query_active_admin_subjects()

    assert f"admin:{admin_a}" in keys
    assert f"admin:{admin_b}:{agent_b}" in keys


def test_query_active_subjects_merges_users_and_admins(monkeypatch):
    """派发全集 = 活跃用户主体 + admin 主体。"""
    from internal.task import consolidation_tasks as ct

    monkeypatch.setattr(ct, "_query_active_users", lambda: ["u1"])
    monkeypatch.setattr(ct, "_query_active_admin_subjects", lambda: ["admin:a1"])

    assert ct._query_active_subjects() == ["u1", "admin:a1"]


def test_query_active_admin_subjects_degrades_without_driver(monkeypatch):
    from internal.task import consolidation_tasks as ct

    monkeypatch.setattr(ct, "_get_neo4j_driver", lambda: None)

    assert ct._query_active_admin_subjects() == []
