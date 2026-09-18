"""跨层主体键一致性守卫（真库 + 真图校验；不可用时 skip，不制造假绿）。

验证 P3b 的核心前提：
1. 用户主体字符串键 `to_key()` == 存量 `user_memory.owner_account_id` 的 `str()`；
2. Neo4j 属性级分离成立：存量节点只有裸 UUID 的 `user_id`，无前缀值，且不存在
   「同时带 `user_id` 与 `admin_user_id`」的混装节点；
3. 用户主体的 `neo4j_props()` / `neo4j_filter_condition()` 产物与存量写入形态一致
   （裸 UUID + `user_id` 属性），且能真实命中存量节点；
4. admin 侧约束已真实落地（Task 2b 的效果，在库上可见）。

这些是「存储层事实」，静态文件断言只能证明代码写了什么，证明不了库里是否真如此。
"""
import os
from uuid import UUID

import pytest


def _pg_engine():
    """返回可连的同步引擎；无可用 PostgreSQL 时返回 None（调用方 skip）。"""
    from sqlalchemy import create_engine

    from config import Config

    uri = getattr(Config(), "SQLALCHEMY_DATABASE_URI", "") or ""
    if not uri.startswith("postgresql"):
        return None
    try:
        engine = create_engine(uri)
        with engine.connect():
            pass
        return engine
    except Exception:
        return None


@pytest.fixture()
def pg_engine():
    engine = _pg_engine()
    if engine is None:
        pytest.skip("无可用 PostgreSQL，跳过跨层键一致性校验")
    yield engine
    engine.dispose()


def _neo4j_driver():
    """返回可连的 Neo4j 驱动；不可用时返回 None（调用方 skip）。

    与同目录/相邻 live 守卫保持同一来源约定：优先环境变量，缺失时回落
     `settings.neo4j`。本守卫自身不写入口令字面量（凭据统一取自 env / `settings.neo4j`）；
     硬编码口令会使守卫在口令变更时静默 skip、失去覆盖。
     """
    uri = os.getenv("NEO4J_URI", "")
    user = os.getenv("NEO4J_USER", "")
    password = os.getenv("NEO4J_PASSWORD", "")
    if not (uri and user and password):
        from internal.config.memory_settings import settings

        uri = uri or settings.neo4j.uri
        user = user or settings.neo4j.user
        password = password or settings.neo4j.password
    try:
        from neo4j import GraphDatabase

        driver = GraphDatabase.driver(uri, auth=(user, password))
        driver.verify_connectivity()
        return driver
    except Exception:
        return None


@pytest.fixture()
def neo4j_driver():
    driver = _neo4j_driver()
    if driver is None:
        pytest.skip("无可用 Neo4j，跳过跨层键一致性校验")
    yield driver
    driver.close()


# =========================================================
# PG：用户主体键 == 存量 owner_account_id 的字符串形态
# =========================================================


def test_user_owner_key_equals_stored_owner_account_id(pg_engine):
    from sqlalchemy import text

    from internal.entity.memory_owner_entity import MemoryOwnerKey

    with pg_engine.connect() as conn:
        rows = conn.execute(
            text(
                "SELECT DISTINCT owner_account_id FROM user_memory "
                "WHERE owner_type = 'user' AND owner_account_id IS NOT NULL LIMIT 20"
            )
        ).all()

    assert rows, "无存量 user 主体行可供校验"
    for (account_id,) in rows:
        assert MemoryOwnerKey.for_user(account_id).to_key() == str(account_id)


def test_no_prefixed_user_owner_type_in_storage(pg_engine):
    """owner_type 不得混入带 `user:` 前缀的脏数据（形态契约）。"""
    from sqlalchemy import text

    with pg_engine.connect() as conn:
        bad = conn.execute(
            text("SELECT count(*) FROM user_memory WHERE owner_type LIKE '%:%'")
        ).scalar()
    assert bad == 0


def test_owner_type_is_known_enum_value(pg_engine):
    """owner_type 取值必须落在已知枚举内（防「拼错但无冒号」的脏值，如 usr/admn）。"""
    from sqlalchemy import text

    with pg_engine.connect() as conn:
        bad = conn.execute(
            text(
                "SELECT count(*) FROM user_memory "
                "WHERE owner_type IS NULL OR owner_type NOT IN ('user', 'admin')"
            )
        ).scalar()
    assert bad == 0


# =========================================================
# Neo4j：属性级分离 + 访问器产物与存量形态一致 + admin 约束落地
# =========================================================


def test_neo4j_user_ids_are_bare_uuids(neo4j_driver):
    # 不做 LIMIT 抽样：全图扫描代价可忽略，抽样会让未抽中的脏数据漏检
    with neo4j_driver.session() as session:
        records = session.run(
            "MATCH (n) WHERE n.user_id IS NOT NULL "
            "RETURN DISTINCT n.user_id AS uid"
        ).data()

    prefixed = [
        r["uid"] for r in records if str(r["uid"]).startswith(("user:", "admin:"))
    ]
    assert prefixed == [], (
        "Neo4j 存量 user_id 出现带前缀值——说明有人把复合键写进了 user 属性，"
        f"与属性分离设计冲突：{prefixed[:5]}"
    )
    for record in records:
        UUID(str(record["uid"]))  # 非 UUID 即抛出，视为脏数据


def test_neo4j_user_props_match_storage_shape(neo4j_driver):
    from internal.entity.memory_owner_entity import MemoryOwnerKey

    with neo4j_driver.session() as session:
        record = session.run(
            "MATCH (n:Episode) WHERE n.user_id IS NOT NULL "
            "RETURN n.user_id AS uid LIMIT 1"
        ).single()
        if record is None:
            pytest.skip("库中无存量 Episode 节点")

        owner = MemoryOwnerKey.for_user(UUID(str(record["uid"])))
        props = owner.neo4j_props()
        condition = owner.neo4j_filter_condition("n")

        assert props == {"user_id": str(record["uid"])}
        assert condition == "n.user_id = $user_id"

        count = session.run(
            f"MATCH (n:Episode) WHERE {condition} RETURN count(n) AS c", **props
        ).single()["c"]
        assert count >= 1, "用户主体访问器产物无法命中存量节点——读路径将失效"


def test_neo4j_no_mixed_owner_nodes(neo4j_driver):
    with neo4j_driver.session() as session:
        mixed = session.run(
            "MATCH (n) WHERE n.user_id IS NOT NULL AND n.admin_user_id IS NOT NULL "
            "RETURN count(n) AS c"
        ).single()["c"]

    assert mixed == 0, "存在同时带 user_id 与 admin_user_id 的节点，属性分离被破坏"


def test_neo4j_admin_constraints_present(neo4j_driver):
    with neo4j_driver.session() as session:
        names = {
            r["name"]
            for r in session.run("SHOW CONSTRAINTS YIELD name RETURN name").data()
        }

    assert "entity_name_admin_unique" in names, "admin 侧约束未落地（Task 2b 未生效）"
    assert "community_key_admin_unique" in names
