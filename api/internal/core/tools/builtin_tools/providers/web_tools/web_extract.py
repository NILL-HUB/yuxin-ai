"""通用网页提取工具。

对齐 Hermes `tools/web_tools.py::web_extract_tool` 的“读网页内容”能力：
抓取 URL 并把 HTML 转成可读文本/Markdown，供 Agent 研究、总结使用。

安全约束：
- 仅允许 http/https；
- 阻止常见内网/保留地址（SSRF 防护）；
- 限制响应大小与超时，避免把超长页面灌进上下文。
"""

from __future__ import annotations

import ipaddress
import json
import logging
import re
import socket
import urllib.error
import urllib.request
from typing import Any
from urllib.parse import urlparse

from langchain_core.tools import BaseTool
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

_BLOCKED_HOSTS = {"localhost", "127.0.0.1", "0.0.0.0", "::1"}
_MAX_BYTES = 2 * 1024 * 1024
_DEFAULT_TIMEOUT = 20


def _is_safe_url(url: str) -> tuple[bool, str]:
    """SSRF 防护：仅 http/https，且主机不能是内网/保留地址。"""
    try:
        parsed = urlparse(url)
    except ValueError:
        return False, "URL 无法解析"
    if parsed.scheme not in {"http", "https"}:
        return False, "仅支持 http/https"
    host = (parsed.hostname or "").lower()
    if not host:
        return False, "URL 缺少主机名"
    if host in _BLOCKED_HOSTS or host.endswith(".local"):
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


def _html_to_readable_text(html: str, base_url: str) -> str:
    """把 HTML 转为可读文本，保留链接与标题，去掉脚本/样式。"""
    try:
        from bs4 import BeautifulSoup

        soup = BeautifulSoup(html, "html.parser")
    except Exception:
        text = re.sub(r"<[^>]+>", " ", html)
        return re.sub(r"\s+", " ", text).strip()[:8000]

    for tag in soup(["script", "style", "noscript", "svg", "iframe"]):
        tag.decompose()
    for tag in soup.find_all(["h1", "h2", "h3", "h4"]):
        tag.append("\n")
    for tag in soup.find_all(["p", "li", "tr"]):
        tag.append("\n")
    for tag in soup.find_all("a"):
        href = tag.get("href")
        if href and href.startswith(("http://", "https://")):
            tag.append(f" ({href})")

    lines = []
    for line in soup.get_text("\n").splitlines():
        stripped = line.strip()
        if stripped:
            lines.append(stripped)
    text = "\n".join(lines)
    if not text:
        text = str(soup.get_text(" ", strip=True))[:4000]
    return text[:12000]


class WebExtractInput(BaseModel):
    url: str = Field(..., description="要读取的网页完整 URL，例如 https://example.com/article")


class WebExtractTool(BaseTool):
    name: str = "web_extract"
    description: str = (
        "读取指定网页并返回可读正文文本，用于资料调研、内容总结、引用核实。"
        "返回纯文本（保留主要标题与段落），不要拿它下载二进制文件。"
    )
    args_schema: type[BaseModel] = WebExtractInput

    def _run(self, url: str, **kwargs: Any) -> str:
        safe, reason = _is_safe_url(url)
        if not safe:
            return json.dumps({"ok": False, "error": reason}, ensure_ascii=False)
        try:
            request = urllib.request.Request(
                url,
                headers={
                    "User-Agent": "Mozilla/5.0 (YuxinAI WebExtract/1.0)",
                    "Accept": "text/html,application/xhtml+xml",
                },
            )
            with urllib.request.urlopen(request, timeout=_DEFAULT_TIMEOUT) as resp:
                raw = resp.read(_MAX_BYTES + 1)
            if len(raw) > _MAX_BYTES:
                return json.dumps({"ok": False, "error": "页面超过大小限制"}, ensure_ascii=False)
            content_type = ""
            try:
                content_type = str(resp.headers.get("Content-Type", ""))
            except Exception:
                pass
            if "html" not in content_type and not content_type:
                try:
                    text = raw.decode("utf-8", errors="replace")
                except Exception:
                    text = ""
                return json.dumps({"ok": True, "text": text[:4000]}, ensure_ascii=False)
            html = raw.decode("utf-8", errors="replace")
            text = _html_to_readable_text(html, url)
            return json.dumps(
                {"ok": True, "url": url, "text": text, "char_count": len(text)},
                ensure_ascii=False,
            )
        except urllib.error.HTTPError as exc:
            return json.dumps({"ok": False, "error": f"HTTP {exc.code}: {exc.reason}"}, ensure_ascii=False)
        except Exception as exc:
            return json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False)

    async def _arun(self, url: str, **kwargs: Any) -> str:
        return self._run(url=url, **kwargs)


def web_extract(**kwargs: Any) -> BaseTool:
    return WebExtractTool()
