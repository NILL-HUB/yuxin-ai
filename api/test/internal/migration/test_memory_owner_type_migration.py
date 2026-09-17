"""记忆主体三列迁移守卫。

设计 §8：`user_memory` 与向量分表补 `owner_type` / `owner_admin_user_id` /
`owner_agent_id`；存量全标 `owner_type='user'`，**行为零变化**。
"""
import re
from pathlib import Path

API_ROOT = Path(__file__).resolve().parents[3]
VERSIONS = API_ROOT / "internal" / "migration" / "versions"
MIGRATION = VERSIONS / "y2b3c4d5e6f8_add_memory_owner_type.py"


def _source() -> str:
    assert MIGRATION.is_file(), "缺少记忆主体迁移"
    return MIGRATION.read_text(encoding="utf-8")


def test_down_revision_points_to_current_single_head():
    down = re.search(r"^down_revision\s*=\s*[\"']([^\"']+)[\"']", _source(), re.M)
    assert down is not None, "迁移必须声明 down_revision"
    assert down.group(1) == "x1a2b3c4d5e7", (
        "down_revision 必须指向当前单 head（x1a2b3c4d5e7）"
    )


def test_migration_adds_three_columns_to_user_memory():
    source = _source()
    for column in ("owner_type", "owner_admin_user_id", "owner_agent_id"):
        assert column in source, f"迁移必须补 {column} 列"


def test_migration_backfills_existing_rows_as_user():
    """存量必须回填 owner_type='user'，否则新列非空约束会炸或语义错误。"""
    source = _source()
    assert "owner_type" in source
    assert re.search(r"UPDATE\s+user_memory", source, re.I), "必须回填存量行"
    assert "'user'" in source


def test_migration_creates_owner_agent_fk_and_index():
    source = _source()
    assert "admin_agent" in source, "owner_agent_id 必须 FK 到 admin_agent"
    assert "create_index" in source
    assert "owner_agent" in source


def test_migration_is_reversible():
    source = _source()
    assert "def downgrade" in source
    assert "drop_column" in source or "op.drop_column" in source


def test_model_declares_the_three_columns():
    from internal.model import UserMemory

    for column in ("owner_type", "owner_admin_user_id", "owner_agent_id"):
        assert column in UserMemory.__table__.c, f"模型缺列 {column}"
