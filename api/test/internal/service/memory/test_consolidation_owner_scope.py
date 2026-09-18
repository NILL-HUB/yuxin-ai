"""巩固链主体过滤守卫。

不变量（P3b Task 5）：
1. pgvector 相似度查询必须按主体过滤（owner_type + 归属列），而不是只按 owner_account_id——
   后者在引入 admin 主体后会跨主体合并记忆；
2. 用户主体下 Neo4j 归属谓词与改造前逐字节等价（故存量不变）；
3. admin 主体下归属属性必须随之切换（`admin_user_id` [+ `agent_id`]），
   且 Community 的 `MERGE` 模式必须保留归属属性——只按 `key` MERGE 会让不同主体的
   同名主题合并到同一节点（跨主体污染）。

> 判别性说明：断言 2（用户态）在改造前因「硬编码 `user_id: $user_id`」而**碰巧成立**，
> 故本文件的**红→绿**由断言 3（admin 态）驱动：改造前 admin 键会产出用户态形态，
> 改造后必须产出 admin 归属。
"""
from uuid import uuid4

import pytest

from internal.entity.memory_owner_entity import MemoryOwnerKey


def test_pgvector_similarity_query_uses_owner_conditions():
    from internal.model import UserMemory

    owner = MemoryOwnerKey.for_user(uuid4())
    conds = owner.pg_filter_conditions(UserMemory)
    rendered = " ".join(str(c) for c in conds)

    assert "owner_type" in rendered
    assert "owner_account_id" in rendered
    assert len(conds) == 2


class _CapturedSession:
    def __init__(self, sink):
        self._sink = sink

    def run(self, cypher, params=None, **kwargs):
        self._sink.append((cypher, params if params is not None else kwargs))
        return self

    def consume(self):
        return self

    def single(self):
        return None

    def __iter__(self):
        return iter([])

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class _CapturedDriver:
    def __init__(self):
        self.calls = []

    def session(self):
        return _CapturedSession(self.calls)


def _engine_with_driver(cls, driver):
    engine = cls.__new__(cls)
    engine._get_driver = lambda: driver
    return engine


def test_community_merge_keeps_owner_prop_in_pattern():
    """⚠️ 关键：Community 的 MERGE 必须把归属属性保留在模式内——
    若退化成只按 key MERGE，不同用户的同名主题会被合并到同一节点（跨主体污染）。
    """
    from internal.service.memory.community_induction import CommunityInductionEngine

    account_id = uuid4()
    owner_key = MemoryOwnerKey.for_user(account_id).to_key()
    driver = _CapturedDriver()
    engine = _engine_with_driver(CommunityInductionEngine, driver)
    engine._persist_community(
        owner_key,
        {"key": "k1", "title": "t", "summary": "s", "theme_keywords": []},
        [{"members": 1}],
    )

    assert driver.calls, "应至少下推一次 Cypher"
    cypher, params = driver.calls[0]
    assert "user_id: $user_id" in cypher, "MERGE 模式必须保留归属属性（用户态）"
    assert params.get("user_id") == str(account_id)


def test_community_merge_scopes_admin_owner_in_pattern():
    """admin 主体：MERGE 模式必须换成 admin 归属属性（判别性用例）。"""
    from internal.service.memory.community_induction import CommunityInductionEngine

    admin_id = uuid4()
    owner_key = MemoryOwnerKey.for_admin(admin_id).to_key()
    driver = _CapturedDriver()
    engine = _engine_with_driver(CommunityInductionEngine, driver)
    engine._persist_community(
        owner_key,
        {"key": "k1", "title": "t", "summary": "s", "theme_keywords": []},
        [{"members": 1}],
    )

    cypher, params = driver.calls[0]
    assert "admin_user_id: $admin_user_id" in cypher
    assert "user_id: $user_id" not in cypher
    assert params.get("admin_user_id") == str(admin_id)
    assert "user_id" not in params


def test_query_old_episodes_scopes_admin_owner_keeping_clauses():
    """Episode 查询：admin 态归属谓词下推 WHERE，且既有子句一个不丢。"""
    from internal.service.memory.consolidation_engine import ConsolidationEngine

    admin_id = uuid4()
    owner_key = MemoryOwnerKey.for_admin(admin_id).to_key()
    driver = _CapturedDriver()
    engine = _engine_with_driver(ConsolidationEngine, driver)
    engine._query_old_episodes(driver, owner_key, 7)

    cypher, params = driver.calls[0]
    assert "MATCH (e:Episode)" in cypher
    assert "e.admin_user_id = $admin_user_id AND e.agent_id IS NULL" in cypher
    assert "e.user_id = $user_id" not in cypher
    for clause in ("LIMIT 100", "RETURN", "e.processed IS NULL"):
        assert clause in cypher, f"既有子句 {clause} 不得丢失"
    assert params["admin_user_id"] == str(admin_id)


