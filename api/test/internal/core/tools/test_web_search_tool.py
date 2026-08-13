import json
import sys
import types

from internal.core.tools.builtin_tools.providers.web_tools.web_search import (
    WebSearchTool,
    _normalize_tavily,
)


def test_normalize_tavily():
    items = [
        {"title": "T", "url": "https://x.com", "content": "snippet"},
        {"title": "T2", "url": "https://y.com", "snippet": "s2"},
    ]
    normalized = _normalize_tavily(items)
    assert normalized[0]["url"] == "https://x.com"
    assert normalized[0]["snippet"] == "snippet"
    assert normalized[1]["snippet"] == "s2"


def test_web_search_uses_tavily(monkeypatch):
    monkeypatch.setenv("TAVILY_API_KEY", "tvly-test")
    captured = {}

    class _FakeResp:
        def raise_for_status(self):
            pass

        def json(self):
            return {
                "results": [
                    {"title": "结果", "url": "https://example.com", "content": "摘要"}
                ]
            }

    def _fake_post(url, json=None, timeout=None):
        captured["url"] = url
        captured["json"] = json
        return _FakeResp()

    import requests

    monkeypatch.setattr(
        requests,
        "post",
        _fake_post,
    )

    result = json.loads(WebSearchTool()._run(query="Python", max_results=3))

    assert result["ok"] is True
    assert result["results"][0]["title"] == "结果"
    assert captured["json"]["query"] == "Python"
    assert captured["json"]["max_results"] == 3


def test_web_search_falls_back_to_duckduckgo(monkeypatch):
    monkeypatch.delenv("TAVILY_API_KEY", raising=False)
    monkeypatch.delenv("SERPAPI_API_KEY", raising=False)

    class _FakeDDGS:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def text(self, query, max_results=5):
            return [
                {"title": "DDG", "href": "https://ddg.example.com", "body": "摘要"}
            ]

    fake_ddgs = types.ModuleType("ddgs")
    fake_ddgs.DDGS = _FakeDDGS
    monkeypatch.setitem(sys.modules, "ddgs", fake_ddgs)

    result = json.loads(WebSearchTool()._run(query="hello"))

    assert result["ok"] is True
    assert result["results"][0]["title"] == "DDG"


def test_web_search_returns_error_when_all_providers_fail(monkeypatch):
    monkeypatch.delenv("TAVILY_API_KEY", raising=False)
    monkeypatch.delenv("SERPAPI_API_KEY", raising=False)
    fake_ddgs = types.ModuleType("ddgs")
    fake_ddgs.DDGS = lambda: (_ for _ in ()).throw(RuntimeError("down"))
    monkeypatch.setitem(sys.modules, "ddgs", fake_ddgs)

    result = json.loads(WebSearchTool()._run(query="hello"))
    assert result["ok"] is False


def test_web_search_reports_zero_result(monkeypatch):
    monkeypatch.delenv("TAVILY_API_KEY", raising=False)
    monkeypatch.delenv("SERPAPI_API_KEY", raising=False)

    class _FakeDDGS:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def text(self, query, max_results=5):
            return []

    fake_ddgs = types.ModuleType("ddgs")
    fake_ddgs.DDGS = _FakeDDGS
    monkeypatch.setitem(sys.modules, "ddgs", fake_ddgs)

    result = json.loads(WebSearchTool()._run(query="不存在的词"))

    assert result["ok"] is True
    assert result["count"] == 0
    assert result["zero_result"] is True
    assert "更换关键词" in result["hint"]
