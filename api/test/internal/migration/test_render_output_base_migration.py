"""成品库标识与唯一约束守卫。

成品库必须「每账号至多一个」且由系统托管。唯一性靠 PostgreSQL 部分唯一索引
（created_from='render_output'）兜底：普通唯一约束会把同账号的多个
manual_upload 库也判为冲突，语义错误。
"""
import re
from pathlib import Path

API_ROOT = Path(__file__).resolve().parents[3]
VERSIONS = API_ROOT / "internal" / "migration" / "versions"
MIGRATION = VERSIONS / "w1e2f3a4b5c6_add_render_output_base_unique.py"


def test_render_output_enum_exists():
    from internal.entity.knowledge_entity import KnowledgeCreatedFrom

    assert KnowledgeCreatedFrom.RENDER_OUTPUT.value == "render_output"


def test_migration_file_exists_with_correct_down_revision():
    assert MIGRATION.is_file(), "缺少成品库唯一索引迁移"
    source = MIGRATION.read_text(encoding="utf-8")

    down = re.search(r"^down_revision\s*=\s*[\"']([^\"']+)[\"']", source, re.M)
    assert down is not None, "迁移必须声明 down_revision"
    assert down.group(1) == "v0d1e2f3a4b5", (
        "down_revision 必须指向当前单 head（v0d1e2f3a4b5）；"
        "指向其他分支会造成多 head，alembic upgrade head 直接失败"
    )


def test_migration_creates_partial_unique_index():
    source = MIGRATION.read_text(encoding="utf-8")

    assert "unique=True" in source
    assert "postgresql_where" in source, "必须是部分唯一索引，而非全表唯一约束"
    assert "render_output" in source


def test_migration_is_reversible():
    source = MIGRATION.read_text(encoding="utf-8")

    assert "def downgrade" in source
    assert "drop_index" in source
