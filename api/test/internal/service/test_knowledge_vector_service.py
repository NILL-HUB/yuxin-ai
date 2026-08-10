from types import SimpleNamespace
from uuid import uuid4

from internal.service.embedding_table_router import EmbeddingTableRouter
from internal.service.knowledge_vector_service import KnowledgeVectorService


class _EmbeddingsStub:
    def __init__(self, embedding=None):
        self.embedding = embedding if embedding is not None else [0.1, 0.2, 0.3]
        self.embed_query_calls = []

    def embed_query(self, text):
        self.embed_query_calls.append(text)
        return self.embedding


class _EmbeddingsServiceStub:
    def __init__(self, dimension=1024, embeddings=None):
        self.dimension = dimension
        self.embeddings = embeddings or _EmbeddingsStub()
        self.calls = []

    def get_embeddings_for_model_id(self, model_id):
        self.calls.append(model_id)
        return self.embeddings, self.dimension


class _RouterStub:
    def __init__(self, table_name="knowledge_segment_embedding_1024"):
        self.table_name = table_name
        self.ensured_dimensions = []

    def ensure_tables_for_dimension(self, dimension):
        self.ensured_dimensions.append(dimension)

    def get_knowledge_segment_table_name(self, dimension):
        return self.table_name


class _SessionStub:
    def __init__(self):
        self.execute_calls = []
        self.result_rows = []
        self.execute_error = None
        self.committed = 0
        self.rolled_back = 0

    def execute(self, stmt, params):
        if self.execute_error is not None:
            raise self.execute_error
        self.execute_calls.append((str(stmt), params))
        return self.result_rows

    def commit(self):
        self.committed += 1

    def rollback(self):
        self.rolled_back += 1


class _DbStub:
    def __init__(self):
        self.session = _SessionStub()


def _build_service(monkeypatch, db=None, embeddings_service=None, rerank_service=None):
    service = KnowledgeVectorService.__new__(KnowledgeVectorService)
    service.db = db or _DbStub()
    service.embeddings_service = embeddings_service or _EmbeddingsServiceStub()
    service.rerank_service = rerank_service
    monkeypatch.setattr(service, "_get_router", lambda: _RouterStub())
    return service


def _make_segment(segment_id=None, content="知识片段内容", enabled=True, knowledge_base=None):
    return SimpleNamespace(
        id=segment_id or uuid4(),
        content=content,
        enabled=enabled,
        knowledge_document_id=uuid4(),
        knowledge_base=knowledge_base,
    )


def _make_knowledge_base(base_id=None, scope="user_content"):
    return SimpleNamespace(
        id=base_id or uuid4(),
        knowledge_scope=scope,
        owner_account_id=uuid4(),
    )


class TestKnowledgeVectorService:
    def test_collection_name_is_isolated_from_dataset(self):
        assert EmbeddingTableRouter.get_knowledge_segment_table_name(1024) == "knowledge_segment_embedding_1024"
        assert EmbeddingTableRouter.get_knowledge_segment_table_name(1536) == "knowledge_segment_embedding_1536"
        assert EmbeddingTableRouter.get_knowledge_segment_table_name(1024) != EmbeddingTableRouter.get_knowledge_segment_table_name(1536)

    def test_index_segment_should_write_vector_with_metadata(self, monkeypatch):
        embeddings_service = _EmbeddingsServiceStub()
        db = _DbStub()
        service = _build_service(monkeypatch, db=db, embeddings_service=embeddings_service)

        segment = _make_segment(content="测试内容")
        knowledge_base = _make_knowledge_base()

        node_id = service.index_segment(segment, knowledge_base)

        assert node_id == str(segment.id)
        assert embeddings_service.embeddings.embed_query_calls == ["测试内容"]
        assert len(db.session.execute_calls) == 1
        sql, params = db.session.execute_calls[0]
        assert "INSERT INTO knowledge_segment_embedding_1024" in sql
        assert "ON CONFLICT (segment_id) DO UPDATE" in sql
        assert params["segment_id"] == str(segment.id)
        assert params["kb_id"] == str(knowledge_base.id)
        assert params["embedding"] == embeddings_service.embeddings.embedding
        assert db.session.committed == 1

    def test_remove_segment_should_delete_node_by_segment_id(self, monkeypatch):
        db = _DbStub()
        service = _build_service(monkeypatch, db=db)

        knowledge_base = _make_knowledge_base()
        segment = _make_segment(knowledge_base=knowledge_base)

        service.remove_segment(segment)

        assert len(db.session.execute_calls) == 1
        sql, params = db.session.execute_calls[0]
        assert "DELETE FROM knowledge_segment_embedding_1024" in sql
        assert params["segment_id"] == str(segment.id)
        assert db.session.committed == 1

    def test_remove_segment_should_swallow_deletion_failure(self, monkeypatch):
        db = _DbStub()
        db.session.execute_error = RuntimeError("delete-failed")
        service = _build_service(monkeypatch, db=db)

        knowledge_base = _make_knowledge_base()
        segment = _make_segment(knowledge_base=knowledge_base)

        service.remove_segment(segment)

        assert db.session.rolled_back == 1

    def test_search_should_return_content_score_and_segment_id(self, monkeypatch):
        db = _DbStub()
        seg_id = uuid4()
        doc_id = uuid4()
        kb_id = uuid4()
        db.session.result_rows = [
            SimpleNamespace(
                segment_id=seg_id,
                content="命中内容",
                knowledge_document_id=doc_id,
                score=0.88,
            )
        ]
        service = _build_service(monkeypatch, db=db)
        knowledge_base = _make_knowledge_base(base_id=kb_id)

        results = service.search(knowledge_base, "查询", top_k=5)

        assert len(results) == 1
        hit = results[0]
        assert hit["content"] == "命中内容"
        assert hit["score"] == 0.88
        assert hit["segment_id"] == str(seg_id)
        assert hit["document_id"] == str(doc_id)
        assert hit["knowledge_base_id"] == str(kb_id)

        assert len(db.session.execute_calls) == 1
        sql, params = db.session.execute_calls[0]
        assert "JOIN knowledge_segment ks" in sql
        assert params["kb_id"] == str(kb_id)
        assert params["limit"] == 5

    def test_search_should_return_empty_when_no_hits(self, monkeypatch):
        db = _DbStub()
        db.session.result_rows = []
        service = _build_service(monkeypatch, db=db)

        results = service.search(_make_knowledge_base(), "查询", top_k=5)

        assert results == []