def test_query_old_episodes_user_owner_keeps_full_clause_set():
    from internal.service.memory.consolidation_engine import ConsolidationEngine

    account_id = uuid4()
    owner_key = MemoryOwnerKey.for_user(account_id).to_key()
    driver = _CapturedDriver()
    engine = _engine_with_driver(ConsolidationEngine, driver)
    engine._query_old_episodes(driver, owner_key, 7)

    cypher, params = driver.calls[0]
    assert "e.user_id = $user_id" in cypher
    assert "LIMIT 100" in cypher
    assert params["user_id"] == str(account_id)


def test_conflict_pairs_dual_alias_scopes_admin_owner():
    """双别名（a/b）都必须主体化（判别性用例）。"""
    from internal.service.memory.conflict_detector import ConflictDetector

    admin_id = uuid4()
    owner_key = MemoryOwnerKey.for_admin(admin_id).to_key()
    driver = _CapturedDriver()
    detector = ConflictDetector.__new__(ConflictDetector)
    detector._query_conflict_pairs(driver, owner_key, 50)

    cypher, params = driver.calls[0]
    assert "a.admin_user_id = $admin_user_id AND a.agent_id IS NULL" in cypher
    assert "b.admin_user_id = $admin_user_id AND b.agent_id IS NULL" in cypher
    assert "a.user_id = $user_id" not in cypher
    assert "b.user_id = $user_id" not in cypher
    assert params["admin_user_id"] == str(admin_id)
    assert params["batch_size"] == 50


def test_persist_skill_sets_owner_props_for_admin():
    """Skill 归属属性写入必须按主体切换（判别性用例）。"""
    from internal.service.memory.skill_emergence import Skill, SkillEmergence

    admin_id = uuid4()
    owner_key = MemoryOwnerKey.for_admin(admin_id).to_key()
    driver = _CapturedDriver()
    emergence = SkillEmergence.__new__(SkillEmergence)
    emergence._neo4j_driver = driver
    emergence._redis = None

    emergence._persist_skill(
        Skill(skill_id="skill_1", name="n", user_id=owner_key)
    )

    cypher, params = driver.calls[0]
    assert "s += $owner_props" in cypher
    assert "s.user_id = $user_id" not in cypher
    assert params["owner_props"] == {"admin_user_id": str(admin_id)}


def test_persist_skill_user_writes_user_id_prop():
    from internal.service.memory.skill_emergence import Skill, SkillEmergence

    account_id = uuid4()
    owner_key = MemoryOwnerKey.for_user(account_id).to_key()
    driver = _CapturedDriver()
    emergence = SkillEmergence.__new__(SkillEmergence)
    emergence._neo4j_driver = driver
    emergence._redis = None

    emergence._persist_skill(
        Skill(skill_id="skill_1", name="n", user_id=owner_key)
    )

    cypher, params = driver.calls[0]
    assert params["owner_props"] == {"user_id": str(account_id)}


def test_user_owner_predicate_is_byte_identical():
    """用户态归属谓词与历史硬编码逐字节等价（零变化根基）。"""
    account_id = uuid4()
    owner = MemoryOwnerKey.for_user(account_id)

    assert owner.neo4j_filter_condition("e") == "e.user_id = $user_id"
    assert owner.neo4j_props() == {"user_id": str(account_id)}


# =========================================================
# CREATE 分支的归属写入（属性分离的另一半——新增节点必须按主体落归属属性）
# =========================================================


def test_create_semantic_memory_sets_owner_props():
    """`_create_semantic_memory` 建节点必须写主体归属属性（用户态写 user_id）。"""
    from internal.service.memory.consolidation_engine import ConsolidationEngine

    account_id = uuid4()
    owner_key = MemoryOwnerKey.for_user(account_id).to_key()
    driver = _CapturedDriver()
    engine = _engine_with_driver(ConsolidationEngine, driver)

    engine._create_semantic_memory(driver, owner_key, "摘要内容", [])

    cypher, params = driver.calls[0]
    assert "CREATE (s:SemanticMemory:MemoryNode" in cypher
    assert "SET s += $owner_props" in cypher
    assert params["owner_props"] == {"user_id": str(account_id)}


