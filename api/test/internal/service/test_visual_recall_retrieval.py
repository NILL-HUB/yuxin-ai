"""视觉向量「读取侧」接入测试（自动补充召回）。

背景：P3 视觉向量此前**只写不读**——`video_visual_embedding` 有数据、
`VisualEmbeddingService.search_by_*` 有实现，但检索链路零调用点，
导致「以图搜图 / 文本跨模态召回画面」在运行时不可达（与 L2 同类断链）。

本测试锁定五件必须成立的事：
1. 视觉命中作为**并行补充召回**并入主检索结果；
2. 与文本召回**按 segment_id 去重**，同一帧不重复返回；
3. 库内无视觉向量时**不发起编码调用**（控成本）；
4. 视觉召回**受同一套过滤约束**（媒体类型 / 标签 / 分区 / 阈值），不得绕过；
5. 视觉编码失败**不影响**主检索结果（补充通道不得反噬主链路）。
"""
from types import SimpleNamespace
from uuid import uuid4

from langchain_core.documents import Document as LCDocument

from internal.service.retrieval_service import RetrievalFilter, RetrievalService


class _QueryStub:
    def __init__(self, results=None):
        self._results = results if results is not None else []

    def filter(self, *args, **_kw):
        return self

    def all(self):
        return self._results

    def update(self, *_a, **_kw):
        return 1


class _SessionStub:
    def __init__(self, bases, docs=None):
        self._bases = bases
        self._docs = docs if docs is not None else []

    def query(self, model, *_a, **_kw):
        name = getattr(model, "__name__", str(model))
        return _QueryStub(self._bases if name == "KnowledgeBase" else self._docs)


class _AutoCommit:
    def __enter__(self):
        return self

    def __exit__(self, *_exc):
        return False


class _VisualStub:
    """记录调用入参，便于断言过滤条件确实透传到视觉检索。"""

    def __init__(self, hits=None, has=True):
        self.hits = hits if hits is not None else []
        self._has = has
        self.has_calls = []
        self.search_calls = []

    def has_vectors(self, knowledge_base_ids):
        self.has_calls.append(list(knowledge_base_ids))
        return self._has

    def search_by_text(
        self, *, query, knowledge_base_id, limit=10,
        document_ids=None, partition_id=None, media_types=None,
    ):
        self.search_calls.append({
            "query": query,
            "knowledge_base_id": knowledge_base_id,
            "limit": limit,
            "document_ids": document_ids,
            "partition_id": partition_id,
            "media_types": media_types,
        })
        return self.hits


def _visual_hit(segment_id, score=0.9, content="画面：一只猫"):
    return {
        "segment_id": segment_id,
        "frame_url": "2026/09/15/frame.jpg",
        "scene_index": 0,
        "content": content,
        "score": score,
    }


def _service(bases, semantic_hits=None, visual=None, tag_service=None, docs=None):
    svc = RetrievalService.__new__(RetrievalService)
    svc.db = SimpleNamespace(
        session=_SessionStub(bases, docs), auto_commit=lambda: _AutoCommit()
    )
    svc.knowledge_vector_service = SimpleNamespace(search=lambda *a, **kw: semantic_hits or [])
    svc.rerank_service = None
    svc.jieba_service = SimpleNamespace(extract_keywords=lambda _t, _n: [])
    svc.knowledge_tag_service = tag_service
    svc.visual_embedding_service = visual
    return svc


def _base():
    return SimpleNamespace(id=uuid4(), knowledge_scope="user_content", enabled=True)


def _semantic_hit(segment_id, score=0.8, content="文本描述"):
    return {
        "segment_id": segment_id,
        "document_id": str(uuid4()),
        "knowledge_base_id": str(uuid4()),
        "content": content,
        "score": score,
    }


