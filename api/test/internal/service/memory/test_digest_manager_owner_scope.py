"""Digest 缓存键与查询的主体化守卫。

不变量（P3b Task 4）：
1. **用户主体零变化**：缓存键必须是 `memory:digest:{裸uuid}`——与历史实际写入键
   逐字节一致（否则全部用户冷启动重建）。
2. **7 个 Cypher 点按主体下推归属谓词**：用户态用 `{alias}.user_id = $user_id`，
   admin 态用 `{alias}.admin_user_id = $admin_user_id` [+ agent 维度]，
   且**不得丢失任何既有 WHERE / ORDER BY / LIMIT / RETURN 子句**。
"""
import textwrap
from uuid import uuid4

import pytest

from internal.entity.memory_owner_entity import MemoryOwnerKey
from internal.service.memory.digest_manager import DigestManager


class _StubResult:
    def __iter__(self):
        return iter([])

    def single(self):
        return None


class _CapturedSession:
    def __init__(self, sink):
        self._sink = sink

    def run(self, cypher, params=None, **kwargs):
        self._sink.append((cypher, params if params is not None else kwargs))
        return _StubResult()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class _CapturedDriver:
    """替身 Neo4j 驱动：记录每次下推的 Cypher 与绑定参数，返回空结果。"""

    def __init__(self):
        self.calls = []

    def session(self):
        return _CapturedSession(self.calls)


def _norm(text: str) -> str:
    return textwrap.dedent(text).strip()


def test_cache_key_matches_legacy_format_for_user():
    account_id = uuid4()
    owner_key = MemoryOwnerKey.for_user(account_id).to_key()
    manager = DigestManager(redis_client=None)

    assert manager._cache_key(owner_key) == f"memory:digest:{account_id}"


# 用户态期望 Cypher：MATCH 行去掉内联属性，归属谓词下推到 WHERE 首位。
USER_CASES = [
    (
        "_fetch_explicit_memories",
        """\
        MATCH (e:Episode)
        WHERE e.user_id = $user_id
          AND e.explicit_category IS NOT NULL
          AND e.t_invalidated_at IS NULL
          AND (e.status IS NULL OR NOT (e.status IN ['superseded', 'deprecated']))
        RETURN e.explicit_category AS category,
               e.explicit_polarity AS polarity,
               e.content AS content,
               e.summary AS summary
        ORDER BY e.created_at DESC
        LIMIT $limit
        """,
    ),
    (
        "_fetch_entity_profile",
        """\
        MATCH (e:Entity)
        WHERE e.user_id = $user_id
          AND e.type IN ['person', 'profile', 'user']
        RETURN e.name AS name, e.summary AS summary
        LIMIT $limit
        """,
    ),
    (
        "_fetch_skills",
        """\
        MATCH (s:Skill)
        WHERE s.user_id = $user_id
          AND s.status = 'active'
        RETURN s.name AS name, s.description AS description,
               s.use_count AS use_count
        ORDER BY s.maturity DESC, s.use_count DESC
        LIMIT $limit
        """,
    ),
    (
        "_fetch_recent_episodes",
        """\
        MATCH (e:Episode)
        WHERE e.user_id = $user_id
          AND (e.storage_tier IS NULL OR e.storage_tier IN ['hot', 'warm'])
        RETURN e.summary AS summary, e.content AS content, e.created_at AS created_at
        ORDER BY e.created_at DESC
        LIMIT $limit
        """,
    ),
    (
        "_fetch_tasks",
        """\
        MATCH (e:Entity)
        WHERE e.user_id = $user_id
          AND e.type IN ['task', 'todo']
        RETURN e.name AS name, e.summary AS summary
        LIMIT $limit
        """,
    ),
    (
        "_fetch_themes",
        """\
        MATCH (c:Community)
        WHERE c.user_id = $user_id
          AND c.is_active <> false
          AND (c.status IS NULL OR c.status IN ['candidate', 'active'])
        RETURN c.title AS title, c.summary AS summary
        ORDER BY coalesce(c.maturity, 0.0) DESC, c.updated_at DESC
        LIMIT $limit
        """,
    ),
]


def _capture(monkeypatch, owner_key, method_name):
    manager = DigestManager(redis_client=None)
    driver = _CapturedDriver()
    monkeypatch.setattr(DigestManager, "_get_driver", lambda self: driver)
    getattr(manager, method_name)(owner_key)
    assert len(driver.calls) == 1, f"{method_name} 应恰好下推一次 Cypher"
    return driver.calls[0]


@pytest.mark.parametrize("method_name,expected", USER_CASES)
def test_user_owner_cypher_keeps_full_clause_set(monkeypatch, method_name, expected):
    """用户态：归属谓词改为 WHERE 下推，其余子句一个不丢。"""
    account_id = uuid4()
    owner_key = MemoryOwnerKey.for_user(account_id).to_key()

    cypher, params = _capture(monkeypatch, owner_key, method_name)

    assert _norm(cypher) == _norm(expected)
    assert params["user_id"] == str(account_id)
    assert "admin_user_id" not in cypher


@pytest.mark.parametrize("method_name,expected", USER_CASES)
def test_admin_owner_cypher_scopes_by_admin_props(monkeypatch, method_name, expected):
    """admin 态：用 admin 属性下推，且用户属性完全不出现。"""
    admin_id = uuid4()
    owner_key = MemoryOwnerKey.for_admin(admin_id).to_key()

    cypher, params = _capture(monkeypatch, owner_key, method_name)

    assert "admin_user_id = $admin_user_id" in cypher
    assert ".user_id = $user_id" not in cypher
    assert "agent_id IS NULL" in cypher
    assert params["admin_user_id"] == str(admin_id)
    assert "user_id" not in params


def test_get_skill_detail_scopes_both_tiers(monkeypatch):
    """get_skill_detail 两处 Cypher（Tier1/Tier2）都必须主体化。"""
    account_id = uuid4()
    owner_key = MemoryOwnerKey.for_user(account_id).to_key()
    manager = DigestManager(redis_client=None)
    driver = _CapturedDriver()
    monkeypatch.setattr(DigestManager, "_get_driver", lambda self: driver)

    manager.get_skill_detail(owner_key, "代码审查", tier=1)
    manager.get_skill_detail(owner_key, "代码审查", tier=2)

    assert len(driver.calls) == 2
    for cypher, params in driver.calls:
        assert "MATCH (s:Skill)" in cypher
        assert "s.user_id = $user_id" in cypher
        assert params["user_id"] == str(account_id)
        assert params["skill_name"] == "代码审查"

    tier1_cypher = _norm(driver.calls[0][0])
    tier2_cypher = _norm(driver.calls[1][0])
    assert "s.maturity AS maturity\nLIMIT 1" in tier1_cypher
    assert "s.source_memories AS source_memories" in tier2_cypher
    assert "s.status IN ['active', 'emerging']" in tier1_cypher
    assert "s.status IN ['active', 'emerging']" in tier2_cypher
