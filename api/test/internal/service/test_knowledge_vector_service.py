from types import SimpleNamespace
from uuid import uuid4

from langchain_core.documents import Document as LCDocument

from internal.service.knowledge_vector_service import KnowledgeVectorService


class _VectorStoreStub:
    def __init__(self):
        self.add_documents_calls = []
        self.search_results = []

    def add_documents(self, *, documents, ids):
        self.add_documents_calls.append((documents, ids))
        return ids

    def similarity_search_with_relevance_scores(self, *, query, k, filters):
        return self.search_results


class _CollectionDataStub:
    def __init__(self):
        self.deleted_ids = []

    def delete_by_id(self, node_id):
        self.deleted_ids.append(node_id)


class _CollectionStub:
    def __init__(self):
        self.data = _CollectionDataStub()


def _build_service(monkeypatch, vector_store=None, collection=None):
    service = KnowledgeVectorService.__new__(KnowledgeVectorService)
    vs = vector_store or _VectorStoreStub()
    col = collection or _CollectionStub()
    monkeypatch.setattr(type(service), "vector_store", property(lambda _self: vs))
    monkeypatch.setattr(type(service), "collection", property(lambda _self: col))
    return service


def _make_segment(segment_id=None, content="知识片段内容", enabled=True):
    return SimpleNamespace(
        id=segment_id or uuid4(),
        content=content,
        enabled=enabled,
        knowledge_document_id=uuid4(),
    )


def _make_knowledge_base(base_id=None, scope="user_content"):
    return SimpleNamespace(
        id=base_id or uuid4(),
        knowledge_scope=scope,
        owner_account_id=uuid4(),
    )


class TestKnowledgeVectorService:
    def test_collection_name_is_isolated_from_dataset(self):
        assert KnowledgeVectorService.COLLECTION_NAME == "KnowledgeBase"

    def test_index_segment_should_write_vector_with_metadata(self, monkeypatch):
        vector_store = _VectorStoreStub()
        service = _build_service(monkeypatch, vector_store=vector_store)

        segment = _make_segment(content="测试内容")
        knowledge_base = _make_knowledge_base()

        node_id = service.index_segment(segment, knowledge_base)

        assert node_id == str(segment.id)
        assert len(vector_store.add_documents_calls) == 1
        documents, ids = vector_store.add_documents_calls[0]
        assert ids == [str(segment.id)]
        assert documents[0].page_content == "测试内容"
        metadata = documents[0].metadata
        assert metadata["segment_id"] == str(segment.id)
        assert metadata["knowledge_base_id"] == str(knowledge_base.id)
        assert metadata["knowledge_scope"] == "user_content"
        assert metadata["document_id"] == str(segment.knowledge_document_id)
        assert metadata["document_enabled"] is True

    def test_remove_segment_should_delete_node_by_segment_id(self, monkeypatch):
        collection = _CollectionStub()
        service = _build_service(monkeypatch, collection=collection)

        segment = _make_segment()

        service.remove_segment(segment)

        assert collection.data.deleted_ids == [str(segment.id)]

    def test_remove_segment_should_swallow_deletion_failure(self, monkeypatch):
        collection = _CollectionStub()
        collection.data.delete_by_id = lambda _node_id: (_ for _ in ()).throw(RuntimeError("delete-failed"))
        service = _build_service(monkeypatch, collection=collection)

        segment = _make_segment()

        service.remove_segment(segment)

    def test_search_should_return_content_score_and_segment_id(self, monkeypatch):
        vector_store = _VectorStoreStub()
        seg_id = uuid4()
        doc_id = uuid4()
        kb_id = uuid4()
        vector_store.search_results = [
            (
                LCDocument(
                    page_content="命中内容",
                    metadata={
                        "segment_id": str(seg_id),
                        "document_id": str(doc_id),
                        "knowledge_base_id": str(kb_id),
                    },
                ),
                0.88,
            )
        ]
        service = _build_service(monkeypatch, vector_store=vector_store)
        knowledge_base = _make_knowledge_base(base_id=kb_id)

        results = service.search(knowledge_base, "查询", top_k=5)

        assert len(results) == 1
        hit = results[0]
        assert hit["content"] == "命中内容"
        assert hit["score"] == 0.88
        assert hit["segment_id"] == str(seg_id)
        assert hit["document_id"] == str(doc_id)
        assert hit["knowledge_base_id"] == str(kb_id)

    def test_search_should_return_empty_when_no_hits(self, monkeypatch):
        vector_store = _VectorStoreStub()
        vector_store.search_results = []
        service = _build_service(monkeypatch, vector_store=vector_store)

        results = service.search(_make_knowledge_base(), "查询", top_k=5)

        assert results == []
