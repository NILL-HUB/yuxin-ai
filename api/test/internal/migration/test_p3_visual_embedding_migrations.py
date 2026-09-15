"""P3 迁移文件测试：视觉向量表 + 硅基流动视觉编码模型 seed。

这些是「文件级」断言：迁移在测试环境不会真正执行（无 PostgreSQL），
因此断言迁移脚本的关键属性，防止后续被改坏。
"""
from pathlib import Path

import re

API_ROOT = Path(__file__).resolve().parents[3]
VERSIONS_DIR = API_ROOT / "internal/migration/versions"
TABLE_MIGRATION = VERSIONS_DIR / "c9d0e1f2a3b4_add_video_visual_embedding.py"
SEED_MIGRATION = VERSIONS_DIR / "dae1f2a3b4c5_seed_siliconflow_vl_embedding.py"


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


class TestVideoVisualEmbeddingMigration:
    def test_migration_exists(self):
        assert TABLE_MIGRATION.is_file(), "缺少视觉向量表迁移"

    def test_declares_table_and_dimension(self):
        source = _read(TABLE_MIGRATION)
        assert "video_visual_embedding" in source
        assert "Vector(1536)" in source or "Vector(VISUAL_EMBEDDING_DIMENSION)" in source

    def test_creates_hnsw_index(self):
        """量级上需要 ANN 索引，否则全表顺序扫描。"""
        source = _read(TABLE_MIGRATION)
        assert "hnsw" in source.lower()
        assert "vector_cosine_ops" in source

    def test_has_downgrade_dropping_table(self):
        source = _read(TABLE_MIGRATION)
        assert re.search(r"def downgrade\(\):", source)
        assert "drop_table" in source

    def test_declares_real_down_revision(self):
        """down_revision 必须指向已提交的迁移（历史上曾指向未跟踪文件导致部署崩溃）。"""
        source = _read(SEED_MIGRATION.parent / TABLE_MIGRATION.name)
        match = re.search(r"^down_revision\s*=\s*[\"']([^\"']+)[\"']", source, re.M)
        assert match, "未声明 down_revision"
        assert match.group(1) != "None"


class TestVisualEmbeddingSeedMigration:
    def test_migration_exists(self):
        assert SEED_MIGRATION.is_file(), "缺少视觉编码模型 seed 迁移"

    def test_seed_is_idempotent(self):
        """必须用 WHERE NOT EXISTS / ON CONFLICT，重复执行不得插入重复行。"""
        source = _read(SEED_MIGRATION)
        assert "NOT EXISTS" in source or "ON CONFLICT" in source

    def test_seed_declares_provider_model_and_dimension(self):
        source = _read(SEED_MIGRATION)
        assert "SiliconFlow" in source
        assert "Qwen/Qwen3-VL-Embedding-8B" in source
        assert "visual_embedding" in source
        assert "1536" in source

    def test_seed_does_not_write_api_key(self):
        """迁移不得写入密钥——密钥由管理员在 admin 配置，禁止把凭据固化进代码库。"""
        source = _read(SEED_MIGRATION)
        # 只检查真实 SQL 语句，避免文档字符串里提到表名造成误判
        sql_statements = [
            line for line in source.splitlines()
            if line.strip().upper().startswith(("INSERT", "UPDATE", "DELETE"))
        ]
        assert not any("model_key_config" in line for line in sql_statements), (
            "seed 迁移不得写入 model_key_config（密钥由 admin 配置）"
        )
        assert "key_value_encrypted" not in source

    def test_seed_chains_after_table_migration(self):
        source = _read(SEED_MIGRATION)
        match = re.search(r"^down_revision\s*=\s*[\"']([^\"']+)[\"']", source, re.M)
        assert match, "未声明 down_revision"
        table_source = _read(TABLE_MIGRATION)
        table_rev = re.search(r"^revision\s*=\s*[\"']([^\"']+)[\"']", table_source, re.M)
        assert table_rev and match.group(1) == table_rev.group(1)
