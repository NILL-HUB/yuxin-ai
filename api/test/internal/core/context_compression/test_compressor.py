from __future__ import annotations

import json

import pytest

from internal.core.context_compression import (
    compress_content,
    compress_dict_messages,
    compress_langchain_tool_messages,
    get_compression_stats,
    is_enabled,
    reset_compression_stats,
)


@pytest.fixture(autouse=True)
def _clean_stats():
    reset_compression_stats()
    yield
    reset_compression_stats()


def _make_json_rows(count: int = 300) -> str:
    rows = []
    for i in range(count):
        rows.append(
            {
                "id": i,
                "name": f"record_{i:04d}",
                "status": ["ok", "pending", "failed"][i % 3],
                "score": round(i * 0.137, 3),
                "path": f"/data/bucket/{i % 12}/file_{i}.json",
                "tags": ["search", "index", "llm"],
            }
        )
    return json.dumps(rows, ensure_ascii=False)


def test_disabled_by_default(monkeypatch):
    monkeypatch.delenv("CONTEXT_COMPRESSION_ENABLED", raising=False)
    assert is_enabled() is False


def test_disabled_passthrough(monkeypatch):
    monkeypatch.setenv("CONTEXT_COMPRESSION_ENABLED", "0")
    content = _make_json_rows()
    result = compress_content(content, tool_name="search")
    assert result.was_compressed is False
    assert result.compressed_content == content


def test_short_content_passthrough(monkeypatch):
    monkeypatch.setenv("CONTEXT_COMPRESSION_ENABLED", "1")
    result = compress_content("hello", tool_name="echo")
    assert result.was_compressed is False
    assert result.compressed_content == "hello"


def test_compress_json_array_when_enabled(monkeypatch):
    monkeypatch.setenv("CONTEXT_COMPRESSION_ENABLED", "1")
    content = _make_json_rows()
    result = compress_content(content, tool_name="search")
    assert result.was_compressed is True
    assert result.tokens_saved > 0
    assert result.compressed_content != content
    stats = get_compression_stats()
    assert stats["requests"] >= 1
    assert stats["compressions"] >= 1


def test_compress_langchain_tool_messages(monkeypatch):
    monkeypatch.setenv("CONTEXT_COMPRESSION_ENABLED", "1")
    from langchain_core.messages import ToolMessage

    message = ToolMessage(tool_call_id="call_1", name="search", content=_make_json_rows())
    compress_langchain_tool_messages([message], protect_recent=0)
    assert message.content != _make_json_rows()
    assert get_compression_stats()["compressions"] >= 1


def test_truncate_long_plain_text_tool_result(monkeypatch):
    monkeypatch.setenv("CONTEXT_COMPRESSION_ENABLED", "1")
    content = "x" * 30000

    result = compress_content(content, tool_name="read_file")

    assert result.was_compressed is True
    assert "已截断" in result.compressed_content
    assert len(result.compressed_content) < 30000
    assert "truncate" in result.transforms


def test_compress_dict_messages(monkeypatch):
    monkeypatch.setenv("CONTEXT_COMPRESSION_ENABLED", "1")
    messages = [
        {"role": "tool", "tool_call_id": "call_1", "name": "search", "content": _make_json_rows()},
    ]
    compress_dict_messages(messages, protect_recent=0)
    assert messages[0]["content"] != _make_json_rows()
    assert get_compression_stats()["compressions"] >= 1


def test_compress_logs_when_enabled(monkeypatch):
    monkeypatch.setenv("CONTEXT_COMPRESSION_ENABLED", "1")
    lines = [
        f"2026-08-12 10:00:{i % 60:02d}.{i % 1000:03d} INFO worker-{i % 4} task={i} "
        f"message=step {i} completed duration_ms={i * 7 % 997}"
        for i in range(200)
    ]
    lines[42] = "2026-08-12 10:00:42.042 FATAL out of memory at line 42"
    content = "\n".join(lines)
    result = compress_content(content, tool_name="run")
    assert result.was_compressed is True
    assert "FATAL out of memory" in result.compressed_content
    assert get_compression_stats()["compressions"] >= 1


def test_plain_text_passthrough(monkeypatch):
    monkeypatch.setenv("CONTEXT_COMPRESSION_ENABLED", "1")
    content = "这是普通中文文本，" * 200
    result = compress_content(content, tool_name="echo")
    assert result.was_compressed is False
    assert result.compressed_content == content
