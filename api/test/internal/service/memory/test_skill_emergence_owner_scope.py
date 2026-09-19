"""技能链主体化（ADMIN-P3c-3）。

不变量：
1. `_node_to_skill` 必须按属性还原主体（admin 节点不得退化为空主体）；
2. `_persist_skill` 的 MERGE 键必须含归属（防跨主体混装）；
3. `_fetch_memories` 必须带主体谓词（防跨主体取数）；
4. 种子提示键解析在 admin 键下必须取到正确的 skill 名。
"""
from uuid import uuid4

import pytest

from internal.entity.memory_owner_entity import (
    NEO4J_ADMIN_LEVEL_AGENT_SENTINEL,
    MemoryOwnerKey,
)


class _Session:
    def __init__(self, sink):
        self._sink = sink

    def run(self, cypher, params=None, **kwargs):
        self._sink.append((cypher, params if params is not None else kwargs))
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


def _emergence(driver=None, redis=None):
    from internal.service.memory.skill_emergence import SkillEmergence

    return SkillEmergence(neo4j_driver=driver, redis_client=redis)


def test_node_to_skill_admin_reads_admin_props():
    """admin 节点：必须还原为 admin 主体键（不再得到空串）。"""
    admin_id = uuid4()
    node = {
        "id": "skill_x",
        "name": "n",
        "admin_user_id": str(admin_id),
        "agent_id": NEO4J_ADMIN_LEVEL_AGENT_SENTINEL,
    }

    skill = _emergence()._node_to_skill(node)

    assert skill is not None
    assert skill.user_id == f"admin:{admin_id}"


def test_node_to_skill_admin_agent_level():
    admin_id, agent_id = uuid4(), uuid4()
    node = {
        "id": "skill_x",
        "name": "n",
        "admin_user_id": str(admin_id),
        "agent_id": str(agent_id),
    }

    skill = _emergence()._node_to_skill(node)

    assert skill is not None
    assert skill.user_id == f"admin:{admin_id}:{agent_id}"


def test_node_to_skill_user_unchanged():
    account_id = uuid4()
    node = {"id": "skill_x", "name": "n", "user_id": str(account_id)}

    skill = _emergence()._node_to_skill(node)

    assert skill is not None
    assert skill.user_id == str(account_id)


def test_node_to_skill_without_owner_returns_none():
    """无归属节点必须返回 None（不再伪装成空主体的「成功」）。"""
    assert _emergence()._node_to_skill({"id": "skill_x", "name": "n"}) is None


def test_persist_skill_merges_on_owner_key():
    """MERGE 模式必须含归属属性，否则跨主体同名技能被合并（混装）。"""
    from internal.service.memory.skill_emergence import Skill

    driver = _Driver()
    em = _emergence(driver=driver)
    admin_id = uuid4()

    em._persist_skill(Skill(skill_id="skill_x", name="n", user_id=f"admin:{admin_id}"))

    cypher, params = driver.calls[0]
    assert "MERGE (s:Skill {id: $skill_id" in cypher
    assert "admin_user_id: $admin_user_id" in cypher
    assert "agent_id: $agent_id" in cypher
    assert "s += $owner_props" in cypher
    assert params["agent_id"] == NEO4J_ADMIN_LEVEL_AGENT_SENTINEL


def test_persist_skill_user_merges_on_user_id():
    from internal.service.memory.skill_emergence import Skill

    driver = _Driver()
    em = _emergence(driver=driver)
    account_id = uuid4()

    em._persist_skill(Skill(skill_id="skill_x", name="n", user_id=str(account_id)))

    cypher, params = driver.calls[0]
    assert "user_id: $user_id" in cypher
    assert params["user_id"] == str(account_id)


def test_fetch_memories_applies_owner_predicate():
    driver = _Driver()
    em = _emergence(driver=driver)
    admin_id = uuid4()

    em._fetch_memories(["m1"], owner_key=f"admin:{admin_id}")

    cypher, params = driver.calls[0]
    assert "admin_user_id = $admin_user_id" in cypher
    assert params["admin_user_id"] == str(admin_id)


def test_fetch_memories_user_predicate_unchanged():
    driver = _Driver()
    em = _emergence(driver=driver)
    account_id = uuid4()

    em._fetch_memories(["m1"], owner_key=str(account_id))

    cypher, params = driver.calls[0]
    assert "user_id = $user_id" in cypher
    assert params["user_id"] == str(account_id)


def test_get_seed_hints_parses_admin_key_skill_name():
    """admin 键下 skill 名必须是完整名，而非 '{uuid}:{skill}'。"""
    admin_id = uuid4()

    class _Redis:
        def keys(self, pattern):
            assert pattern == f"seed:admin:{admin_id}:*"
            return [f"seed:admin:{admin_id}:写周报"]

        def get(self, key):
            return b'{"polarity": "positive", "source": "s", "created_at": "t"}'

    em = _emergence(redis=_Redis())

    hints = em._get_seed_hints(f"admin:{admin_id}")

    assert "写周报" in hints


def test_get_seed_hints_user_unchanged():
    account_id = uuid4()

    class _Redis:
        def keys(self, pattern):
            return [f"seed:{account_id}:写周报"]

        def get(self, key):
            return b'{"polarity": "positive", "source": "s", "created_at": "t"}'

    em = _emergence(redis=_Redis())

    assert "写周报" in em._get_seed_hints(str(account_id))


def test_bump_use_sets_expiry():
    """统计 hash 必须设兜底 TTL（缺口十二：防未命中残留无限累积）。"""
    calls = {}

    class _Pipe:
        def hincrby(self, *a, **k):
            return self

        def hset(self, *a, **k):
            return self

        def expire(self, key, ttl):
            calls["ttl"] = ttl
            return self

        def execute(self):
            return None

    class _Redis:
        def pipeline(self):
            return _Pipe()

    em = _emergence(redis=_Redis())

    em.bump_use(str(uuid4()), "skill_x")

    assert calls.get("ttl", 0) > 0, "bump_use 必须对 skill:stats 设 TTL"
