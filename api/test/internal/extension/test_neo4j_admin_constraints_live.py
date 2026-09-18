"""admin 侧 Neo4j 约束/索引在**真实库**上确实存在的守卫。

与同目录静态测试互补：静态测试防「代码写错」，本测试防「DDL 静默吞异常导致
约束从未真正创建」（`_ensure_constraints_and_indexes` 对每条语句
`except Exception: logger.warning(...)`，拼错不会阻断启动）。

无可用 Neo4j 时 skip（不制造假绿）。
"""
import os

import pytest


def _driver():
    uri = os.getenv("NEO4J_URI", "bolt://localhost:7687")
    user = os.getenv("NEO4J_USER", "neo4j")
    password = os.getenv("NEO4J_PASSWORD", "")
    if not password:
        from internal.config.memory_settings import settings

        password = settings.neo4j.password
        uri = settings.neo4j.uri
        user = settings.neo4j.user
    try:
        from neo4j import GraphDatabase

        driver = GraphDatabase.driver(uri, auth=(user, password))
        driver.verify_connectivity()
        return driver
    except Exception as exc:  # noqa: BLE001
        pytest.skip(f"无可用 Neo4j，跳过 admin 约束真库校验：{exc}")


@pytest.fixture()
def driver():
    d = _driver()
    yield d
    d.close()


def test_admin_constraints_present_in_live_db(driver):
    with driver.session() as session:
        names = {
            r["name"]
            for r in session.run("SHOW CONSTRAINTS YIELD name RETURN name").data()
        }
    assert "entity_name_admin_unique" in names, "admin 实体唯一约束未在真库落地"
    assert "community_key_admin_unique" in names, "admin Community 唯一约束未在真库落地"


def test_admin_indexes_present_in_live_db(driver):
    with driver.session() as session:
        names = {
            r["name"]
            for r in session.run("SHOW INDEXES YIELD name RETURN name").data()
        }
    for expected in (
        "episode_admin_user_id_idx",
        "entity_admin_user_id_idx",
        "memorynode_admin_user_id_idx",
        "community_admin_user_id_idx",
    ):
        assert expected in names, f"admin 索引未在真库落地：{expected}"
