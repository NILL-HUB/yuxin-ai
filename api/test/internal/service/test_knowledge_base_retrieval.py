from types import SimpleNamespace
from uuid import uuid4


class TestKnowledgeBaseRetrieval:
    def test_search_in_knowledge_base_should_return_matching_segments(self, monkeypatch):
        from internal.service.retrieval_service import RetrievalService

        service = RetrievalService.__new__(RetrievalService)

        kb_id = uuid4()
        account_id = uuid4()
        seg_id = uuid4()
        doc_id = uuid4()

        segment = SimpleNamespace(
            id=seg_id,
            knowledge_base_id=kb_id,
            knowledge_document_id=doc_id,
            content="飞书文档同步的内容片段",
            position=1,
        )

        class _QueryStub:
            def __init__(self):
                self._filters = []

            def filter(self, *args, **kwargs):
                self._filters.append((args, kwargs))
                return self

            def order_by(self, *args, **kwargs):
                return self

            def limit(self, n):
                return self

            def all(self):
                return [segment]

        class _SessionStub:
            def query(self, model):
                return _QueryStub()

        class _DbStub:
            session = _SessionStub()

        service.db = _DbStub()

        documents = service.search_in_knowledge_base(
            knowledge_base_ids=[kb_id],
            query="飞书",
            account_id=account_id,
            k=4,
        )

        assert len(documents) == 1
        assert documents[0].page_content == "飞书文档同步的内容片段"
        assert documents[0].metadata["source"] == "knowledge_base"
        assert documents[0].metadata["knowledge_base_id"] == str(kb_id)

    def test_search_in_knowledge_base_should_return_empty_for_no_match(self, monkeypatch):
        from internal.service.retrieval_service import RetrievalService

        service = RetrievalService.__new__(RetrievalService)

        class _QueryStub:
            def filter(self, *args, **kwargs):
                return self

            def order_by(self, *args, **kwargs):
                return self

            def limit(self, n):
                return self

            def all(self):
                return []

        class _SessionStub:
            def query(self, model):
                return _QueryStub()

        class _DbStub:
            session = _SessionStub()

        service.db = _DbStub()

        documents = service.search_in_knowledge_base(
            knowledge_base_ids=[uuid4()],
            query="不存在的内容",
            account_id=uuid4(),
            k=4,
        )

        assert documents == []
