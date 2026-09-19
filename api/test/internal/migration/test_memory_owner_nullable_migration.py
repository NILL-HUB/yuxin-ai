"""记忆主体解阻塞迁移守卫（ADMIN-P3c-1）。

不变量：
1. 新迁移必须是当前单 head（down_revision == 'y2b3c4d5e6f8'）；
2. 必须把 owner_account_id 改为可空（DROP NOT NULL）；
3. 必须补「按主体类型非空」的 CHECK，而非仅去掉非空（否则约束语义丢失）；
4. 必须扫描动态向量分表（与 P3b 的 y2b3c4d5e6f8 同法）；
5. 必须可逆（downgrade 存在）。
"""
import re
from pathlib import Path

API_ROOT = Path(__file__).resolve().parents[3]
VERSIONS = API_ROOT / "internal" / "migration" / "versions"
MIGRATION = VERSIONS / "z3c4d5e6f7a8_memory_owner_nullable_account.py"


def _source() -> str:
    assert MIGRATION.is_file(), "缺少解阻塞迁移"
    return MIGRATION.read_text(encoding="utf-8")


def test_down_revision_points_to_previous_head():
    down = re.search(r"^down_revision\s*=\s*[\"']([^\"']+)[\"']", _source(), re.M)
    assert down is not None, "迁移必须声明 down_revision"
    assert down.group(1) == "y2b3c4d5e6f8", "down_revision 必须指向 y2b3c4d5e6f8"


def test_revision_id_is_declared():
    rev = re.search(r"^revision\s*=\s*[\"']([^\"']+)[\"']", _source(), re.M)
    assert rev is not None
    assert rev.group(1) == "z3c4d5e6f7a8"


def test_drops_not_null_on_account_column():
    source = _source()
    assert "DROP NOT NULL" in source, "必须解除 owner_account_id 的非空约束"
    assert "owner_account_id" in source


def test_adds_subject_type_check_constraint():
    """仅去掉 NOT NULL 会让主体类型与归属列失去一致性保证。"""
    source = _source()
    assert "CHECK" in source.upper()
    assert "owner_type = 'user'" in source
    assert "owner_type = 'admin'" in source
    assert "owner_admin_user_id IS NOT NULL" in source


def test_scans_dynamic_embedding_tables():
    source = _source()
    assert "information_schema.tables" in source
    assert "user_memory_embedding_" in source


def test_migration_is_reversible():
    source = _source()
    assert "def downgrade" in source
    # 回退时若存在 admin 主体行必须拒绝（否则 SET NOT NULL 会炸且丢语义）
    assert "owner_type = 'admin'" in source
    # 拒绝逻辑必须覆盖分表：分表若留 admin 行，SET NOT NULL 会落到裸 PG 报错
    assert source.count("owner_type = 'admin'") >= 2, "降级守卫必须同时检查主表与分表"
