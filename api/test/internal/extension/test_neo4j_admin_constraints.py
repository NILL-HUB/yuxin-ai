"""Neo4j admin 侧约束/索引必须与用户侧对称且真实生效（属性级切分的 schema 面）。

背景：Neo4j 约束的真实生效点是 `neo4j_extension._ensure_constraints_and_indexes`
（启动时幂等执行）；`internal/migration/neo4j_init.cypher` 是全仓零引用的死文件，
故本测试只针对 extension，避免守错对象。
"""
from pathlib import Path

SOURCE = (
    Path(__file__).resolve().parents[3]
    / "internal" / "extension" / "neo4j_extension.py"
)


def _source() -> str:
    return SOURCE.read_text(encoding="utf-8")


def test_admin_user_unique_constraint_declared():
    """admin 侧必须有按 admin_user_id + agent_id 的唯一约束（与用户侧 user_id 对称）。"""
    source = _source()
    assert "admin_user_id" in source, "extension 必须声明 admin 侧唯一约束"
    assert "agent_id" in source


def test_admin_user_index_declared():
    source = _source()
    assert "admin_user_id_idx" in source, "admin 侧需索引支撑过滤"


def test_user_side_constraint_preserved():
    """不得为了加 admin 约束而改坏既有 user 侧约束（存量依赖它）。"""
    source = _source()
    assert "(n.name, n.user_id) IS UNIQUE" in source
