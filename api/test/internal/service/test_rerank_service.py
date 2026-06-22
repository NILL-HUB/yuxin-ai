from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from internal.service.rerank_service import RerankService


class _FakeResponse:
    def __init__(self, content):
        self.content = content


def _make_docs():
    return [
        {"content": "文档A内容", "score": 0.9, "segment_id": "s1"},
        {"content": "文档B内容", "score": 0.1, "segment_id": "s2"},
    ]


def _build_service_with_llm(invoke_return=None, invoke_side_effect=None):
    mock_llm = Mock()
    if invoke_side_effect is not None:
        mock_llm.invoke.side_effect = invoke_side_effect
    else:
        mock_llm.invoke.return_value = invoke_return
    mock_lms = Mock()
    mock_lms.get_cheap_chat_model.return_value = mock_llm
    return RerankService(language_model_service=mock_lms)


class TestRerankService:
    def test_rerank_empty_documents_returns_empty_list(self, monkeypatch):
        monkeypatch.delenv("COHERE_API_KEY", raising=False)
        service = RerankService(language_model_service=Mock())

        assert service.rerank("查询", [], top_n=5) == []

    def test_rerank_single_document_returns_directly(self, monkeypatch):
        monkeypatch.delenv("COHERE_API_KEY", raising=False)
        service = RerankService(language_model_service=Mock())
        doc = {"content": "唯一文档", "score": 0.5}

        result = service.rerank("查询", [doc], top_n=5)

        assert result == [doc]

    def test_rerank_llm_scoring_should_sort_by_llm_score(self, monkeypatch):
        monkeypatch.delenv("COHERE_API_KEY", raising=False)
        service = _build_service_with_llm(
            invoke_return=_FakeResponse('[{"index": 0, "score": 3}, {"index": 1, "score": 9}]'),
        )

        result = service.rerank("查询", _make_docs(), top_n=5)

        assert len(result) == 2
        assert result[0]["content"] == "文档B内容"
        assert result[0]["rerank_score"] == 9.0
        assert result[1]["content"] == "文档A内容"
        assert result[1]["rerank_score"] == 3.0

    def test_rerank_falls_back_to_original_score_when_llm_fails(self, monkeypatch):
        monkeypatch.delenv("COHERE_API_KEY", raising=False)
        service = _build_service_with_llm(invoke_side_effect=RuntimeError("LLM down"))

        result = service.rerank("查询", _make_docs(), top_n=5)

        assert len(result) == 2
        assert result[0]["content"] == "文档A内容"
        assert result[0]["score"] == 0.9
        assert result[1]["content"] == "文档B内容"
        assert result[1]["score"] == 0.1

    def test_rerank_top_n_truncation(self, monkeypatch):
        monkeypatch.delenv("COHERE_API_KEY", raising=False)
        docs = [
            {"content": f"doc{i}", "score": 0.1 * i}
            for i in range(4)
        ]
        service = _build_service_with_llm(
            invoke_return=_FakeResponse(
                '[{"index": 0, "score": 1}, {"index": 1, "score": 2}, '
                '{"index": 2, "score": 3}, {"index": 3, "score": 4}]'
            ),
        )

        result = service.rerank("查询", docs, top_n=2)

        assert len(result) == 2
        assert result[0]["content"] == "doc3"
        assert result[0]["rerank_score"] == 4.0
        assert result[1]["content"] == "doc2"
        assert result[1]["rerank_score"] == 3.0

    def test_rerank_documents_preserves_metadata_and_scores(self, monkeypatch):
        monkeypatch.delenv("COHERE_API_KEY", raising=False)
        from langchain_core.documents import Document as LCDocument

        service = _build_service_with_llm(
            invoke_return=_FakeResponse('[{"index": 0, "score": 2}, {"index": 1, "score": 9}]'),
        )
        docs = [
            LCDocument(page_content="文档A", metadata={"score": 0.9, "segment_id": "s1"}),
            LCDocument(page_content="文档B", metadata={"score": 0.1, "segment_id": "s2"}),
        ]

        result = service.rerank_documents("查询", docs, top_n=5)

        assert len(result) == 2
        assert result[0].page_content == "文档B"
        assert result[0].metadata["score"] == 9.0
        assert result[0].metadata["segment_id"] == "s2"
        assert result[1].page_content == "文档A"
        assert result[1].metadata["score"] == 2.0
