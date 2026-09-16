"""P2 会话/消息表与 builtin_key 迁移守卫。

设计 §10.1：管理端 Agent 的会话与消息走**独立表**，不与用户端
conversation/message 混表；预置 Agent 需 builtin_key 作幂等键。

为什么不写「源码字符串子串」断言：那种写法对改名/位移完全不敏感——
外键名从 `fk_admin_agent_conversation_agent_id_admin_agent` 改成规范名后，
旧断言依然通过，约束是否真的建出来无人守卫。因此这里用
`sqlalchemy.create_mock_engine` + alembic `MigrationContext`/`Operations`
捕获 `upgrade()` / `downgrade()` **真实生成的 DDL**，再对 DDL 文本断言。
"""
from __future__ import annotations

import importlib.util
import re
from pathlib import Path

from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import create_mock_engine

API_ROOT = Path(__file__).resolve().parents[3]
VERSIONS = API_ROOT / "internal" / "migration" / "versions"
MIGRATION = VERSIONS / "x1a2b3c4d5e7_add_admin_agent_conversation.py"

_INDEX_RE = re.compile(r"^CREATE (?:UNIQUE )?INDEX (\w+) ON (\w+) ")


def _load_migration():
    spec = importlib.util.spec_from_file_location(
        "x1a2b3c4d5e7_add_admin_agent_conversation", MIGRATION
    )
    assert spec is not None and spec.loader is not None, "无法载入 P2 会话表迁移"
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _migration_ddl(direction: str) -> list[str]:
    """执行迁移的 upgrade()/downgrade()，返回其真实生成的 DDL（空白已归一化）。"""
    module = _load_migration()
    statements: list[str] = []

    def _record(sql, *multiparams, **params):
        statements.append(" ".join(str(sql.compile(dialect=engine.dialect)).split()))

    engine = create_mock_engine("postgresql+psycopg2://", _record)
    context = MigrationContext.configure(engine.connect())
    original_op = module.op
    module.op = Operations(context)
    try:
        getattr(module, direction)()
    finally:
        module.op = original_op
    return statements


def _index_statements(statements: list[str]) -> set[tuple[str, str]]:
    return {
        (match.group(1), match.group(2))
        for statement in statements
        for match in [_INDEX_RE.match(statement)]
        if match is not None
    }


def test_migration_declares_correct_down_revision():
    assert MIGRATION.is_file(), "缺少 P2 会话表迁移"
    source = MIGRATION.read_text(encoding="utf-8")
    down = re.search(r"^down_revision\s*=\s*[\"']([^\"']+)[\"']", source, re.M)
    assert down is not None
    assert down.group(1) == "w1e2f3a4b5c6", "down_revision 必须是当前单 head"


def test_upgrade_creates_both_conversation_tables():
    ddl = _migration_ddl("upgrade")
    assert any(s.startswith("CREATE TABLE admin_agent_conversation ") for s in ddl)
    assert any(s.startswith("CREATE TABLE admin_agent_message ") for s in ddl)


def test_upgrade_adds_builtin_key_with_partial_unique_index():
    ddl = _migration_ddl("upgrade")

    assert "ALTER TABLE admin_agent ADD COLUMN builtin_key VARCHAR(64)" in ddl

    assert (
        "CREATE UNIQUE INDEX admin_agent_owner_builtin_uniq ON admin_agent "
        "(owner_admin_user_id, builtin_key) WHERE builtin_key IS NOT NULL"
    ) in ddl, "builtin_key 幂等键必须是部分唯一索引，而非全表唯一约束"


def test_upgrade_creates_expected_foreign_keys():
    joined = " ".join(_migration_ddl("upgrade"))

    assert (
        "CONSTRAINT fk_admin_agent_conversation_admin_agent_id_admin_agent "
        "FOREIGN KEY(admin_agent_id) REFERENCES admin_agent (id) ON DELETE CASCADE"
    ) in joined
    assert (
        "CONSTRAINT fk_admin_agent_conversation_admin_user_id_admin_user "
        "FOREIGN KEY(admin_user_id) REFERENCES admin_user (id) ON DELETE CASCADE"
    ) in joined, "admin_user_id 必须有指向 admin_user 的外键"
    assert (
        "CONSTRAINT fk_admin_agent_message_conversation_id_admin_agent_conversation "
        "FOREIGN KEY(conversation_id) REFERENCES admin_agent_conversation (id) ON DELETE CASCADE"
    ) in joined


