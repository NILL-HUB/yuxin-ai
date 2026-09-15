"""视觉编码服务测试：请求体格式 + 维度校验 + 降级 + 排序。

重点：Qwen3-VL-Embedding 的 embeddings 入参与 OpenAI 不兼容——
文本传裸字符串，图片传 {"image": ...}，混合传对象数组。
用 OpenAIEmbeddings 无法表达这些形态，会静默只编码文本。
"""
from types import SimpleNamespace
from uuid import uuid4

from internal.model.video_visual_embedding import VISUAL_EMBEDDING_DIMENSION
from internal.service.visual_embedding_service import VisualEmbeddingService, _cosine_similarity


class _ResponseStub:
    def __init__(self, payload, status_code=200):
        self._payload = payload
        self.status_code = status_code

    def json(self):
        return self._payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


def _vector():
    return [0.1] * VISUAL_EMBEDDING_DIMENSION


def _service(post_impl, creds=None):
    svc = VisualEmbeddingService.__new__(VisualEmbeddingService)
    svc.db = SimpleNamespace()
    svc._post = post_impl
    svc._credentials = lambda: creds if creds is not None else {
        "api_key": "k",
        "base_url": "https://api.siliconflow.cn/v1",
        "model": "Qwen/Qwen3-VL-Embedding-8B",
    }
    return svc


class TestVisualEmbeddingService:
    def test_embed_text_sends_plain_string_input(self):
        captured = {}

        def _post(url, json, headers, timeout):
            captured.update({"url": url, "json": json, "headers": headers})
            return _ResponseStub({"data": [{"embedding": _vector()}]})

        vector = _service(_post).embed_text("一只猫")

        assert captured["json"]["input"] == "一只猫"
        assert captured["url"].endswith("/embeddings")
        assert captured["json"]["dimensions"] == VISUAL_EMBEDDING_DIMENSION
        assert captured["json"]["model"] == "Qwen/Qwen3-VL-Embedding-8B"
        assert captured["headers"]["Authorization"] == "Bearer k"
        assert len(vector) == VISUAL_EMBEDDING_DIMENSION

    def test_embed_image_uses_image_object_input(self):
        """该模型的图片入参是 {"image": ...}，不是 OpenAI 的字符串数组。"""
        captured = {}

        def _post(url, json, headers, timeout):
            captured.update(json)
            return _ResponseStub({"data": [{"embedding": _vector()}]})

        _service(_post).embed_image("data:image/jpeg;base64,AAAA")

        assert captured["input"] == {"image": "data:image/jpeg;base64,AAAA"}

    def test_embed_mixed_uses_content_object_list(self):
        captured = {}

        def _post(url, json, headers, timeout):
            captured.update(json)
            return _ResponseStub({"data": [{"embedding": _vector()}]})

        _service(_post).embed_mixed("产品卖点", "data:image/jpeg;base64,AAAA")

        assert captured["input"] == [
            {"text": "产品卖点"},
            {"image": "data:image/jpeg;base64,AAAA"},
        ]

    def test_base_url_trailing_slash_is_normalised(self):
        captured = {}

        def _post(url, json, headers, timeout):
            captured.update({"url": url})
            return _ResponseStub({"data": [{"embedding": _vector()}]})

        svc = _service(_post, creds={
            "api_key": "k", "base_url": "https://api.siliconflow.cn/v1/", "model": "m",
        })
        svc.embed_text("x")

        assert "//embeddings" not in captured["url"]
        assert captured["url"].endswith("/v1/embeddings")

    def test_returns_empty_on_request_exception(self):
        def _post(*_a, **_kw):
            raise RuntimeError("boom")

        svc = _service(_post)
        assert svc.embed_text("x") == []
        assert svc.embed_image("data:image/jpeg;base64,AAAA") == []

    def test_returns_empty_when_api_key_missing(self):
        svc = _service(lambda *_a, **_kw: _ResponseStub({}),
                       creds={"api_key": "", "base_url": "u", "model": "m"})
        assert svc.embed_text("x") == []

    def test_returns_empty_when_model_missing(self):
        svc = _service(lambda *_a, **_kw: _ResponseStub({}),
                       creds={"api_key": "k", "base_url": "u", "model": ""})
        assert svc.embed_text("x") == []

    def test_returns_empty_when_dimension_mismatch(self):
        """维度不符必须视为失败——否则会写入错误的向量破坏索引。"""
        svc = _service(lambda *_a, **_kw: _ResponseStub({"data": [{"embedding": [0.1, 0.2]}]}))
        assert svc.embed_text("x") == []

    def test_returns_empty_when_data_missing(self):
        svc = _service(lambda *_a, **_kw: _ResponseStub({}))
        assert svc.embed_text("x") == []

    def test_returns_empty_on_http_error_status(self):
        svc = _service(lambda *_a, **_kw: _ResponseStub({}, status_code=500))
        assert svc.embed_text("x") == []


class TestVisualSearch:
    def test_search_by_image_ranks_by_cosine_similarity(self):
        svc = _service(lambda *_a, **_kw: _ResponseStub({}))
        svc.embed_image = lambda _uri: [1.0, 0.0]
        svc._fetch_rows = lambda **_kw: [
            {"segment_id": "s1", "frame_url": "f1", "embedding": [1.0, 0.0]},
            {"segment_id": "s2", "frame_url": "f2", "embedding": [0.0, 1.0]},
        ]

        results = svc.search_by_image(
            image_uri="data:image/jpeg;base64,AAAA", knowledge_base_id=uuid4()
        )

        assert [r["segment_id"] for r in results] == ["s1", "s2"]
        assert results[0]["score"] > results[1]["score"]

    def test_search_by_text_uses_same_space(self):
        """文本与图片共享语义空间，文本 query 可直接召回视觉向量。"""
        svc = _service(lambda *_a, **_kw: _ResponseStub({}))
        svc.embed_text = lambda _q: [1.0, 0.0]
        svc._fetch_rows = lambda **_kw: [
            {"segment_id": "s1", "frame_url": "f1", "embedding": [1.0, 0.0]},
        ]

        results = svc.search_by_text(query="画面里有猫", knowledge_base_id=uuid4())

        assert results[0]["segment_id"] == "s1"

    def test_search_returns_empty_when_query_embedding_fails(self):
        svc = _service(lambda *_a, **_kw: _ResponseStub({}))
        svc.embed_image = lambda _uri: []
        assert svc.search_by_image(image_uri="x", knowledge_base_id=uuid4()) == []

    def test_search_respects_limit(self):
        svc = _service(lambda *_a, **_kw: _ResponseStub({}))
        svc.embed_text = lambda _q: [1.0, 0.0]
        svc._fetch_rows = lambda **_kw: [
            {"segment_id": f"s{i}", "frame_url": f"f{i}", "embedding": [1.0, 0.0]}
            for i in range(10)
        ]

        assert len(svc.search_by_text(query="q", knowledge_base_id=uuid4(), limit=3)) == 3


class TestCosineSimilarity:
    def test_identical_vectors_score_one(self):
        assert _cosine_similarity([1.0, 0.0], [1.0, 0.0]) == 1.0

    def test_orthogonal_vectors_score_zero(self):
        assert _cosine_similarity([1.0, 0.0], [0.0, 1.0]) == 0.0

    def test_zero_vector_returns_zero_without_dividing_by_zero(self):
        assert _cosine_similarity([0.0, 0.0], [1.0, 0.0]) == 0.0

    def test_dimension_mismatch_returns_zero(self):
        assert _cosine_similarity([1.0], [1.0, 0.0]) == 0.0
