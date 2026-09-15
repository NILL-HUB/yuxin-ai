"""视觉向量表结构测试。"""
from internal.model import VideoVisualEmbedding


class TestVideoVisualEmbeddingModel:
    def test_table_name(self):
        assert VideoVisualEmbedding.__tablename__ == "video_visual_embedding"

    def test_required_columns_exist(self):
        columns = {c.name for c in VideoVisualEmbedding.__table__.columns}
        for name in (
            "id", "knowledge_base_id", "knowledge_document_id", "segment_id",
            "account_id", "frame_url", "scene_index", "embedding", "model_id",
            "updated_at", "created_at",
        ):
            assert name in columns, f"缺少列 {name}"

    def test_dimension_constant_is_within_pgvector_limit(self):
        """pgvector 的 vector 类型上限 2000；原生 4096 必须经 MRL 降到 1536。"""
        from internal.model.video_visual_embedding import VISUAL_EMBEDDING_DIMENSION

        assert VISUAL_EMBEDDING_DIMENSION <= 2000
        assert VISUAL_EMBEDDING_DIMENSION == 1536

    def test_embedding_column_uses_visual_dimension(self):
        column = VideoVisualEmbedding.__table__.columns["embedding"]
        assert column.type.dim == 1536

    def test_segment_unique_constraint_exists(self):
        """一条片段只应有一条视觉向量，重解析走 upsert 而非累积。"""
        names = {c.name for c in VideoVisualEmbedding.__table__.constraints if c.name}
        assert "uq_video_visual_embedding_segment" in names

    def test_foreign_keys_cascade_on_delete(self):
        """素材/板块删除时视觉向量必须随之清理，避免孤儿行。"""
        table = VideoVisualEmbedding.__table__
        for column_name in ("knowledge_base_id", "knowledge_document_id", "segment_id"):
            fks = list(table.columns[column_name].foreign_keys)
            assert fks, f"{column_name} 缺少外键"
            assert fks[0].ondelete == "CASCADE", f"{column_name} 外键未设 CASCADE"
