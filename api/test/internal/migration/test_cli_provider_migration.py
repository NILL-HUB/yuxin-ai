"""cli_provider / cli_tool 表迁移守卫。

Task 1 新增 cli_provider / cli_tool 两表及其索引，用于登记纯 CLI 工具提供者与
工具元数据（工具粒度，1:N 关联）。down_revision 指向当前单 head p2c3d4e5f6a8。

沿用既有迁移守卫写法（create_mock_engine 捕获真实 DDL），不写源码子串断言。
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import create_mock_engine

API_ROOT = Path(__file__).resolve().parents[3]
VERSIONS = API_ROOT / "internal" / "migration" / "versions"
MIGRATION = VERSIONS / "c4e5f6a7b8d9_add_cli_provider_tables.py"


def _load_migration():
    spec = importlib.util.spec_from_file_location(
        "c4e5f6a7b8d9_add_cli_provider_tables", MIGRATION
    )
    assert spec is not None and spec.loader is not None, "无法载入 cli_provider 迁移"
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class _FakeResult:
    """mock engine 的 execute 返回 None（SQLAlchemy 2.0.x 行为）；包一层空 Result
    代理，兼容迁移内部对执行结果的迭代/取值。"""

    def fetchall(self):
        return []

    def __iter__(self):
        return iter(())

    def __next__(self):
        raise StopIteration


def _migration_ddl(direction: str) -> list[str]:
    module = _load_migration()
    statements: list[str] = []

    def _record(sql, *multiparams, **params):
        statements.append(" ".join(str(sql.compile(dialect=engine.dialect)).split()))

    engine = create_mock_engine("postgresql+psycopg2://", _record)
    conn = engine.connect()
    original_execute = conn.execute

    def _fake_execute(obj, *multiparams, **params):
        original_execute(obj, *multiparams, **params)
        return _FakeResult()

    conn.execute = _fake_execute
    context = MigrationContext.configure(conn)
    original_op = module.op
    module.op = Operations(context)
    try:
        getattr(module, direction)()
    finally:
        module.op = original_op
    return statements


def test_migration_links_to_known_head():
    assert MIGRATION.is_file(), "缺少 cli_provider 迁移"
    mod = _load_migration()
    assert mod.revision == "c4e5f6a7b8d9"
    assert mod.down_revision == "p2c3d4e5f6a8"


def test_upgrade_creates_both_tables():
    ddl = _migration_ddl("upgrade")
    assert any(s.startswith("CREATE TABLE cli_provider") for s in ddl)
    assert any(s.startswith("CREATE TABLE cli_tool") for s in ddl)


def test_upgrade_creates_indexes_including_gin():
    ddl = _migration_ddl("upgrade")
    for idx in (
        "cli_provider_account_id_idx",
        "cli_provider_is_public_idx",
        "cli_provider_task_keywords_idx",
        "cli_tool_provider_id_idx",
        "cli_tool_name_idx",
        "cli_tool_task_keywords_idx",
    ):
        assert any(
            s.startswith(f"CREATE INDEX {idx} ON ") for s in ddl
        ), f"缺少索引 {idx}"
    assert "USING gin (task_keywords)" in " ".join(ddl)


def test_ids_have_db_side_default():
    joined = " ".join(_migration_ddl("upgrade"))
    assert joined.count("uuid_generate_v4()") == 2


def test_downgrade_drops_tables_in_reverse_fk_order():
    ddl = _migration_ddl("downgrade")
    drop_tool = next(
        i for i, s in enumerate(ddl) if s.startswith("DROP TABLE cli_tool")
    )
    drop_provider = next(
        i for i, s in enumerate(ddl) if s.startswith("DROP TABLE cli_provider")
    )
    assert drop_tool < drop_provider, "cli_tool 依赖 cli_provider，必须先于其 drop"
    assert any(
        s.startswith("DROP INDEX cli_tool_provider_id_idx") for s in ddl
    )
    assert any(
        s.startswith("DROP INDEX cli_provider_account_id_idx") for s in ddl
    )


def test_migration_tables_match_models():
    from internal.model.cli import CliProvider, CliTool

    assert CliProvider.__tablename__ == "cli_provider"
    assert CliTool.__tablename__ == "cli_tool"
    assert hasattr(CliProvider, "tool_schema")
    assert hasattr(CliTool, "task_keywords")
    joined = " ".join(_migration_ddl("upgrade"))
    assert f"CREATE TABLE {CliProvider.__tablename__}" in joined
    assert f"CREATE TABLE {CliTool.__tablename__}" in joined
