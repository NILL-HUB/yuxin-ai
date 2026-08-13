"""视觉分析工具。

对齐 Hermes `vision_tools.py::vision_analyze_tool`：接收图片 URL/data URI，
用平台的视觉模型返回描述、OCR、目标检测等分析结果。

安全约束：抓取图片走 SSRF 防护，仅 http/https，禁止内网/本地地址。
"""

from __future__ import annotations

import base64
import ipaddress
import json
import logging
import re
import socket
import urllib.request
from typing import Any
from urllib.parse import urlparse

from langchain_core.tools import BaseTool
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


def _is_safe_image_url(url: str) -> tuple[bool, str]:
    try:
        parsed = urlparse(url)
    except ValueError:
        return False, "URL 无法解析"
    if parsed.scheme not in {"http", "https"}:
        return False, "仅支持 http/https"
    host = (parsed.hostname or "").lower()
    if not host or host in {"localhost", "127.0.0.1", "0.0.0.0", "::1"} or host.endswith(".local"):
        return False, "禁止访问本地地址"
    try:
        ips = {item[4][0] for item in socket.getaddrinfo(host, None)}
    except OSError:
        return False, "域名无法解析"
    for ip in ips:
        try:
            if ipaddress.ip_address(ip).is_private or ipaddress.ip_address(ip).is_loopback:
                return False, "禁止访问内网地址"
        except ValueError:
            continue
    return True, ""


def _resolve_image_data_uri(value: str) -> str:
    """返回可传给模型的 data URI；支持 data URI 或 http(s) URL。"""
    normalized = str(value or "").strip()
    if normalized.startswith("data:image/"):
        return normalized
    safe, reason = _is_safe_image_url(normalized)
    if not safe:
        raise ValueError(reason)
    with urllib.request.urlopen(normalized, timeout=20) as resp:
        raw = resp.read(8 * 1024 * 1024 + 1)
    if len(raw) > 8 * 1024 * 1024:
        raise ValueError("图片超过大小限制")
    mime = (resp.headers.get("Content-Type") or "image/jpeg").split(";")[0].strip()
    if not mime.startswith("image/"):
        mime = "image/jpeg"
    return f"data:{mime};base64,{base64.b64encode(raw).decode('ascii')}"


def _invoke_vision_model(data_uri: str, prompt: str) -> str:
    from internal.service.language_model_service import LanguageModelService

    llm = LanguageModelService.get_feature_model("vision_analyze")
    if llm is None:
        raise RuntimeError("未配置视觉分析模型")
    content = [
        {"type": "text", "text": prompt},
        {"type": "image_url", "image_url": {"url": data_uri}},
    ]
    from langchain_core.messages import HumanMessage

    response = llm.invoke([HumanMessage(content=content)])
    text = getattr(response, "content", "")
    if isinstance(text, list):
        text = "\n".join(
            str(item.get("text", ""))
            for item in text
            if isinstance(item, dict) and item.get("text")
        )
    return str(text or "").strip()


class VisionAnalyzeInput(BaseModel):
    image: str = Field(..., description="图片 URL 或 data:image/...;base64,.... 格式")
    prompt: str = Field(
        default="请详细描述这张图片的内容，包括主体、背景、文字和可观察到的细节。",
        description="分析要求，如“识别图中文字”“检测有哪些物体”",
    )


class VisionAnalyzeTool(BaseTool):
    name: str = "vision_analyze"
    description: str = (
        "分析图片：支持图片 URL 或 data URI，返回模型对图片的描述/OCR/物体检测结果。"
        "用于识别截图内容、检查设计稿、阅读图片文字等场景。"
    )
    args_schema: type[BaseModel] = VisionAnalyzeInput

    def _run(self, image: str, prompt: str = "", **kwargs: Any) -> str:
        try:
            data_uri = _resolve_image_data_uri(image)
            normalized_prompt = str(prompt or "").strip() or "请详细描述这张图片的内容。"
            text = _invoke_vision_model(data_uri, normalized_prompt)
            return json.dumps({"ok": True, "analysis": text}, ensure_ascii=False)
        except Exception as exc:
            logger.warning("视觉分析失败", exc_info=True)
            return json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False)

    async def _arun(self, image: str, prompt: str = "", **kwargs: Any) -> str:
        return self._run(image=image, prompt=prompt, **kwargs)


def vision_analyze(**kwargs: Any) -> BaseTool:
    return VisionAnalyzeTool()