def test_upgrade_creates_expected_indexes():
    assert _index_statements(_migration_ddl("upgrade")) == {
        ("admin_agent_owner_builtin_uniq", "admin_agent"),
        ("admin_agent_conversation_admin_agent_id_idx", "admin_agent_conversation"),
        ("admin_agent_conversation_admin_user_id_idx", "admin_agent_conversation"),
        ("admin_agent_message_conversation_id_idx", "admin_agent_message"),
    }


def test_downgrade_drops_message_before_conversation_and_builtin_key():
    ddl = _migration_ddl("downgrade")

    assert "DROP TABLE admin_agent_message" in ddl
    assert "DROP TABLE admin_agent_conversation" in ddl
    assert ddl.index("DROP TABLE admin_agent_message") < ddl.index(
        "DROP TABLE admin_agent_conversation"
    ), "必须先删消息表再删会话表，否则外键依赖会阻塞删除"

    for index_name in (
        "admin_agent_message_conversation_id_idx",
        "admin_agent_conversation_admin_user_id_idx",
        "admin_agent_conversation_admin_agent_id_idx",
        "admin_agent_owner_builtin_uniq",
    ):
        assert f"DROP INDEX {index_name}" in ddl

    assert "ALTER TABLE admin_agent DROP COLUMN builtin_key" in ddl


def test_models_exported_and_declared():
    from internal.model import AdminAgentConversation, AdminAgentMessage

    assert AdminAgentConversation.__tablename__ == "admin_agent_conversation"
    assert AdminAgentMessage.__tablename__ == "admin_agent_message"
    assert hasattr(AdminAgentConversation, "admin_agent_id")
    assert hasattr(AdminAgentConversation, "admin_user_id")
    assert hasattr(AdminAgentMessage, "tool_calls")


def test_admin_agent_model_declares_builtin_key_partial_unique_index():
    from internal.model import AdminAgent

    assert hasattr(AdminAgent, "builtin_key")

    index = next(
        (i for i in AdminAgent.__table__.indexes if i.name == "admin_agent_owner_builtin_uniq"),
        None,
    )
    assert index is not None, "预置 Agent 幂等键 admin_agent_owner_builtin_uniq 缺失"
    assert index.unique is True
    assert [column.name for column in index.columns] == ["owner_admin_user_id", "builtin_key"]
    assert str(index.dialect_options["postgresql"]["where"]) == "builtin_key IS NOT NULL"


def test_conversation_model_declares_admin_user_foreign_key():
    from internal.model import AdminAgentConversation

    constraints = {
        constraint.name: constraint
        for constraint in AdminAgentConversation.__table__.foreign_key_constraints
    }
    assert set(constraints) == {
        "fk_admin_agent_conversation_admin_agent_id_admin_agent",
        "fk_admin_agent_conversation_admin_user_id_admin_user",
    }

    admin_user_fk = constraints["fk_admin_agent_conversation_admin_user_id_admin_user"]
    assert [element.target_fullname for element in admin_user_fk.elements] == ["admin_user.id"]
    assert admin_user_fk.ondelete == "CASCADE"


def test_models_declare_same_index_names_as_migration():
    from internal.model import AdminAgentConversation, AdminAgentMessage

    assert {index.name for index in AdminAgentConversation.__table__.indexes} == {
        "admin_agent_conversation_admin_agent_id_idx",
        "admin_agent_conversation_admin_user_id_idx",
    }
    assert {index.name for index in AdminAgentMessage.__table__.indexes} == {
        "admin_agent_message_conversation_id_idx",
    }
