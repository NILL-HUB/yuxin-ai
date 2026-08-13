"""统一网页搜索工具。

对齐 Hermes `web_search_tool` 的“多个 provider 可插拔”设计：按可用凭证
依次尝试 Tavily、SerpAPI、DuckDuckGo，返回统一结构的搜索结果。
"""

from __future__ import annotations

import json
import logging
import os
from typing import Any

from langchain_core.tools import BaseTool
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


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
        return [
            {
                "title": str(item.get("title") or ""),
                "url": str(item.get("link") or ""),
                "snippet": str(item.get("snippet") or ""),
            }
            for item in organic[:max_results]
            if isinstance(item, dict)
        ]
    except Exception as exc:
        logger.warning("SerpAPI 搜索失败，尝试下一个 provider: %s", exc)
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


class WebSearchInput(BaseModel):
    query: str = Field(..., description="搜索查询语句")
    max_results: int = Field(default=5, ge=1, le=10, description="返回结果数量，默认 5")


class WebSearchTool(BaseTool):
    name: str = "web_search"
    description: str = (
        "统一网页搜索工具：按 Tavily → SerpAPI → DuckDuckGo 顺序自动选择可用提供商，"
        "返回标题、链接、摘要列表。用于时事、资料、事实核实等搜索需求。"
    )
    args_schema: type[BaseModel] = WebSearchInput

    def _run(self, query: str, max_results: int = 5, **kwargs: Any) -> str:
        normalized = str(query or "").strip()
        if not normalized:
            return json.dumps({"ok": False, "error": "搜索词不能为空"}, ensure_ascii=False)
        limit = max(1, min(int(max_results or 5), 10))
        results = _tavily_search(normalized, limit) or _serpapi_search(normalized, limit) or _duckduckgo_search(normalized, limit)
        if results is None:
            return json.dumps(
                {"ok": False, "error": "所有搜索提供商均不可用或失败"},
                ensure_ascii=False,
            )
        if not results:
            return json.dumps(
                {
                    "ok": True,
                    "query": normalized,
                    "results": [],
                    "count": 0,
                    "zero_result": True,
                    "hint": "未找到匹配结果，请尝试更换关键词、缩小范围或补充上下文后重试。",
                },
                ensure_ascii=False,
            )
        return json.dumps(
            {"ok": True, "query": normalized, "results": results, "count": len(results)},
            ensure_ascii=False,
        )

    async def _arun(self, query: str, max_results: int = 5, **kwargs: Any) -> str:
        return self._run(query=query, max_results=max_results, **kwargs)


def web_search(**kwargs: Any) -> BaseTool:
    return WebSearchTool()
