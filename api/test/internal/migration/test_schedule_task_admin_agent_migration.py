"""ADMIN-P4 T3 定时任务 admin_agent 通道迁移守卫。

设计：管理端 Agent 可以被绑定到定时任务上周期执行板块动作。
`schedule_task` / `schedule_task_run` 各加一列 `admin_agent_id`（UUID NULL，
FK → admin_agent.id），`down_revision` 指向当前单 head `z3c4d5e6f7a8`。

沿用既有迁移守卫写法（create_mock_engine 捕获真实 DDL），不写源码子串断言。
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
MIGRATION = VERSIONS / "f3e4d5c6b7a8_add_schedule_task_admin_agent.py"


def _load_migration():
    spec = importlib.util.spec_from_file_location(
        "f3e4d5c6b7a8_add_schedule_task_admin_agent", MIGRATION
    )
    assert spec is not None and spec.loader is not None, "无法载入 T3 定时任务迁移"
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _migration_ddl(direction: str) -> list[str]:
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


def test_migration_declares_correct_down_revision():
    assert MIGRATION.is_file(), "缺少 T3 定时任务迁移"
    source = MIGRATION.read_text(encoding="utf-8")
    down = re.search(r"^down_revision\s*=\s*[\"']([^\"']+)[\"']", source, re.M)
    assert down is not None
    assert down.group(1) == "z3c4d5e6f7a8", "down_revision 必须是当前单 head"


def test_upgrade_adds_admin_agent_id_to_both_tables():
    ddl = _migration_ddl("upgrade")
    assert "ALTER TABLE schedule_task ADD COLUMN admin_agent_id UUID" in ddl
    assert "ALTER TABLE schedule_task_run ADD COLUMN admin_agent_id UUID" in ddl


def test_upgrade_adds_foreign_keys_to_admin_agent():
    joined = " ".join(_migration_ddl("upgrade"))
    assert (
        "CONSTRAINT fk_schedule_task_admin_agent_id_admin_agent "
        "FOREIGN KEY(admin_agent_id) REFERENCES admin_agent (id)" in joined
    )
    assert (
        "CONSTRAINT fk_schedule_task_run_admin_agent_id_admin_agent "
        "FOREIGN KEY(admin_agent_id) REFERENCES admin_agent (id)" in joined
    )


def test_upgrade_creates_indexes():
    ddl = _migration_ddl("upgrade")
    assert any(
        s.startswith("CREATE INDEX ix_schedule_task_admin_agent ON schedule_task")
        for s in ddl
    )
    assert any(
        s.startswith("CREATE INDEX ix_schedule_task_run_admin_agent ON schedule_task_run")
        for s in ddl
    )


def test_downgrade_drops_columns_and_indexes():
    ddl = _migration_ddl("downgrade")
    assert "DROP INDEX ix_schedule_task_admin_agent" in ddl
    assert "DROP INDEX ix_schedule_task_run_admin_agent" in ddl
    assert "ALTER TABLE schedule_task_run DROP COLUMN admin_agent_id" in ddl
    assert "ALTER TABLE schedule_task DROP COLUMN admin_agent_id" in ddl


def test_models_declare_admin_agent_columns():
    from internal.model import ScheduleTask, ScheduleTaskRun

    assert hasattr(ScheduleTask, "admin_agent_id")
    assert hasattr(ScheduleTaskRun, "admin_agent_id")
    fk_names = {
        constraint.name
        for constraint in ScheduleTask.__table__.foreign_key_constraints
    }
    assert "fk_schedule_task_admin_agent_id_admin_agent" in fk_names
