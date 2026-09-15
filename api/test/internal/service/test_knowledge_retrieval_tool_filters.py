"""search_knowledge_base 工具过滤参数测试。"""
from types import SimpleNamespace
from uuid import uuid4

from internal.service.retrieval_service import RetrievalFilter, RetrievalService


class _AppStub:
    class app_context:
        def __enter__(self):
            return self

        def __exit__(self, *_exc):
            return False


def _service(captured):
    svc = RetrievalService.__new__(RetrievalService)

    def _fake_layered_search(
        account_id, query, knowledge_base_ids,
        retrieval_config=None, top_k_per_layer=None, retrieval_filter=None,
    ):
        captured["retrieval_config"] = retrieval_config or {}
        captured["retrieval_filter"] = retrieval_filter
        return []

    svc.layered_search = _fake_layered_search
    return svc


class TestRetrievalToolFilters:
    def test_tool_schema_exposes_filter_fields(self):
        svc = _service({})
        tool = svc.create_knowledge_retrieval_tool(_AppStub(), [uuid4()], uuid4())

        props = tool.args_schema.model_json_schema()["properties"]
        for field in ("query", "partition_id", "media_types", "tags", "score_threshold"):
            assert field in props, f"工具入参缺少 {field}"

    def test_tool_builds_retrieval_filter_from_args(self):
        captured = {}
        svc = _service(captured)
        tool = svc.create_knowledge_retrieval_tool(_AppStub(), [uuid4()], uuid4())
        partition_id = uuid4()

        tool.invoke({
            "query": "找几段讲卖点的视频",
            "partition_id": str(partition_id),
            "media_types": ["video"],
            "tags": ["产品A"],
            "score_threshold": 0.3,
        })

        spec = captured["retrieval_filter"]
        assert isinstance(spec, RetrievalFilter)
        assert str(spec.partition_id) == str(partition_id)
        assert spec.media_types == ["video"]
        assert spec.score_threshold == 0.3

    def test_tool_tags_are_resolved_to_tag_ids(self):
        captured = {}
        svc = _service(captured)
        tag_id = uuid4()
        svc.knowledge_tag_service = SimpleNamespace(
            resolve_tag_ids_by_names=lambda names: [tag_id]
        )
        tool = svc.create_knowledge_retrieval_tool(_AppStub(), [uuid4()], uuid4())

        tool.invoke({"query": "q", "tags": ["产品A"]})

        assert captured["retrieval_filter"].tag_ids == [tag_id]

    def test_tool_accepts_omitted_optional_filters(self):
        captured = {}
        svc = _service(captured)
        tool = svc.create_knowledge_retrieval_tool(_AppStub(), [uuid4()], uuid4())

        tool.invoke({"query": "随便搜搜"})

        spec = captured["retrieval_filter"]
        assert spec is None or (
            spec.partition_id is None
            and not spec.media_types
            and not spec.tag_ids
            and spec.score_threshold is None
        )

    def test_tool_ignores_blank_tag_names(self):
        captured = {}
        svc = _service(captured)
        svc.knowledge_tag_service = SimpleNamespace(
            resolve_tag_ids_by_names=lambda names: []
        )
        tool = svc.create_knowledge_retrieval_tool(_AppStub(), [uuid4()], uuid4())

        tool.invoke({"query": "q", "tags": ["  ", ""]})

        spec = captured["retrieval_filter"]
        assert spec is None or not spec.tag_ids

    def test_tool_fails_closed_when_tag_names_match_nothing(self):
        """标签名一个都解析不到时必须 fail closed。

        真实生效点在检索层：filter.tag_ids == [] 会让检索直接返回空
        （绝不能因空列表是 falsy 就退化成「不过滤」而召回全库）。
        因此这里断言两件事：
        1. tag_ids 必须保留为空列表语义，而不是被丢弃成 None；
        2. 调用方拿到的是「没有检索到」提示，而不是全库内容。
        """
        captured = {}
        svc = _service(captured)
        svc.knowledge_tag_service = SimpleNamespace(
            resolve_tag_ids_by_names=lambda names: []
        )
        tool = svc.create_knowledge_retrieval_tool(_AppStub(), [uuid4()], uuid4())

        result = tool.invoke({"query": "q", "tags": ["根本不存在的标签"]})

        spec = captured.get("retrieval_filter")
        assert spec is not None, "带标签名的检索必须带上过滤条件，不能整体丢弃"
        assert spec.tag_ids == [], "解析不到的标签必须保留为空列表以触发 fail closed"
        assert "没有" in result

    def test_tool_passes_retrieval_config_unchanged(self):
        captured = {}
        svc = _service(captured)
        tool = svc.create_knowledge_retrieval_tool(
            _AppStub(), [uuid4()], uuid4(), retrieval_strategy="semantic", k=7
        )

        tool.invoke({"query": "q"})

        assert captured["retrieval_config"]["retrieval_strategy"] == "semantic"
        assert captured["retrieval_config"]["k"] == 7


class TestLayeredSearchAcceptsFilter:
    def test_filter_reaches_search_in_knowledge_base(self):
        svc = RetrievalService.__new__(RetrievalService)
        base = SimpleNamespace(id=uuid4(), knowledge_scope="user_content", enabled=True)
        seen = {}

        class _Query:
            def filter(self, *_a, **_kw):
                return self

            def all(self):
                return [base]

        svc.db = SimpleNamespace(session=SimpleNamespace(query=lambda *_a, **_kw: _Query()))

        def _fake_search(**kwargs):
            seen.update(kwargs)
            return []

        svc.search_in_knowledge_base = _fake_search
        spec = RetrievalFilter(media_types=["video"])

        svc.layered_search(uuid4(), "q", [base.id], retrieval_filter=spec)

        assert seen["retrieval_filter"] is spec
