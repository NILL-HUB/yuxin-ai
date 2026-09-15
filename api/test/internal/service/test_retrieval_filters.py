"""检索服务过滤透传测试。

重点覆盖两类风险：
1. 过滤条件必须真正下推到向量服务；
2. **标签无命中时必须 fail closed**，绝不能退化成"不过滤"（否则用户以为已收窄范围，实际召回全库）；
3. 混合检索的全文分支同样要受过滤约束，否则会绕过向量分支的过滤。
"""
from types import SimpleNamespace
from uuid import uuid4

from langchain_core.documents import Document as LCDocument

from internal.service.retrieval_service import RetrievalFilter, RetrievalService


class _QueryStub:
    def __init__(self, results=None):
        self._results = results if results is not None else []
        self.filters = []

    def filter(self, *args, **_kw):
        self.filters.append(args)
        return self

    def all(self):
        return self._results

    def update(self, *_a, **_kw):
        return 1


class _SessionStub:
    def __init__(self, bases, docs=None):
        self._bases = bases
        self._docs = docs if docs is not None else []
        self.queries = []

    def query(self, model, *_a, **_kw):
        name = getattr(model, "__name__", str(model))
        if name == "KnowledgeBase":
            stub = _QueryStub(self._bases)
        else:
            stub = _QueryStub(self._docs)
        self.queries.append((name, stub))
        return stub


class _AutoCommit:
    def __enter__(self):
        return self

    def __exit__(self, *_exc):
        return False


def _service(bases, semantic_hits=None, docs=None, tag_service=None):
    svc = RetrievalService.__new__(RetrievalService)
    svc.db = SimpleNamespace(
        session=_SessionStub(bases, docs), auto_commit=lambda: _AutoCommit()
    )
    captured = {}

    def _fake_search(kb, query, top_k=5, knowledge_scope=None, **kwargs):
        captured.update(kwargs)
        captured["knowledge_scope"] = knowledge_scope
        return semantic_hits or []

    svc.knowledge_vector_service = SimpleNamespace(search=_fake_search)
    svc.rerank_service = None
    svc.jieba_service = SimpleNamespace(extract_keywords=lambda _t, _n: [])
    svc.knowledge_tag_service = tag_service
    return svc, captured


def _base():
    return SimpleNamespace(id=uuid4(), knowledge_scope="user_content", enabled=True)


class TestRetrievalFilterPassthrough:
    def test_filters_reach_vector_service(self):
        base = _base()
        svc, captured = _service([base])
        partition_id = uuid4()

        svc.search_in_knowledge_base(
            [base.id], "q", uuid4(), k=3,
            retrieval_strategy="semantic",
            retrieval_filter=RetrievalFilter(
                partition_id=partition_id,
                media_types=["video"],
                score_threshold=0.4,
            ),
        )

        assert captured["partition_id"] == partition_id
        assert captured["media_types"] == ["video"]
        assert captured["score_threshold"] == 0.4

    def test_no_filter_means_no_extra_kwargs(self):
        base = _base()
        svc, captured = _service([base])

        svc.search_in_knowledge_base([base.id], "q", uuid4(), k=3, retrieval_strategy="semantic")

        assert captured.get("partition_id") is None
        assert captured.get("media_types") is None
        assert captured.get("score_threshold") is None
        assert captured.get("document_ids") is None


