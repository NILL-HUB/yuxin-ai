"""Self-contained context compressor adapted from Headroom's core design.

Headroom's production compressors are Rust-backed and its dependency tree
conflicts with yuxin-ai's locked requirements. This module keeps the core
design (content routing + structural JSON compression + log collapse +
protected messages + fail-open) in pure Python, with no external dependency.
"""

from __future__ import annotations

import json
import logging
import re
import threading
from collections import Counter
from dataclasses import dataclass, field
from statistics import mean
from typing import Any

from .config import (
    get_max_items,
    get_max_log_lines,
    get_min_chars,
    get_min_tokens,
    get_protect_recent,
    is_enabled,
)

logger = logging.getLogger(__name__)

_stats_lock = threading.Lock()
_stats: dict[str, int] = {
    "requests": 0,
    "compressions": 0,
    "tokens_before": 0,
    "tokens_after": 0,
    "tokens_saved": 0,
    "errors": 0,
}

_ERROR_KEYWORDS = (
    "error",
    "exception",
    "failed",
    "failure",
    "critical",
    "fatal",
    "traceback",
    "panic",
    "out of memory",
)

_LOG_LEVEL_RE = re.compile(r"\b(FATAL|CRITICAL|ERROR|WARN|WARNING|INFO|DEBUG|TRACE)\b", re.IGNORECASE)
_NUMBER_RE = re.compile(r"\b\d+(?:\.\d+)?\b")
_HEX_RE = re.compile(r"\b0x[0-9a-fA-F]+\b")
_UUID_RE = re.compile(r"\b[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}\b")
_TIMESTAMP_RE = re.compile(r"\b\d{4}-\d{2}-\d{2}[T ][0-9:.Z+-]+\b")

# 普通长文本工具结果的兜底硬裁剪阈值（JSON 数组/日志有各自的结构化压缩）。
DEFAULT_MAX_TOOL_RESULT_CHARS = 12000


@dataclass(slots=True)
class CompressionResult:
    """Result of one content compression attempt."""

    original_content: str
    compressed_content: str
    original_tokens: int = 0
    compressed_tokens: int = 0
    tokens_saved: int = 0
    savings_ratio: float = 0.0
    transforms: list[str] = field(default_factory=list)
    was_compressed: bool = False
    error: str | None = None


def is_available() -> bool:
    """The self-contained compressor is always available."""
    return True


def _passthrough(content: str, reason: str | None = None) -> CompressionResult:
    return CompressionResult(
        original_content=content,
        compressed_content=content,
        error=reason,
    )


def _approx_tokens(content: str) -> int:
    return max(1, len(content or "") // 4)


def _record(original_tokens: int, compressed_tokens: int, was_compressed: bool, error: bool = False) -> None:
    with _stats_lock:
        _stats["requests"] += 1
        _stats["tokens_before"] += original_tokens
        _stats["tokens_after"] += compressed_tokens
        _stats["tokens_saved"] += max(0, original_tokens - compressed_tokens)
        if was_compressed:
            _stats["compressions"] += 1
        if error:
            _stats["errors"] += 1


def get_compression_stats() -> dict[str, int]:
    with _stats_lock:
        return dict(_stats)


def reset_compression_stats() -> None:
    with _stats_lock:
        _stats.update(
            {
                "requests": 0,
                "compressions": 0,
                "tokens_before": 0,
                "tokens_after": 0,
                "tokens_saved": 0,
                "errors": 0,
            }
        )


def _contains_error(value: Any) -> bool:
    try:
        text = json.dumps(value, ensure_ascii=False, default=str).lower()
    except Exception:
        text = str(value).lower()
    return any(keyword in text for keyword in _ERROR_KEYWORDS)


def _guess_type(value: Any) -> str:
    if isinstance(value, bool):
        return "bool"
    if isinstance(value, int):
        return "int"
    if isinstance(value, float):
        return "float"
    if isinstance(value, (dict, list)):
        return "json"
    return "string"


def _format_value(value: Any) -> str:
    if isinstance(value, str):
        return json.dumps(value, ensure_ascii=False)
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False, separators=(",", ":"))
    return str(value)


