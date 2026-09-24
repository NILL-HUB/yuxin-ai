"""X（Twitter）搜索工具（对齐 Hermes `x_search_tool`）。

通过 xAI Responses API 的内置 ``x_search`` 模型工具搜索 X 公开帖子/话题，
只读发现，不做发帖/回复/点赞等账户操作。需要配置 ``XAI_API_KEY``。

设计对齐点（来自 Hermes x_search_tool）：
- 支持 handles 限定/排除、YYYY-MM-DD 日期范围、图片/视频理解；
- 日期范围客户端校验，避免无效请求；
- 返回带引用（citations）的回答；无引用时标记 degraded 供调用方判断。
"""

from __future__ import annotations

import json
import logging
import time
from datetime import date, datetime, timezone
from typing import Any

from langchain_core.tools import BaseTool
from pydantic import BaseModel, Field

from internal.service.tool_credential_resolver import get_tool_credential

logger = logging.getLogger(__name__)

_DEFAULT_XAI_BASE_URL = "https://api.x.ai/v1"
_DEFAULT_X_SEARCH_MODEL = "grok-4.5"
_MAX_HANDLES = 10


def _xai_api_key() -> str:
    return get_tool_credential("XAI_API_KEY")


def _validate_date_range(from_date: str, to_date: str) -> None:
    today = date.today()

    def _parse(value: str) -> date | None:
        if not value.strip():
            return None
        try:
            return datetime.strptime(value.strip(), "%Y-%m-%d").date()
        except ValueError:
            raise ValueError("日期必须为 YYYY-MM-DD 格式")

    f = _parse(from_date)
    t = _parse(to_date)
    if f and t and f > t:
        raise ValueError("from_date 不能晚于 to_date")
    if f and f > today:
        raise ValueError("from_date 不能晚于今天")


class XSearchInput(BaseModel):
    query: str = Field(..., description="要在 X 上搜索的内容")
    allowed_x_handles: list[str] | None = Field(
        default=None, description="可选：仅在这些 X 账号内搜索（最多 10 个）"
    )
    excluded_x_handles: list[str] | None = Field(
        default=None, description="可选：排除这些 X 账号（最多 10 个）"
    )
    from_date: str = Field(default="", description="可选的起始日期 YYYY-MM-DD")
    to_date: str = Field(default="", description="可选的结束日期 YYYY-MM-DD")


class XSearchTool(BaseTool):
    name: str = "x_search"
    description: str = (
        "搜索 X（Twitter）公开帖子、账号与话题，使用 xAI 的 X Search 工具。"
        "只读发现：适合了解当前讨论、舆论与公开声明；不做发帖/回复等账户操作。"
        "需要配置 XAI_API_KEY。"
    )
    args_schema: type[BaseModel] = XSearchInput

    def _run(
        self,
        query: str,
        allowed_x_handles: list[str] | None = None,
        excluded_x_handles: list[str] | None = None,
        from_date: str = "",
        to_date: str = "",
        **kwargs: Any,
    ) -> str:
        normalized_query = str(query or "").strip()
        if not normalized_query:
            return json.dumps({"ok": False, "error": "query 不能为空"}, ensure_ascii=False)
        api_key = _xai_api_key()
        if not api_key:
            return json.dumps(
                {"ok": False, "error": "未配置 XAI_API_KEY，无法使用 x_search"},
                ensure_ascii=False,
            )

        allowed = [str(h).strip() for h in (allowed_x_handles or []) if str(h).strip()][: _MAX_HANDLES]
        excluded = [str(h).strip() for h in (excluded_x_handles or []) if str(h).strip()][: _MAX_HANDLES]
        if allowed and excluded:
            return json.dumps(
                {"ok": False, "error": "allowed_x_handles 与 excluded_x_handles 不能同时使用"},
                ensure_ascii=False,
            )
        try:
            _validate_date_range(from_date, to_date)
        except ValueError as exc:
            return json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False)

        tool_def: dict[str, Any] = {"type": "x_search"}
        if allowed:
            tool_def["allowed_x_handles"] = allowed
        if excluded:
            tool_def["excluded_x_handles"] = excluded
        if from_date.strip():
            tool_def["from_date"] = from_date.strip()
        if to_date.strip():
            tool_def["to_date"] = to_date.strip()

        payload: dict[str, Any] = {
            "model": _DEFAULT_X_SEARCH_MODEL,
            "input": [{"role": "user", "content": normalized_query}],
            "tools": [tool_def],
            "store": False,
        }

        try:
            import requests as _requests

            response = _requests.post(
                f"{_DEFAULT_XAI_BASE_URL}/responses",
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                },
                json=payload,
                timeout=180,
            )
            response.raise_for_status()
            data = response.json()
        except Exception as exc:  # noqa: BLE001
            logger.warning("X 搜索请求失败: %s", exc, exc_info=True)
            return json.dumps({"ok": False, "error": f"X 搜索失败: {exc}"}, ensure_ascii=False)

        answer = self._extract_response_text(data)
        citations = self._extract_inline_citations(data)
        degraded = bool(citations) is False and bool(answer)
        return json.dumps(
            {
                "ok": True,
                "answer": answer,
                "citations": citations,
                "degraded": degraded,
                "degraded_reason": (
                    "xAI 未返回引用来源，结果可能来自模型自身知识而非 X 索引"
                    if degraded
                    else ""
                ),
            },
            ensure_ascii=False,
        )

    @staticmethod
    def _extract_response_text(payload: dict[str, Any]) -> str:
        output_text = str(payload.get("output_text") or "").strip()
        if output_text:
            return output_text
        parts: list[str] = []
        for item in payload.get("output", []) or []:
            if item.get("type") != "message":
                continue
            for content in item.get("content", []) or []:
                ctype = content.get("type")
                if ctype in {"output_text", "text"}:
                    text = str(content.get("text") or "").strip()
                    if text:
                        parts.append(text)
        return "\n\n".join(parts).strip()

    @staticmethod
    def _extract_inline_citations(payload: dict[str, Any]) -> list[dict[str, Any]]:
        citations: list[dict[str, Any]] = []
        for item in payload.get("output", []) or []:
            if item.get("type") != "message":
                continue
            for content in item.get("content", []) or []:
                for annotation in content.get("annotations", []) or []:
                    if annotation.get("type") != "url_citation":
                        continue
                    citations.append(
                        {
                            "url": annotation.get("url", ""),
                            "title": annotation.get("title", ""),
                            "start_index": annotation.get("start_index"),
                            "end_index": annotation.get("end_index"),
                        }
                    )
        return citations

    async def _arun(
        self,
        query: str,
        allowed_x_handles: list[str] | None = None,
        excluded_x_handles: list[str] | None = None,
        from_date: str = "",
        to_date: str = "",
        **kwargs: Any,
    ) -> str:
        return self._run(
            query=query,
            allowed_x_handles=allowed_x_handles,
            excluded_x_handles=excluded_x_handles,
            from_date=from_date,
            to_date=to_date,
            **kwargs,
        )


def x_search(**kwargs: Any) -> BaseTool:
    return XSearchTool()