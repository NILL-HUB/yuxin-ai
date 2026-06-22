from contextlib import contextmanager
from types import SimpleNamespace
from uuid import uuid4

from langchain_core.documents import Document as LCDocument

from internal.model import KnowledgeBase, KnowledgeSegment
from internal.service.retrieval_service import RetrievalService


@contextmanager
def _auto_commit():
    yield


class _KnowledgeBaseQuery:
    def __init__(self, bases):
        self._bases = bases

    def filter(self, *_args, **_kwargs):
        return self

    def all(self):
        return self._bases


class _SegmentQuery:
    def __init__(self, segments):
        self._segments = segments
        self.update_payloads = []

    def filter(self, *_args, **_kwargs):
        return self

    def all(self):
        return self._segments

    def update(self, payload):
        self.update_payloads.append(payload)
        return 1


class _Session:
    def __init__(self, bases=None, segments=None):
        self._kb_query = _KnowledgeBaseQuery(bases or [])
        self._seg_query = _SegmentQuery(segments or [])

    def query(self, model):
        if model is KnowledgeBase:
            return self._kb_query
        return self._seg_query


class _Db:
    def __init__(self, session):
        self.session = session

    def auto_commit(self):
        return _auto_commit()


def _build_service(bases=None, segments=None, semantic_hits=None, keywords=None):
    service = RetrievalService.__new__(RetrievalService)
    service.db = _Db(_Session(bases, segments))
    service.knowledge_vector_service = SimpleNamespace(
        search=lambda _kb, _query, top_k=5: semantic_hits or []
    )
    service.jieba_service = SimpleNamespace(
        extract_keywords=lambda _text, _n: keywords or []
    )
    return service


def _make_base(base_id, scope="user_content"):
    return SimpleNamespace(
        id=base_id,
        knowledge_scope=scope,
        owner_account_id=uuid4(),
        enabled=True,
    )


class TestKnowledgeBaseRetrieval:
    def test_hybrid_should_merge_semantic_and_full_text_and_dedup(self):
        kb_id = uuid4()
        account_id = uuid4()
        seg_id_1 = uuid4()
        seg_id_2 = uuid4()
        doc_id = uuid4()

        base = _make_base(kb_id)
        semantic_hits = [
            {
                "content": "语义命中的片段",
                "score": 0.9,
                "segment_id": str(seg_id_1),
                "document_id": str(doc_id),
                "knowledge_base_id": str(kb_id),
            }
        ]

        segment = SimpleNamespace(
            id=seg_id_2,
            knowledge_base_id=kb_id,
            knowledge_document_id=doc_id,
            content="关键词命中的片段",
            keywords=["飞书", "文档"],
        )

        service = _build_service(
            bases=[base],
            segments=[segment],
            semantic_hits=semantic_hits,
            keywords=["飞书", "同步"],
        )

        documents = service.search_in_knowledge_base(
            knowledge_base_ids=[kb_id],
            query="飞书文档同步",
            account_id=account_id,
            k=4,
        )

        segment_ids = {doc.metadata.get("segment_id") for doc in documents}
        assert str(seg_id_1) in segment_ids
        assert str(seg_id_2) in segment_ids
        assert all(doc.metadata["source"] == "knowledge_base" for doc in documents)
        assert service.db.session._seg_query.update_payloads

    def test_should_return_empty_when_no_knowledge_base_found(self):
        service = _build_service(bases=[])

        documents = service.search_in_knowledge_base(
            knowledge_base_ids=[uuid4()],
            query="不存在的内容",
            account_id=uuid4(),
            k=4,
        )

        assert documents == []

    def test_full_text_only_should_return_keyword_matched_segments(self):
        kb_id = uuid4()
        account_id = uuid4()
        seg_id = uuid4()
        doc_id = uuid4()

        base = _make_base(kb_id)
        segment = SimpleNamespace(
            id=seg_id,
            knowledge_base_id=kb_id,
            knowledge_document_id=doc_id,
            content="飞书文档同步的内容片段",
            keywords=["飞书", "文档"],
        )

        service = _build_service(
            bases=[base],
            segments=[segment],
            semantic_hits=[],
            keywords=["飞书"],
        )

        documents = service.search_in_knowledge_base(
            knowledge_base_ids=[kb_id],
            query="飞书",
            account_id=account_id,
            k=4,
            retrieval_strategy="full_text",
        )

        assert len(documents) == 1
        assert documents[0].page_content == "飞书文档同步的内容片段"
        assert documents[0].metadata["segment_id"] == str(seg_id)

    def test_semantic_only_should_return_vector_hits_sorted_by_score(self):
        kb_id = uuid4()
        account_id = uuid4()
        doc_id = uuid4()
        seg_high = uuid4()
        seg_low = uuid4()

        base = _make_base(kb_id)
        semantic_hits = [
            {
                "content": "低分片段",
                "score": 0.3,
                "segment_id": str(seg_low),
                "document_id": str(doc_id),
                "knowledge_base_id": str(kb_id),
            },
            {
                "content": "高分片段",
                "score": 0.9,
                "segment_id": str(seg_high),
                "document_id": str(doc_id),
                "knowledge_base_id": str(kb_id),
            },
        ]

        service = _build_service(
            bases=[base],
            segments=[],
            semantic_hits=semantic_hits,
            keywords=["飞书"],
        )

        documents = service.search_in_knowledge_base(
            knowledge_base_ids=[kb_id],
            query="查询",
            account_id=account_id,
            k=4,
            retrieval_strategy="semantic",
        )

        assert len(documents) == 2
        assert documents[0].metadata["score"] >= documents[1].metadata["score"]
        assert documents[0].page_content == "高分片段"
