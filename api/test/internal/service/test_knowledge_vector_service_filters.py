"""向量检索过滤参数测试：断言生成的 SQL 含预期 WHERE 条件与绑定参数。"""
from types import SimpleNamespace
from uuid import uuid4

from internal.service.knowledge_vector_service import KnowledgeVectorService


class _ResultStub:
    def __init__(self, rows=None):
        self._rows = rows or []

    def __iter__(self):
        return iter(self._rows)


class _SessionStub:
    def __init__(self):
        self.executed = []

    def execute(self, statement, params=None):
        self.executed.append((str(statement), params or {}))
        return _ResultStub()

    def commit(self):
        return None

    def rollback(self):
        return None


class _RouterStub:
    def ensure_tables_for_dimension(self, dimension):
        return None

    def get_knowledge_segment_table_name(self, dimension):
        return f"knowledge_segment_embedding_{dimension}"


class _EmbeddingsStub:
    def embed_query(self, text):
        return [0.1, 0.2]


def _service():
    svc = KnowledgeVectorService.__new__(KnowledgeVectorService)
    svc.db = SimpleNamespace(session=_SessionStub())
    svc.embeddings_service = SimpleNamespace(
        get_embeddings_for_model_id=lambda _model_id: (_EmbeddingsStub(), 1024)
    )
    svc.rerank_service = None
    svc._get_router = lambda: _RouterStub()
    return svc


def _base():
    return SimpleNamespace(id=uuid4(), embedding_model_id=uuid4(), knowledge_scope="user_content")


class TestVectorSearchFilters:
    def test_partition_filter_adds_where_clause(self):
        svc = _service()
        svc.search(_base(), "q", top_k=3, partition_id=uuid4())

        sql, params = svc.db.session.executed[-1]
        assert "kd.partition_id = :partition_id" in sql
        assert "partition_id" in params

    def test_media_type_filter_adds_where_clause(self):
        svc = _service()
        svc.search(_base(), "q", top_k=3, media_types=["video"])

        sql, params = svc.db.session.executed[-1]
        assert "kd.media_type" in sql
        assert "ANY(:media_types)" in sql
        assert params["media_types"] == ["video"]

    def test_document_ids_filter_adds_where_clause(self):
        svc = _service()
        doc_ids = [uuid4(), uuid4()]
        svc.search(_base(), "q", top_k=3, document_ids=doc_ids)

        sql, params = svc.db.session.executed[-1]
        assert "kd.id" in sql
        assert "ANY(:document_ids)" in sql
        assert params["document_ids"] == [str(x) for x in doc_ids]

    def test_no_optional_filter_keeps_sql_minimal(self):
        svc = _service()
        svc.search(_base(), "q", top_k=3)

        sql, _params = svc.db.session.executed[-1]
        assert "partition_id" not in sql
        assert "media_type" not in sql

    def test_score_threshold_is_applied_in_sql(self):
        """分数阈值必须在 SQL 侧过滤，避免先 LIMIT 取走再截断导致召回不足。"""
        svc = _service()
        svc.search(_base(), "q", top_k=3, score_threshold=0.5)

        sql, params = svc.db.session.executed[-1]
        assert "score" in sql
        assert params["score_threshold"] == 0.5

    def test_empty_media_types_is_treated_as_no_filter(self):
        svc = _service()
        svc.search(_base(), "q", top_k=3, media_types=[])

        sql, _params = svc.db.session.executed[-1]
        assert "media_type" not in sql

    def test_empty_document_ids_is_treated_as_no_filter(self):
        svc = _service()
        svc.search(_base(), "q", top_k=3, document_ids=[])

        sql, _params = svc.db.session.executed[-1]
        assert "document_ids" not in sql

    def test_scope_filter_still_works_with_new_filters(self):
        svc = _service()
        svc.search(
            _base(), "q", top_k=3,
            knowledge_scope="user_content",
            media_types=["image"],
            score_threshold=0.2,
        )

        sql, params = svc.db.session.executed[-1]
        assert "kb.knowledge_scope = :scope" in sql
        assert "ANY(:media_types)" in sql
        assert "score_threshold" in params

    def test_existing_behaviour_preserved_when_only_scope_passed(self):
        svc = _service()
        svc.search(_base(), "q", top_k=5, knowledge_scope="user_content")

        sql, params = svc.db.session.executed[-1]
        assert "knowledge_segment_embedding_1024" in sql
        assert params["limit"] == 5
