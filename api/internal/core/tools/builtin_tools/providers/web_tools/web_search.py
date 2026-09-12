"""统一网页搜索工具（对齐 Hermes `web_tools.py` 多 provider 插件式设计）。

按可用凭证自动选择 provider：Tavily → Exa → SerpAPI → Brave → DuckDuckGo（ddgs）。
零结果时返回结构化提示（zero_result），全部 provider 不可用时返回错误而非崩溃。
"""

from __future__ import annotations

import json
import logging
import os
from typing import Any, Callable

from langchain_core.tools import BaseTool
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


# ─── 结果规范化 ────────────────────────────────────────────────────────────────

def _normalize_tavily(items: list[dict]) -> list[dict]:
    return [
        {
            "title": str(item.get("title") or ""),
            "url": str(item.get("url") or ""),
            "snippet": str(item.get("content") or item.get("snippet") or ""),
        }
        for item in items or []
        if isinstance(item, dict)
    ]


def _normalize_serpapi(items: list[dict]) -> list[dict]:
    return [
        {
            "title": str(item.get("title") or ""),
            "url": str(item.get("link") or ""),
            "snippet": str(item.get("snippet") or item.get("content") or ""),
        }
        for item in items or []
        if isinstance(item, dict)
    ]


def _normalize_brave(items: list[dict]) -> list[dict]:
    return [
        {
            "title": str(item.get("title") or ""),
            "url": str(item.get("url") or ""),
            "snippet": str(item.get("description") or ""),
        }
        for item in items or []
        if isinstance(item, dict)
    ]


def _normalize_exa(items: list[dict]) -> list[dict]:
    return [
        {
            "title": str(item.get("title") or ""),
            "url": str(item.get("url") or ""),
            "snippet": str(item.get("text") or item.get("snippet") or ""),
        }
        for item in items or []
        if isinstance(item, dict)
    ]


# ─── 各 provider 实现（返回 None 表示本 provider 不可用/失败，供降级）───────────

def _tavily_search(query: str, max_results: int) -> list[dict] | None:
    api_key = str(os.getenv("TAVILY_API_KEY") or "").strip()
    if not api_key:
        return None
    try:
        import requests

        resp = requests.post(
            "https://api.tavily.com/search",
            json={"api_key": api_key, "query": query, "max_results": max_results},
            timeout=20,
        )
        resp.raise_for_status()
        return _normalize_tavily(resp.json().get("results") or [])
    except Exception as exc:
        logger.warning("Tavily 搜索失败，尝试下一个 provider: %s", exc)
        return None


def _exa_search(query: str, max_results: int) -> list[dict] | None:
    api_key = str(os.getenv("EXA_API_KEY") or "").strip()
    if not api_key:
        return None
    try:
        import requests

        resp = requests.post(
            "https://api.exa.ai/search",
            headers={"x-api-key": api_key, "Content-Type": "application/json"},
            json={"query": query, "numResults": max_results},
            timeout=20,
        )
        resp.raise_for_status()
        return _normalize_exa(resp.json().get("results") or [])
    except Exception as exc:
        logger.warning("Exa 搜索失败，尝试下一个 provider: %s", exc)
        return None


def _serpapi_search(query: str, max_results: int) -> list[dict] | None:
    api_key = str(os.getenv("SERPAPI_API_KEY") or "").strip()
    if not api_key:
        return None
    try:
        import requests

        resp = requests.get(
            "https://serpapi.com/search",
            params={"engine": "google", "q": query, "api_key": api_key, "num": max_results},
            timeout=20,
        )
        resp.raise_for_status()
        organic = resp.json().get("organic_results") or []
        return _normalize_serpapi(organic[:max_results])
    except Exception as exc:
        logger.warning("SerpAPI 搜索失败，尝试下一个 provider: %s", exc)
        return None


def _brave_search(query: str, max_results: int) -> list[dict] | None:
    api_key = str(os.getenv("BRAVE_SEARCH_API_KEY") or "").strip()
    if not api_key:
        return None
    try:
        import requests

        resp = requests.get(
            "https://api.search.brave.com/res/v1/web/search",
            headers={"X-Subscription-Token": api_key, "Accept": "application/json"},
            params={"q": query, "count": max_results},
            timeout=20,
        )
        resp.raise_for_status()
        return _normalize_brave(resp.json().get("web", {}).get("results") or [])
    except Exception as exc:
        logger.warning("Brave 搜索失败，尝试下一个 provider: %s", exc)
        return None


def _duckduckgo_search(query: str, max_results: int) -> list[dict] | None:
    try:
        from ddgs import DDGS

        with DDGS() as ddgs:
            results = list(ddgs.text(query, max_results=max_results))
        return [
            {
                "title": str(item.get("title") or ""),
                "url": str(item.get("href") or item.get("url") or ""),
                "snippet": str(item.get("body") or item.get("snippet") or ""),
            }
            for item in results or []
            if isinstance(item, dict)
        ]
    except Exception as exc:
        logger.warning("DuckDuckGo 搜索失败: %s", exc)
        return None


# provider 优先级队列：按可用凭证自动选择，天然支持降级
_SEARCH_PROVIDERS: list[tuple[str, Callable[[str, int], list[dict] | None]]] = [
    ("tavily", _tavily_search),
    ("exa", _exa_search),
    ("serpapi", _serpapi_search),
    ("brave", _brave_search),
    ("ddgs", _duckduckgo_search),
]


class WebSearchInput(BaseModel):
    query: str = Field(..., description="搜索查询语句")
    max_results: int = Field(default=5, ge=1, le=10, description="返回结果数量，默认 5")


class WebSearchTool(BaseTool):
    name: str = "web_search"
    description: str = (
        "统一网页搜索工具：按 Tavily → Exa → SerpAPI → Brave → DuckDuckGo 顺序"
        "自动选择可用提供商，返回标题、链接、摘要列表。用于时事、资料、事实核实等搜索需求。"
    )
    args_schema: type[BaseModel] = WebSearchInput

    def _run(self, query: str, max_results: int = 5, **kwargs: Any) -> str:
        normalized = str(query or "").strip()
        if not normalized:
            return json.dumps({"ok": False, "error": "搜索词不能为空"}, ensure_ascii=False)
        limit = max(1, min(int(max_results or 5), 10))
        for provider_name, provider_fn in _SEARCH_PROVIDERS:
            results = provider_fn(normalized, limit)
            if results is None:
                continue  # 本 provider 不可用/失败，降级
            if not results:
                return json.dumps(
                    {
                        "ok": True,
                        "query": normalized,
                        "provider": provider_name,
                        "results": [],
                        "count": 0,
                        "zero_result": True,
                        "hint": "未找到匹配结果，请尝试更换关键词、缩小范围或补充上下文后重试。",
                    },
                    ensure_ascii=False,
                )
            return json.dumps(
                {
                    "ok": True,
                    "query": normalized,
                    "provider": provider_name,
                    "results": results,
                    "count": len(results),
                },
                ensure_ascii=False,
            )
        return json.dumps(
            {"ok": False, "error": "所有搜索提供商均不可用或失败"},
            ensure_ascii=False,
        )

    async def _arun(self, query: str, max_results: int = 5, **kwargs: Any) -> str:
        return self._run(query=query, max_results=max_results, **kwargs)


def web_search(**kwargs: Any) -> BaseTool:
    return WebSearchTool()