def _row_to_csv(keys: list[str], row: dict[str, Any]) -> str:
    return ",".join(_format_value(row.get(key)) for key in keys)


def _numeric_stats(rows: list[dict[str, Any]], key: str) -> str | None:
    values: list[float] = []
    for row in rows:
        value = row.get(key)
        if isinstance(value, bool) or value is None:
            continue
        if isinstance(value, (int, float)):
            values.append(float(value))
    if not values:
        return None
    try:
        average = mean(values)
    except Exception:
        average = 0.0
    return f"{key}: min={min(values):g} max={max(values):g} mean={average:.3g}"


def _compress_json_array(content: str) -> CompressionResult:
    try:
        data = json.loads(content)
    except (TypeError, ValueError):
        return _passthrough(content)
    if not isinstance(data, list) or not data:
        return _passthrough(content)

    max_items = get_max_items()
    error_rows: list[tuple[int, Any]] = []
    for index, item in enumerate(data):
        if _contains_error(item):
            error_rows.append((index, item))

    if all(isinstance(item, dict) for item in data):
        keys: list[str] = []
        for item in data:
            for key in item.keys():
                if key not in keys:
                    keys.append(key)
        first = data[:2]
        last = data[-2:]
        middle = data[2:-2]
        sampled: list[Any] = list(first) + list(last)
        if middle:
            step = max(1, len(middle) // max(1, max_items - len(sampled)))
            for index in range(0, len(middle), step):
                if len(sampled) >= max_items:
                    break
                sampled.append(middle[index])

        for index, item in error_rows:
            if index >= len(data):
                continue
            if item not in sampled and len(sampled) < max_items + len(error_rows):
                sampled.append(item)

        lines: list[str] = []
        lines.append(f"[ARRAY] count={len(data)} schema={{{','.join(f'{k}:{_guess_type(next((row.get(k) for row in data if k in row), None))}' for k in keys)}}}")
        for index, item in enumerate(sampled):
            prefix = "#E" if item in [row for _, row in error_rows] else ""
            lines.append(f"{prefix}{index},{_row_to_csv(keys, item)}")

        stats_lines: list[str] = []
        for key in keys:
            categories = Counter(
                json.dumps(row.get(key), ensure_ascii=False, default=str, sort_keys=True)
                for row in data
                if row.get(key) is not None and isinstance(row.get(key), (str, bool))
            )
            if categories and len(categories) <= 12:
                summary = " ".join(f"{name}={count}" for name, count in categories.most_common(6))
                stats_lines.append(f"{key}: {summary}")
            numeric = _numeric_stats(data, key)
            if numeric:
                stats_lines.append(numeric)
        if stats_lines:
            lines.append("[STATS]")
            lines.extend(stats_lines)

        if error_rows:
            lines.append(f"[ERRORS] {len(error_rows)}")
            for index, item in error_rows:
                lines.append(f"#{index}:{_format_value(item)}")

        compressed = "\n".join(lines)
    elif all(isinstance(item, (str, int, float)) for item in data):
        counts = Counter(_format_value(item) for item in data)
        unique = list(counts)
        sample = unique[: max(1, max_items // 2)] + unique[-max(1, max_items // 2) :]
        deduped = list(dict.fromkeys(sample))
        lines = [
            f"[ARRAY] count={len(data)} unique={len(unique)}",
            f"values=[{','.join(deduped[:max_items])}]",
            f"duplicates={{{','.join(f'{k}:{v}' for k, v in list(counts.most_common(5)) if v > 1)}}}",
        ]
        compressed = "\n".join(lines)
    else:
        return _passthrough(content)

    if len(compressed) >= len(content):
        return _passthrough(content)
    original_tokens = _approx_tokens(content)
    compressed_tokens = _approx_tokens(compressed)
    tokens_saved = original_tokens - compressed_tokens
    result = CompressionResult(
        original_content=content,
        compressed_content=compressed,
        original_tokens=original_tokens,
        compressed_tokens=compressed_tokens,
        tokens_saved=tokens_saved,
        savings_ratio=tokens_saved / original_tokens if original_tokens else 0.0,
        transforms=["router:json_array"],
        was_compressed=True,
    )
    _record(original_tokens, compressed_tokens, was_compressed=True)
    return result


def _normalize_log_template(line: str) -> str:
    normalized = _HEX_RE.sub("0x%x", line)
    normalized = _UUID_RE.sub("%uuid", normalized)
    normalized = _TIMESTAMP_RE.sub("%ts", normalized)
    return _NUMBER_RE.sub("%d", normalized)


def _compress_logs(content: str) -> CompressionResult:
    lines = content.splitlines()
    if len(lines) < 20:
        return _passthrough(content)

    max_lines = get_max_log_lines()
    error_lines: list[tuple[int, str]] = []
    template_counter: Counter[str] = Counter()
    level_counter: Counter[str] = Counter()

    for index, line in enumerate(lines):
        match = _LOG_LEVEL_RE.search(line)
        level = match.group(1).upper() if match else "UNKNOWN"
        level_counter[level] += 1
        if level in {"ERROR", "FATAL", "CRITICAL"}:
            error_lines.append((index, line))
        else:
            template_counter[_normalize_log_template(line)] += 1

    output: list[str] = []
    output.append(
        f"[LOG] lines={len(lines)} errors={len(error_lines)} "
        f"templates={len(template_counter)} levels={{{','.join(f'{k}:{v}' for k, v in level_counter.most_common())}}}"
    )

    if error_lines:
        output.append("[ERRORS]")
        for index, line in error_lines[:10]:
            context = [lines[i] for i in range(max(0, index - 2), index)]
            for context_line in context[-2:]:
                output.append(f"# {context_line}")
            output.append(f"#{index} {line}")
        if len(error_lines) > 10:
            output.append(f"# ... {len(error_lines) - 10} more error lines")

    output.append("[SAMPLES]")
    output.extend(f"#{index} {line}" for index, line in list(enumerate(lines))[:2])
    if len(lines) > 4:
        output.extend(f"#{len(lines) - 2 + offset} {line}" for offset, line in enumerate(lines[-2:]))

    output.append("[TEMPLATES]")
    for template, count in template_counter.most_common(max_lines):
        output.append(f"{template} x{count}")

    compressed = "\n".join(output)
    if len(compressed) >= len(content):
        return _passthrough(content)
    original_tokens = _approx_tokens(content)
    compressed_tokens = _approx_tokens(compressed)
    tokens_saved = original_tokens - compressed_tokens
    result = CompressionResult(
        original_content=content,
        compressed_content=compressed,
        original_tokens=original_tokens,
        compressed_tokens=compressed_tokens,
        tokens_saved=tokens_saved,
        savings_ratio=tokens_saved / original_tokens if original_tokens else 0.0,
        transforms=["router:logs"],
        was_compressed=True,
    )
    _record(original_tokens, compressed_tokens, was_compressed=True)
    return result


def _looks_like_json_array(content: str) -> bool:
    try:
        value = json.loads(content)
    except (TypeError, ValueError):
        return False
    return isinstance(value, list) and bool(value)


def _looks_like_logs(content: str) -> bool:
    lines = content.splitlines()
    if len(lines) < 20:
        return False
    matched = sum(1 for line in lines if _LOG_LEVEL_RE.search(line))
    return matched / len(lines) >= 0.3


def _truncate_content(content: str, *, max_chars: int = DEFAULT_MAX_TOOL_RESULT_CHARS) -> CompressionResult:
    """保留头尾的硬裁剪，避免单个工具结果把上下文撑爆。"""
    if len(content) <= max_chars:
        return _passthrough(content)
    head_size = int(max_chars * 0.7)
    tail_size = max_chars - head_size
    head = content[:head_size]
    tail = content[-tail_size:] if tail_size > 0 else ""
    marker = (
        f"\n...[工具结果过长，已截断，原长度 {len(content)} 字符]...\n"
    )
    truncated = f"{head}{marker}{tail}"
    original_tokens = _approx_tokens(content)
    compressed_tokens = _approx_tokens(truncated)
    return CompressionResult(
        original_content=content,
        compressed_content=truncated,
        original_tokens=original_tokens,
        compressed_tokens=compressed_tokens,
        tokens_saved=max(original_tokens - compressed_tokens, 0),
        savings_ratio=(
            (original_tokens - compressed_tokens) / original_tokens
            if original_tokens
            else 0.0
        ),
        transforms=["truncate"],
        was_compressed=True,
    )


def compress_content(
    content: str,
    *,
    tool_name: str = "",
    user_query: str = "",
    min_tokens: int | None = None,
) -> CompressionResult:
    """Compress a single tool output, failing open on any error."""
    content = str(content or "")
    if not content.strip():
        return _passthrough(content)
    if not is_enabled():
        return _passthrough(content)
    if len(content) < get_min_chars():
        return _passthrough(content)
    if _approx_tokens(content) < (min_tokens or get_min_tokens()):
        return _passthrough(content)

    try:
        if _looks_like_json_array(content):
            return _compress_json_array(content)
        if _looks_like_logs(content):
            return _compress_logs(content)
    except Exception as exc:
        logger.warning("context compression failed, using original content: %s", exc)
        _record(0, 0, was_compressed=False, error=True)
        return _passthrough(content, f"compression_error: {exc}")
    if len(content) > DEFAULT_MAX_TOOL_RESULT_CHARS:
        return _truncate_content(content)
    return _passthrough(content)


def _compress_tool_message(
    message: Any,
    *,
    is_langchain: bool,
    user_query: str = "",
) -> CompressionResult:
    content = getattr(message, "content", "") if is_langchain else str(message.get("content", "") or "")
    if not isinstance(content, str) or not content.strip():
        return _passthrough("", "empty")
    tool_name = getattr(message, "name", "") if is_langchain else str(message.get("name", "") or "")
    result = compress_content(content, tool_name=tool_name, user_query=user_query)
    if not result.was_compressed:
        return result
    if is_langchain:
        message.content = result.compressed_content
    else:
        message["content"] = result.compressed_content
    return result


def compress_langchain_tool_messages(
    messages: list[Any],
    *,
    user_query: str = "",
    protect_recent: int | None = None,
) -> list[CompressionResult]:
    """Compress ToolMessage content in place, leaving recent turns untouched."""
    if not is_enabled():
        return []
    if not isinstance(messages, list) or not messages:
        return []

    try:
        from langchain_core.messages import ToolMessage
    except Exception:
        return []

    protect = get_protect_recent() if protect_recent is None else max(0, int(protect_recent))
    compressible = messages[:-protect] if protect else messages
    results: list[CompressionResult] = []
    for message in compressible:
        if not isinstance(message, ToolMessage):
            continue
        try:
            results.append(_compress_tool_message(message, is_langchain=True, user_query=user_query))
        except Exception as exc:
            logger.warning("skip tool message compression: %s", exc)
    return results


def compress_dict_messages(
    messages: list[dict[str, Any]],
    *,
    user_query: str = "",
    protect_recent: int | None = None,
) -> list[dict[str, Any]]:
    """Compress OpenAI-shaped tool messages in place and return the messages."""
    if not is_enabled():
        return messages
    if not isinstance(messages, list) or not messages:
        return messages

    protect = get_protect_recent() if protect_recent is None else max(0, int(protect_recent))
    compressible = messages[:-protect] if protect else messages
    for message in compressible:
        if not isinstance(message, dict) or message.get("role") != "tool":
            continue
        try:
            _compress_tool_message(message, is_langchain=False, user_query=user_query)
        except Exception as exc:
            logger.warning("skip dict tool message compression: %s", exc)
    return messages