class TestVisualSupplementaryRecall:
    def test_visual_hits_are_merged_into_results(self):
        base = _base()
        visual = _VisualStub(hits=[_visual_hit("s-frame")])
        svc = _service([base], visual=visual)

        documents = svc.search_in_knowledge_base(
            [base.id], "画面里有猫", uuid4(), k=4,
            retrieval_strategy="semantic",
        )

        segment_ids = [d.metadata.get("segment_id") for d in documents]
        assert "s-frame" in segment_ids
        visual_doc = next(d for d in documents if d.metadata["segment_id"] == "s-frame")
        assert visual_doc.metadata["retrieval"] == "visual"
        assert visual_doc.metadata["frame_url"] == "2026/09/15/frame.jpg"
        assert visual_doc.page_content == "画面：一只猫"

    def test_dedupes_segments_already_returned_by_text_search(self):
        """帧片段本身也有文本描述，可能已被文本召回命中，不得重复返回。"""
        base = _base()
        visual = _VisualStub(hits=[_visual_hit("s1"), _visual_hit("s2")])
        svc = _service([base], semantic_hits=[_semantic_hit("s1")], visual=visual)

        documents = svc.search_in_knowledge_base(
            [base.id], "q", uuid4(), k=4, retrieval_strategy="semantic",
        )

        segment_ids = [d.metadata.get("segment_id") for d in documents]
        assert segment_ids.count("s1") == 1
        assert "s2" in segment_ids

    def test_skips_encoding_when_knowledge_base_has_no_visual_vectors(self):
        """没有视觉向量的库不得白跑一次编码调用（视觉编码按次计费）。"""
        base = _base()
        visual = _VisualStub(hits=[_visual_hit("s-frame")], has=False)
        svc = _service([base], visual=visual)

        svc.search_in_knowledge_base(
            [base.id], "q", uuid4(), k=4, retrieval_strategy="semantic",
        )

        assert visual.has_calls == [[base.id]]
        assert visual.search_calls == []

    def test_skips_when_media_types_excludes_video(self):
        """视觉向量只存在于视频帧；限定 media_types=image 时必须 fail closed。"""
        base = _base()
        visual = _VisualStub(hits=[_visual_hit("s-frame")])
        svc = _service([base], visual=visual)

        svc.search_in_knowledge_base(
            [base.id], "q", uuid4(), k=4, retrieval_strategy="semantic",
            retrieval_filter=RetrievalFilter(media_types=["image"]),
        )

        assert visual.has_calls == []
        assert visual.search_calls == []

    def test_visual_recall_inherits_tag_document_scope(self):
        """已按标签收窄范围时，视觉召回也必须落在同一批素材内，否则等于绕过过滤。"""
        base = _base()
        document_id = uuid4()
        tag_service = SimpleNamespace(document_ids_for_tags=lambda *_a, **_kw: [document_id])
        visual = _VisualStub(hits=[_visual_hit("s-frame")])
        svc = _service([base], visual=visual, tag_service=tag_service)

        svc.search_in_knowledge_base(
            [base.id], "q", uuid4(), k=4, retrieval_strategy="semantic",
            retrieval_filter=RetrievalFilter(tag_ids=[uuid4()]),
        )

        assert visual.search_calls[0]["document_ids"] == [document_id]

    def test_tag_filter_without_match_disables_visual_recall(self):
        """标签无命中属 fail closed：视觉召回同样不得执行。"""
        base = _base()
        tag_service = SimpleNamespace(document_ids_for_tags=lambda *_a, **_kw: [])
        visual = _VisualStub(hits=[_visual_hit("s-frame")])
        svc = _service([base], visual=visual, tag_service=tag_service)

        documents = svc.search_in_knowledge_base(
            [base.id], "q", uuid4(), k=4, retrieval_strategy="semantic",
            retrieval_filter=RetrievalFilter(tag_ids=[uuid4()]),
        )

        assert documents == []
        assert visual.search_calls == []

    def test_full_text_strategy_does_not_trigger_visual_recall(self):
        """全文检索是关键词路径，不应额外引入编码调用与语义召回。"""
        base = _base()
        visual = _VisualStub(hits=[_visual_hit("s-frame")])
        svc = _service([base], visual=visual)

        svc.search_in_knowledge_base(
            [base.id], "q", uuid4(), k=4, retrieval_strategy="full_text",
        )

        assert visual.has_calls == []
        assert visual.search_calls == []

    def test_visual_hit_below_score_threshold_is_dropped(self):
        base = _base()
        visual = _VisualStub(hits=[_visual_hit("s-frame", score=0.2)])
        svc = _service([base], visual=visual)

        documents = svc.search_in_knowledge_base(
            [base.id], "q", uuid4(), k=4, retrieval_strategy="semantic",
            retrieval_filter=RetrievalFilter(score_threshold=0.5),
        )

        assert documents == []

    def test_visual_failure_does_not_break_main_retrieval(self):
        """视觉是补充通道：它失败时主检索结果必须原样返回。"""
        base = _base()
        visual = _VisualStub(hits=[_visual_hit("s-frame")])
        visual.search_by_text = lambda **_kw: (_ for _ in ()).throw(RuntimeError("boom"))
        svc = _service([base], semantic_hits=[_semantic_hit("s1")], visual=visual)

        documents = svc.search_in_knowledge_base(
            [base.id], "q", uuid4(), k=4, retrieval_strategy="semantic",
        )

        assert [d.metadata.get("segment_id") for d in documents] == ["s1"]

    def test_missing_visual_service_is_tolerated(self):
        """未注入视觉服务（如未配置该能力）时检索必须照常工作。"""
        base = _base()
        svc = _service([base], semantic_hits=[_semantic_hit("s1")], visual=None)

        documents = svc.search_in_knowledge_base(
            [base.id], "q", uuid4(), k=4, retrieval_strategy="semantic",
        )

        assert [d.metadata.get("segment_id") for d in documents] == ["s1"]

    def test_visual_hits_do_not_exceed_k(self):
        base = _base()
        visual = _VisualStub(hits=[_visual_hit(f"s-frame-{i}") for i in range(10)])
        svc = _service([base], visual=visual)

        documents = svc.search_in_knowledge_base(
            [base.id], "q", uuid4(), k=3, retrieval_strategy="semantic",
        )

        assert len(documents) == 3


