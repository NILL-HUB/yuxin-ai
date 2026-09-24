"""全局控制配置表（global_control_config）迁移守卫。

GLOBAL-CONTROL-P1：新增单行 JSONB 表收编行为开关类全局配置，并把
public_ai_feature_config 中三条旧 feature（runtime_fallback / media_fetch /
agent_checkpoint_by_conversation）值搬入后删除旧记录。down_revision 指向
当前单 head f3e4d5c6b7a8。

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
MIGRATION = VERSIONS / "g1b2c3d4e5f8_add_global_control_config.py"


def _load_migration():
    spec = importlib.util.spec_from_file_location(
        "g1b2c3d4e5f8_add_global_control_config", MIGRATION
    )
    assert spec is not None and spec.loader is not None, "无法载入全局控制配置迁移"
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class _FakeResult:
    """mock engine 的 execute 返回 None；数据迁移的 bind.execute(...).fetchall()
    需要真实 Result 语义，这里包一层返回空结果代理。"""

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


def test_migration_declares_correct_down_revision():
    assert MIGRATION.is_file(), "缺少全局控制配置迁移"
    source = MIGRATION.read_text(encoding="utf-8")
    down = re.search(r"^down_revision\s*=\s*[\"']([^\"']+)[\"']", source, re.M)
    assert down is not None
    assert down.group(1) == "f3e4d5c6b7a8", "down_revision 必须是当前单 head"


def test_upgrade_creates_table_and_seed_row():
    ddl = _migration_ddl("upgrade")
    assert any(
        s.startswith("CREATE TABLE global_control_config")
        for s in ddl
    )
    assert any(
        "INSERT INTO global_control_config" in s
        and "ON CONFLICT (id) DO NOTHING" in s
        for s in ddl
    )


def test_upgrade_migrates_legacy_feature_rows():
    ddl = _migration_ddl("upgrade")
    joined = " ".join(ddl)
    assert "SELECT" in joined and "public_ai_feature_config" in joined
    assert "UPDATE global_control_config" in joined
    assert "DELETE FROM public_ai_feature_config" in joined
    # 三条旧 feature_key 都在清理清单里
    for key in ("runtime_fallback", "media_fetch", "agent_checkpoint_by_conversation"):
        assert key in joined


def test_downgrade_drops_table():
    ddl = _migration_ddl("downgrade")
    assert any(
        s.startswith("DROP TABLE global_control_config")
        for s in ddl
    )


def test_model_declares_table_and_configs_column():
    from internal.model.global_control_config import GlobalControlConfig

    assert GlobalControlConfig.__tablename__ == "global_control_config"
    assert "configs" in GlobalControlConfig.__table__.columns
    assert "id" in GlobalControlConfig.__table__.columns


def test_build_configs_from_legacy_rows_merges_enabled_and_extra():
    module = _load_migration()
    rows = [
        ("runtime_fallback", True, {"retry_attempts": 3}),
        ("media_fetch", True, {"max_bytes_fallback": 200}),
        ("agent_checkpoint_by_conversation", False, None),
        ("unknown_feature", True, {}),  # 未知行跳过
    ]
    configs = module._build_configs_from_legacy_rows(rows)
    assert configs["runtime_fallback"] == {"enabled": True, "retry_attempts": 3}
    assert configs["media_fetch"] == {"enabled": True, "max_bytes_fallback": 200}
    assert configs["agent_checkpoint"] == {"enabled": False}
    # 未在旧记录中的 section 保持默认
    assert configs["image_request_policy"] == {"policy": "strict"}
    assert configs["skill_catalog_sync"] == {"enabled": False}


def test_build_configs_from_legacy_rows_ignores_invalid_extra():
    module = _load_migration()
    rows = [
        ("runtime_fallback", None, {"retry_attempts": "0"}),
        ("media_fetch", None, {"max_bytes_fallback": -1}),
    ]
    configs = module._build_configs_from_legacy_rows(rows)
    assert configs["runtime_fallback"] == {"enabled": True, "retry_attempts": 5}
    assert configs["media_fetch"] == {"enabled": False, "max_bytes_fallback": 536870912}
