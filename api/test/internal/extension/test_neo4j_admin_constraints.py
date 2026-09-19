"""Neo4j admin 侧约束/索引必须与用户侧对称且真实生效（属性级切分的 schema 面）。

背景：Neo4j 约束的真实生效点是 `neo4j_extension._ensure_constraints_and_indexes`
（启动时幂等执行）；`internal/migration/neo4j_init.cypher` 是全仓零引用的死文件，
故本测试只针对 extension，避免守错对象。

断言采用**精确语句集合**而非裸子串 —— 裸子串无法防「标签拼错 / 属性拼错 /
语句被整体删除（注释里仍有同名字符串）」等变异（见 P3b Task 2b 质量审查）。

实现方式：源码里多条语句因行长被拆成**相邻字符串字面量隐式拼接**，
故用 `ast` 解析 `_ensure_constraints_and_indexes` 的 `statements` 列表并
`literal_eval` 每个元素 —— 取到的正是**真正下发给 Neo4j 的语句**（Python
解析器已把隐式拼接合并为单个字符串常量），既不受断行位置影响，
也仍能拦住标签/属性拼错与整条删除。
"""
import ast
from pathlib import Path

SOURCE = (
    Path(__file__).resolve().parents[3]
    / "internal" / "extension" / "neo4j_extension.py"
)

_FUNC = "_ensure_constraints_and_indexes"

_ADMIN_CONSTRAINTS = (
    "CREATE CONSTRAINT entity_name_admin_unique IF NOT EXISTS "
    "FOR (n:Entity) REQUIRE (n.name, n.admin_user_id, n.agent_id) IS UNIQUE",
    "CREATE CONSTRAINT community_key_admin_unique IF NOT EXISTS "
    "FOR (n:Community) REQUIRE (n.key, n.admin_user_id, n.agent_id) IS UNIQUE",
)

_ADMIN_INDEXES = (
    "CREATE INDEX episode_admin_user_id_idx IF NOT EXISTS FOR (n:Episode) ON (n.admin_user_id)",
    "CREATE INDEX entity_admin_user_id_idx IF NOT EXISTS FOR (n:Entity) ON (n.admin_user_id)",
    "CREATE INDEX memorynode_admin_user_id_idx IF NOT EXISTS FOR (n:MemoryNode) ON (n.admin_user_id)",
    "CREATE INDEX community_admin_user_id_idx IF NOT EXISTS FOR (n:Community) ON (n.admin_user_id)",
)


def _source() -> str:
    assert SOURCE.is_file(), f"未找到 {SOURCE}"
    return SOURCE.read_text(encoding="utf-8")


def _declared_statements() -> list:
    """精确取回 `_ensure_constraints_and_indexes` 中下发的全部 DDL 语句。"""
    tree = ast.parse(_source())
    for node in ast.walk(tree):
        if not (isinstance(node, ast.FunctionDef) and node.name == _FUNC):
            continue
        for stmt in node.body:
            if not isinstance(stmt, ast.Assign):
                continue
            targets = [t for t in stmt.targets if isinstance(t, ast.Name)]
            if any(t.id == "statements" for t in targets):
                assert isinstance(stmt.value, ast.List), "statements 必须是列表字面量"
                return [ast.literal_eval(el) for el in stmt.value.elts]
    raise AssertionError(f"未在 {_FUNC} 中找到 statements 列表")


def test_admin_unique_constraints_declared_verbatim():
    """两条 admin 唯一约束必须**逐字**存在（防标签/属性拼错、防整条被删）。"""
    statements = _declared_statements()
    for statement in _ADMIN_CONSTRAINTS:
        assert statement in statements, f"缺少或写错 admin 唯一约束：{statement}"


def test_admin_indexes_declared_verbatim():
    """四个 admin 索引必须**逐字**存在。"""
    statements = _declared_statements()
    for statement in _ADMIN_INDEXES:
        assert statement in statements, f"缺少或写错 admin 索引：{statement}"


def test_user_side_constraint_preserved():
    """不得为了加 admin 约束而改坏既有 user 侧约束（存量依赖它）。"""
    statements = _declared_statements()
    assert (
        "CREATE CONSTRAINT entity_node_id IF NOT EXISTS "
        "FOR (n:Entity) REQUIRE (n.name, n.user_id) IS UNIQUE" in statements
    )


def test_existing_three_statements_still_present():
    """既有 3 条（Episode node_id / Entity name+user_id / 全文索引）必须仍在。"""
    statements = _declared_statements()
    assert any("REQUIRE n.node_id IS UNIQUE" in s for s in statements)
    assert any("REQUIRE (n.name, n.user_id) IS UNIQUE" in s for s in statements)
    assert any(s.startswith("CREATE FULLTEXT INDEX memoryFullText") for s in statements)


def test_admin_constraint_applies_to_both_levels_via_sentinel():
    """约束对「管理员级」生效的前提是写入侧**始终写 agent_id**（哨兵兜底）。

    Neo4j 多属性唯一约束要求属性全存在才施加。修复方式：admin 节点恒写 agent_id
    （Agent 级写真实 UUID、管理员级写 NEO4J_ADMIN_LEVEL_AGENT_SENTINEL），
    使 (name, admin_user_id, agent_id) 对两级同时生效。
    """
    from internal.entity.memory_owner_entity import (
        MemoryOwnerKey,
        NEO4J_ADMIN_LEVEL_AGENT_SENTINEL,
    )
    from uuid import uuid4

    admin_id = uuid4()
    admin_level = MemoryOwnerKey.for_admin(admin_id).neo4j_props()

    assert "agent_id" in admin_level, "管理员级必须写 agent_id（否则约束对其豁免）"
    assert admin_level["agent_id"] == NEO4J_ADMIN_LEVEL_AGENT_SENTINEL
    # 约束文本本身必须覆盖 agent_id（若约束不含该属性，哨兵也救不了）
    statements = _declared_statements()
    assert any("REQUIRE (n.name, n.admin_user_id, n.agent_id) IS UNIQUE" in s for s in statements)
    assert any("REQUIRE (n.key, n.admin_user_id, n.agent_id) IS UNIQUE" in s for s in statements)


def test_sentinel_documented_in_extension():
    """写入侧恒写 agent_id 的前提必须在 extension 注释中登记（防读者误以为属性可省）。"""
    source = _source()
    assert "NEO4J_ADMIN_LEVEL_AGENT_SENTINEL" in source
    assert "所有属性都存在" in source or "整条豁免" in source