class TestTagFilterFailsClosed:
    def test_tag_filter_resolves_to_document_ids(self):
        base = _base()
        doc_id = uuid4()
        tag_svc = SimpleNamespace(
            document_ids_for_tags=lambda tag_ids, match_all: [doc_id]
        )
        svc, captured = _service([base], tag_service=tag_svc)

        svc.search_in_knowledge_base(
            [base.id], "q", uuid4(), k=3,
            retrieval_strategy="semantic",
            retrieval_filter=RetrievalFilter(tag_ids=[uuid4()]),
        )

        assert captured["document_ids"] == [doc_id]

    def test_tag_filter_with_no_match_returns_empty(self):
        """标签查不到任何素材时必须直接返回空，不得退化成不过滤。"""
        base = _base()
        tag_svc = SimpleNamespace(document_ids_for_tags=lambda tag_ids, match_all: [])
        svc, _captured = _service([base], tag_service=tag_svc)

        result = svc.search_in_knowledge_base(
            [base.id], "q", uuid4(), k=3,
            retrieval_strategy="semantic",
            retrieval_filter=RetrievalFilter(tag_ids=[uuid4()]),
        )

        assert result == []

    def test_empty_tag_ids_list_fails_closed(self):
        """tag_ids == [] 表示「有标签过滤但无命中」，必须返回空而非退化成不过滤。

        空列表 falsy，若实现里用真假值判断就会静默召回全库——
        这是本设计最危险的失效模式，必须有回归测试钉住。
        """
        base = _base()
        svc, captured = _service([base], tag_service=SimpleNamespace(
            document_ids_for_tags=lambda _ids, match_all: []
        ))

        result = svc.search_in_knowledge_base(
            [base.id], "q", uuid4(), k=3,
            retrieval_strategy="semantic",
            retrieval_filter=RetrievalFilter(tag_ids=[]),
        )

        assert result == []
        assert captured == {}, "fail closed 时不应发起任何检索"

    def test_match_all_flag_is_forwarded_to_tag_service(self):
        base = _base()
        seen = {}
        tag_svc = SimpleNamespace(
            document_ids_for_tags=lambda tag_ids, match_all: seen.update(match_all=match_all) or [uuid4()]
        )
        svc, _captured = _service([base], tag_service=tag_svc)

        svc.search_in_knowledge_base(
            [base.id], "q", uuid4(), k=3,
            retrieval_strategy="semantic",
            retrieval_filter=RetrievalFilter(tag_ids=[uuid4()], match_all_tags=True),
        )

        assert seen["match_all"] is True


class TestFullTextBranchRespectsFilters:
    def test_semantic_pushes_structural_filter_without_extra_query(self):
        """向量分支应把分区/媒体类型直接下推 SQL（命中 HNSW 索引），不额外查素材表。"""
        base = _base()
        svc, captured = _service([base])

        svc.search_in_knowledge_base(
            [base.id], "q", uuid4(), k=3,
            retrieval_strategy="semantic",
            retrieval_filter=RetrievalFilter(media_types=["video"]),
        )

        assert captured["media_types"] == ["video"]
        assert all(name != "KnowledgeDocument" for name, _ in svc.db.session.queries)

    def test_full_text_branch_receives_restricted_document_ids(self):
        """全文分支必须同样受受限素材约束，否则绕过过滤返回库内其他分区内容。"""
        base = _base()
        doc_id = uuid4()
        svc, _captured = _service([base])
        svc._resolve_structural_document_ids = lambda spec: [doc_id]
        seen = {}
        svc._full_text_search_knowledge_base = (
            lambda kb_ids, query, k, document_ids=None: seen.update(
                document_ids=document_ids
            ) or []
        )

        svc.search_in_knowledge_base(
            [base.id], "q", uuid4(), k=3,
            retrieval_strategy="full_text",
            retrieval_filter=RetrievalFilter(media_types=["video"]),
        )

        assert seen["document_ids"] == [doc_id]

    def test_full_text_returns_empty_when_structural_filter_matches_nothing(self):
        """结构化过滤无命中时同样 fail closed。"""
        base = _base()
        svc, _captured = _service([base])
        svc._resolve_structural_document_ids = lambda spec: []

        result = svc.search_in_knowledge_base(
            [base.id], "q", uuid4(), k=3,
            retrieval_strategy="full_text",
            retrieval_filter=RetrievalFilter(partition_id=uuid4()),
        )

        assert result == []

    def test_tag_and_structural_filters_intersect_for_full_text(self):
        """标签与分区同时存在时，全文分支必须取交集而非任一单边。"""
        base = _base()
        tag_doc, other_doc = uuid4(), uuid4()
        svc, _captured = _service([base])
        svc.knowledge_tag_service = SimpleNamespace(
            document_ids_for_tags=lambda _ids, match_all: [tag_doc, other_doc]
        )
        svc._resolve_structural_document_ids = lambda spec: [other_doc]
        seen = {}
        svc._full_text_search_knowledge_base = (
            lambda kb_ids, query, k, document_ids=None: seen.update(
                document_ids=document_ids
            ) or []
        )

        svc.search_in_knowledge_base(
            [base.id], "q", uuid4(), k=3,
            retrieval_strategy="full_text",
            retrieval_filter=RetrievalFilter(
                tag_ids=[uuid4()], partition_id=uuid4()
            ),
        )

        assert seen["document_ids"] == [other_doc]