class TestHybridAlsoGetsVisualRecall:
    def test_hybrid_strategy_includes_visual_hits(self):
        base = _base()
        visual = _VisualStub(hits=[_visual_hit("s-frame")])
        svc = _service([base], visual=visual)

        documents = svc.search_in_knowledge_base(
            [base.id], "q", uuid4(), k=4, retrieval_strategy="hybrid",
        )

        assert "s-frame" in [d.metadata.get("segment_id") for d in documents]


class TestVisualRecallGuardIsNotVacuous:
    """直接覆盖 `_visual_recall_knowledge_base` 的护栏本身。

    公开路径上「标签无命中 → 空」由上游早返回兜住，这条护栏在内部是**防御层**；
    若只测公开路径，把它写成 `if not document_ids`（把空列表误判为「无过滤」）
    也不会有测试失败——那正是最危险的 fail-open。故此处方法级直接锁定。
    """

    def test_empty_document_scope_never_issues_encoding_call(self):
        base = _base()
        visual = _VisualStub(hits=[_visual_hit("s-frame")])
        svc = _service([base], visual=visual)

        documents = svc._visual_recall_knowledge_base(
            [base], "q", 4, None, [],
        )

        assert documents == []
        assert visual.has_calls == []
        assert visual.search_calls == []

    def test_none_document_scope_still_issues_recall(self):
        """None 表示「未按标签收窄」，不得与 [] 混为一谈。"""
        base = _base()
        visual = _VisualStub(hits=[_visual_hit("s-frame")])
        svc = _service([base], visual=visual)

        documents = svc._visual_recall_knowledge_base([base], "q", 4, None, None)

        assert [d.metadata["segment_id"] for d in documents] == ["s-frame"]
        assert visual.search_calls[0]["document_ids"] is None


class TestLayeredSearchKeepsFrameMetadata:
    """分层检索必须把帧地址透传给上游。

    设计稿 §4.1 要求取料结果「带缩略图 / 时间戳」；若 metadata 只保留
    retrieval/source，视觉召回命中的帧会丢失 frame_url，Agent 拿不到图，
    以图搜图的结果就只剩一段文字，等于白召回。
    """

    def test_frame_url_and_scene_index_survive_layering(self):
        base = _base()
        visual = _VisualStub(hits=[_visual_hit("s-frame")])
        svc = _service([base], visual=visual)

        results = svc.layered_search(
            account_id=uuid4(),
            query="画面里有猫",
            knowledge_base_ids=[base.id],
            retrieval_config={"retrieval_strategy": "semantic", "k": 4},
        )

        visual_result = next(r for r in results if r.segment_id == "s-frame")
        assert visual_result.metadata["frame_url"] == "2026/09/15/frame.jpg"
        assert visual_result.metadata["scene_index"] == 0
        assert visual_result.metadata["retrieval"] == "visual"


class TestDependencyInjectionResolves:
    """DI 图必须可解析。

    `RetrievalService` 新增了 `visual_embedding_service` 依赖；injector 对
    **抽象类型注解**（如 `Any`）会直接抛 `TypeError: Injecting Any is not supported`，
    且该错误只在真正构造服务时才暴露——历史上已因此让一批用例整体报错。
    此处用真实 injector 构造一次，把这类问题锁在单测里。
    """

    def test_retrieval_service_is_injectable(self):
        import os

        if not os.getenv("SQLALCHEMY_DATABASE_URI"):
            import pytest

            pytest.skip("未配置数据库连接，跳过 DI 图解析验证")

        from app.http.module import injector

        service = injector.get(RetrievalService)

        assert service is not None
        assert service.visual_embedding_service is not None
        assert service.knowledge_tag_service is not None
