"""Agent 输出文本的伪工具调用剥离。

背景：当模型被 system prompt 告知"必须调用某工具"，但运行时并未真正绑定工具
（bind_tools 未生效）时，模型会把工具调用当作普通文本吐出来，例如：

    <search_knowledge_base><query>xxx</query></search_knowledge_base>

这类文本会经流式分片原样泄漏给用户。本模块提供**唯一权威**的剥离逻辑：
- `strip_pseudo_tool_call_markup(text, tool_names)`：整段文本一次性剥离。
- `PseudoToolCallStreamFilter`：流式分片过滤，采用"前缀回撤缓冲"避免跨 chunk 标签泄漏。

识别规则（保守，避免误删正常正文）：
- 仅识别"标签名属于已知工具名 / 通用工具调用标签"的 `<tag>...</tag>` 块；
- 普通 `<div>`、数学 `<` 等不在已知集合内，原样保留。
"""
from __future__ import annotations

import re

# 通用工具调用标签（与 artifact_policy_entity 的 XML 工具标签保持同源）
from internal.core.agent.entities.artifact_policy_entity import (
    _XML_TOOL_CALL_TAG_NAMES as _GENERIC_TOOL_TAGS,
)

_OPEN_TAG_RE = re.compile(r"^<([A-Za-z0-9_]+)(\s[^>]*)?>")
_SELF_CLOSING_RE = re.compile(r"^<([A-Za-z0-9_]+)(\s[^>]*)?/>")
_PARTIAL_NAME_RE = re.compile(r"^<([A-Za-z0-9_]*)")


def _known_tags(tool_names) -> set[str]:
    tags = {str(name).strip() for name in (tool_names or []) if str(name or "").strip()}
    return tags | set(_GENERIC_TOOL_TAGS)


def strip_pseudo_tool_call_markup(text: str, tool_names=None) -> str:
    """从整段文本中剥离伪工具调用块（含嵌套内容）。"""
    if not text:
        return text
    tags = _known_tags(tool_names)
    out = []
    i = 0
    n = len(text)
    while i < n:
        lt = text.find("<", i)
        if lt < 0:
            out.append(text[i:])
            break
        out.append(text[i:lt])
        rest = text[lt:]
        name = _match_open_tag_name(rest, tags)
        if name is None:
            out.append("<")
            i = lt + 1
            continue
        close = f"</{name}>"
        close_idx = rest.find(close)
        if close_idx < 0:
            # 未闭合：视为伪调用残片，直接丢弃到末尾
            i = n
            break
        i = lt + close_idx + len(close)
    return "".join(out)


def _match_open_tag_name(rest: str, tags: set[str]) -> str | None:
    """若 rest 以某个已知工具标签的**完整开标签/自闭合标签**开头，返回该标签名。"""
    m = _SELF_CLOSING_RE.match(rest)
    if m and m.group(1) in tags:
        return m.group(1)
    m = _OPEN_TAG_RE.match(rest)
    if m and m.group(1) in tags:
        return m.group(1)
    return None


def _could_start_known_tag(partial: str, tags: set[str]) -> bool:
    """partial（以 '<' 开头、可能未闭合）是否可能是某个已知标签的开头。"""
    m = _PARTIAL_NAME_RE.match(partial)
    if m is None:
        return False
    prefix = m.group(1)
    for tag in tags:
        if prefix and tag.startswith(prefix):
            return True
        if not prefix:
            return True
    return False


class PseudoToolCallStreamFilter:
    """流式过滤：去掉伪工具调用块，同时避免跨 chunk 标签泄漏。

    用法：对每个流式 chunk 调用 ``feed(chunk)``，取其返回的可安全下发文本；
    流结束时调用一次 ``flush()`` 取尾部。
    """

    def __init__(self, tool_names=None, *, max_hold: int = 4096):
        self._tags = _known_tags(tool_names)
        self._buffer = ""
        self._inside: str | None = None
        self._max_hold = max_hold

    def feed(self, chunk: str) -> str:
        if chunk:
            self._buffer += chunk
        return self._drain(flush=False)

    def flush(self) -> str:
        return self._drain(flush=True)

    def _drain(self, *, flush: bool) -> str:
        out: list[str] = []
        while True:
            if self._inside is not None:
                close = f"</{self._inside}>"
                idx = self._buffer.find(close)
                if idx >= 0:
                    self._buffer = self._buffer[idx + len(close):]
                    self._inside = None
                    continue
                if flush:
                    # 未闭合：一次性丢弃（疑似伪调用残片）
                    self._buffer = ""
                    self._inside = None
                break

            lt = self._buffer.find("<")
            if lt < 0:
                out.append(self._buffer)
                self._buffer = ""
                break
            if lt > 0:
                out.append(self._buffer[:lt])
                self._buffer = self._buffer[lt:]

            name = _match_open_tag_name(self._buffer, self._tags)
            if name is not None:
                # 命中完整开标签：进入块内，丢弃该开标签
                m = _SELF_CLOSING_RE.match(self._buffer)
                if m:
                    self._buffer = self._buffer[m.end():]
                    continue
                m = _OPEN_TAG_RE.match(self._buffer)
                self._buffer = self._buffer[m.end():]
                self._inside = name
                continue

            if not flush and _could_start_known_tag(self._buffer, self._tags):
                # 可能是已知标签的开头：正常情况下回撤等待后续 chunk；
                # 但若缓冲过长仍未判定（防无限缓冲），则放行。
                if len(self._buffer) > self._max_hold:
                    out.append(self._buffer)
                    self._buffer = ""
                break
            # 不是工具标签：放行一个 '<'，继续扫描
            out.append("<")
            self._buffer = self._buffer[1:]
            if not self._buffer:
                break

        return "".join(out)