def test_create_evolved_community_sets_owner_props_for_admin():
    """演化出的新 Community 必须按主体落归属属性（判别性用例）。"""
    from internal.service.memory.community_induction import CommunityInductionEngine

    admin_id, agent_id = uuid4(), uuid4()
    owner_key = MemoryOwnerKey.for_admin(admin_id, agent_id=agent_id).to_key()
    driver = _CapturedDriver()
    engine = _engine_with_driver(CommunityInductionEngine, driver)

    engine._create_evolved_community(
        owner_key, "old-node", {"key": "k1", "title": "t", "summary": "s"}, []
    )

    cypher, params = driver.calls[0]
    assert "CREATE (new:Community" in cypher
    assert params["owner_props"] == {
        "admin_user_id": str(admin_id),
        "agent_id": str(agent_id),
    }
    assert "user_id" not in params["owner_props"]


def test_register_seed_hint_uses_owner_key_redis_key():
    """种子提示的 Redis 键必须以 owner_key 作主体片段（用户态 == 裸 uuid）。"""
    from internal.service.memory.skill_emergence import SkillEmergence

    account_id = uuid4()
    owner_key = MemoryOwnerKey.for_user(account_id).to_key()

    class _RecordingRedis:
        def __init__(self):
            self.setex_calls = []

        def setex(self, key, ttl, value):
            self.setex_calls.append((key, value))

    redis = _RecordingRedis()
    emergence = SkillEmergence.__new__(SkillEmergence)
    emergence._neo4j_driver = None
    emergence._redis = redis

    emergence.register_seed_hint(
        owner_key=owner_key, skill_name="代码审查", polarity="positive", source="explicit_statement"
    )

    assert redis.setex_calls, "应写入种子提示键"
    key, _value = redis.setex_calls[0]
    assert key.startswith(f"seed:{account_id}:"), f"键主体片段必须是 owner_key，实际 {key}"


# =========================================================
# PG 向量分支：过滤条件必须按主体产出（`owner_type` + 归属列）
# =========================================================


class _FilterCapturingQuery:
    def __init__(self, sink):
        self._sink = sink

    def filter(self, *conds):
        self._sink.extend(conds)
        return self

    def order_by(self, *args, **kwargs):
        return self

    def limit(self, *args, **kwargs):
        return self

    def first(self):
        return None

    def all(self):
        return []


class _FilterCapturingSession:
    def __init__(self):
        self.filters = []

    def query(self, *entities, **kwargs):
        return _FilterCapturingQuery(self.filters)


class _FakeDB:
    def __init__(self):
        self.session = _FilterCapturingSession()


def _pgvector_engine():
    from internal.service.memory.consolidation_engine import ConsolidationEngine

    engine = ConsolidationEngine.__new__(ConsolidationEngine)
    db = _FakeDB()
    engine._get_db = lambda: db
    return engine, db


def test_pgvector_similarity_source_query_scopes_by_owner_type():
    engine, db = _pgvector_engine()
    owner_key = MemoryOwnerKey.for_user(uuid4()).to_key()

    engine._find_similar_nodes_pgvector(owner_key, "n1", 0.9)

    rendered = " ".join(str(c) for c in db.session.filters)
    assert "owner_type" in rendered, "PG 分支必须约束 owner_type"
    assert "owner_account_id" in rendered


def test_pgvector_similarity_source_query_scopes_admin_owner():
    engine, db = _pgvector_engine()
    admin_id = uuid4()
    owner_key = MemoryOwnerKey.for_admin(admin_id).to_key()

    engine._find_similar_nodes_pgvector(owner_key, "n1", 0.9)

    rendered = " ".join(str(c) for c in db.session.filters)
    assert "owner_admin_user_id" in rendered
    assert "owner_agent_id IS NULL" in rendered
    assert "owner_account_id" not in rendered


def test_skipped_when_no_db():
    """无 db 时降级为空，不抛异常。"""
    from internal.service.memory.consolidation_engine import ConsolidationEngine

    engine = ConsolidationEngine.__new__(ConsolidationEngine)
    engine._get_db = lambda: None
    assert engine._find_similar_nodes_pgvector("x", "n1", 0.9) == []
