"""通用网页提取工具（对齐 Hermes `web_tools.py::web_extract_tool`）。

支持一次提取最多 5 个 URL，返回干净可读的 Markdown/文本；不做 LLM 摘要（后端返回即用，快）。
对齐 Hermes 的设计要点：
- URL 批量归一化：接受字符串或含 url/href 的对象；
- SSRF 防护：仅 http/https、拒绝内网/保留地址；
- 大小限制：超限抛错且不灌满上下文；
- 内联 base64 图片替换为 [IMAGE: alt] 占位符（保留真实图片链接）；
- 超长页面 head+tail 截断并附 footer 提示。
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
_DEFAULT_CHAR_LIMIT = 15000
_MAX_URLS = 5

_BASE64_IMAGE_RE = re.compile(
    r"!\[(?P<alt>[^\]]*)\]\(\s*data:image/[^;]+;base64,[A-Za-z0-9+/=\s]+\)"
)
_PAREN_B64_RE = re.compile(r"\(\s*data:image/[^;]+;base64,[A-Za-z0-9+/=\s]+\)")
_BARE_B64_RE = re.compile(r"data:image/[^;]+;base64,[A-Za-z0-9+/=]+")


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


def convert_base64_images_to_links(text: str) -> str:
    """把内联 base64 图片替换为可读占位符，避免 token 炸弹。

    ``![alt](data:image/png;base64,AAAA...)`` -> ``[IMAGE: alt]``
    裸 data URI 与普通 base64 图片 -> ``[IMAGE]``；真实 http/https 图片链接保留。
    """
    out = _BASE64_IMAGE_RE.sub(
        lambda m: (f"[IMAGE: {m.group('alt').strip()}]" if (m.group("alt") or "").strip() else "[IMAGE]"),
        text,
    )
    out = _PAREN_B64_RE.sub("[IMAGE]", out)
    out = _BARE_B64_RE.sub("[IMAGE]", out)
    return out


def _truncate_with_footer(content: str, url: str, char_limit: int) -> tuple[str, bool]:
    """超长页面 head+tail 截断并附 footer；页面 ≤ char_limit 时原样返回。"""
    if len(content) <= char_limit:
        return content, False
    head_budget = int(char_limit * 0.75)
    tail_budget = char_limit - head_budget
    head = content[:head_budget]
    tail = content[-tail_budget:]
    nl = head.rfind("\n")
    if nl > head_budget * 0.5:
        head = head[:nl]
    nl = tail.find("\n")
    if 0 <= nl < tail_budget * 0.5:
        tail = tail[nl + 1:]
    total = len(content)
    footer = [
        "",
        "─" * 8 + " [TRUNCATED] " + "─" * 8,
        f"Showing {len(head):,} chars (head) + {len(tail):,} chars (tail) "
        f"of {total:,} total clean characters. Source: {url}",
        "─" * 29,
    ]
    model_text = head + "\n\n[... middle omitted — see footer ...]\n\n" + tail
    model_text += "\n" + "\n".join(footer)
    return model_text, True


def _extract_url_item(value: Any) -> str | None:
    """从模型传入的提取项中取 URL：接受字符串或含 url/href 字段的字典。"""
    if isinstance(value, dict):
        value = value.get("url") or value.get("href")
    if not isinstance(value, str):
        return None
    value = value.strip()
    return value or None


def _fetch_readable(url: str) -> tuple[bool, str]:
    """抓取单个 URL 并转可读文本。返回 (ok, 内容或错误)。"""
    try:
        request = urllib.request.Request(
            url,
            headers={
                "User-Agent": "Mozilla/5.0 (Yujianwo WebExtract/1.0)",
                "Accept": "text/html,application/xhtml+xml",
            },
        )
        with urllib.request.urlopen(request, timeout=_DEFAULT_TIMEOUT) as resp:
            raw = resp.read(_MAX_BYTES + 1)
        if len(raw) > _MAX_BYTES:
            return False, "页面超过大小限制"
        content_type = ""
        try:
            content_type = str(resp.headers.get("Content-Type", ""))
        except Exception:
            pass
        if ("html" not in content_type) and content_type:
            # 非 HTML（PDF/JSON/纯文本等）只回显前 4k
            text = raw.decode("utf-8", errors="replace")
            return True, text[:4000]
        html = raw.decode("utf-8", errors="replace")
        return True, _html_to_readable_text(html, url)
    except urllib.error.HTTPError as exc:
        return False, f"HTTP {exc.code}: {exc.reason}"
    except Exception as exc:
        return False, str(exc)


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
    urls: list[str] = Field(
        ...,
        description="要读取的网页 URL 列表（最多 5 个），或单个 URL 字符串",
    )
    char_limit: int | None = Field(
        default=None,
        ge=2000,
        description="每个页面的字符预算（默认 15000）。超过则 head+tail 截断并附 footer。",
    )


class WebExtractTool(BaseTool):
    name: str = "web_extract"
    description: str = (
        "读取指定网页并返回可读正文文本，用于资料调研、内容总结、引用核实。"
        "支持一次提取最多 5 个 URL；内联图片以 [IMAGE: alt] 占位展示；"
        "PDF 链接也可直接传入。超长页面返回 head+tail 窗口并在 footer 标注已截断。"
    )
    args_schema: type[BaseModel] = WebExtractInput

    def _run(
        self,
        urls: Any = None,
        url: str | None = None,
        char_limit: int | None = None,
        **kwargs: Any,
    ) -> str:
        single_mode = (url is not None) or isinstance(urls, str)
        if url is not None:
            urls = [url]
        if isinstance(urls, str):
            raw_urls = [urls]
        elif isinstance(urls, list):
            raw_urls = urls[: _MAX_URLS]
        else:
            return json.dumps({"ok": False, "error": "urls 必须是 URL 字符串或列表"}, ensure_ascii=False)

        limit = char_limit if char_limit is not None else _DEFAULT_CHAR_LIMIT
        try:
            limit = max(2000, min(int(limit), 500_000))
        except (TypeError, ValueError):
            limit = _DEFAULT_CHAR_LIMIT

        results: list[dict[str, Any]] = []
        for raw in raw_urls:
            item_url = _extract_url_item(raw)
            if not item_url:
                results.append({"url": "", "title": "", "content": "", "error": "无效的 URL 项"})
                continue
            safe, reason = _is_safe_url(item_url)
            if not safe:
                results.append({"url": item_url, "title": "", "content": "", "error": reason})
                continue
            ok, payload = _fetch_readable(item_url)
            if not ok:
                results.append({"url": item_url, "title": "", "content": "", "error": payload})
                continue
            clean = convert_base64_images_to_links(payload)
            model_text, _truncated = _truncate_with_footer(clean, item_url, limit)
            results.append(
                {"url": item_url, "title": "", "content": model_text, "error": None}
            )

        if single_mode and len(results) == 1:
            r = results[0]
            if r.get("error"):
                return json.dumps({"ok": False, "error": r["error"]}, ensure_ascii=False)
            return json.dumps(
                {"ok": True, "url": r["url"], "text": r["content"], "char_count": len(r["content"])},
                ensure_ascii=False,
            )
        return json.dumps({"ok": True, "results": results}, ensure_ascii=False)

    async def _arun(
        self,
        urls: Any = None,
        url: str | None = None,
        char_limit: int | None = None,
        **kwargs: Any,
    ) -> str:
        return self._run(urls=urls, url=url, char_limit=char_limit, **kwargs)


def web_extract(**kwargs: Any) -> BaseTool:
    return WebExtractTool()