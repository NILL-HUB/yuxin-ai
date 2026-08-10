"""ContextCompressor 单元测试。"""
from __future__ import annotations

import pytest
from langchain_core.messages import AIMessage, HumanMessage

from internal.core.memory.context_compressor import ContextCompressor


def _msg(*pairs: tuple[str, str]) -> list:
    """根据 (human, ai) 对构造消息列表。"""
    messages: list = []
    for human, ai in pairs:
        messages.append(HumanMessage(content=human))
        messages.append(AIMessage(content=ai))
    return messages


def _token_counter(messages: list) -> int:
    """简单 token 计数：每个字符算 1 个 token。"""
    total = 0
    for message in messages:
        content = message.content
        total += len(content) if isinstance(content, str) else 0
    return total


def test_compress_messages_should_return_unchanged_when_within_budget():
    compressor = ContextCompressor()
    messages = _msg(("hi", "hello"))

    kept, summary = compressor.compress_messages(messages, max_tokens=1000, token_counter=_token_counter)

    assert kept == messages
    assert summary == ""


def test_compress_messages_should_keep_recent_and_summarize_early(monkeypatch):
    compressor = ContextCompressor()
    messages = _msg(
        ("早期问题1", "早期回答1"),
        ("早期问题2", "早期回答2"),
        ("早期问题3", "早期回答3"),
        ("最近问题", "最近回答"),
    )
    monkeypatch.setattr(
        compressor,
        "_summarize_messages",
        lambda early: "早期对话摘要",
    )

    kept, summary = compressor.compress_messages(
        messages, max_tokens=10, token_counter=_token_counter
    )

    assert summary == "早期对话摘要"
    # 只保留最近 RECENT_KEEP_MESSAGES 条
    assert len(kept) == ContextCompressor.RECENT_KEEP_MESSAGES
    assert kept[-1].content == "最近回答"


def test_compress_messages_should_fallback_when_summary_fails(monkeypatch):
    compressor = ContextCompressor()
    messages = _msg(
        ("早期问题1", "早期回答1"),
        ("早期问题2", "早期回答2"),
        ("早期问题3", "早期回答3"),
        ("最近问题", "最近回答"),
    )
    monkeypatch.setattr(compressor, "_summarize_messages", lambda early: "")

    kept, summary = compressor.compress_messages(
        messages, max_tokens=10, token_counter=_token_counter
    )

    # 压缩失败时返回原消息与空摘要，交由调用方回退截断
    assert kept == messages
    assert summary == ""


def test_compress_messages_should_not_compress_when_message_count_too_small():
    compressor = ContextCompressor()
    messages = _msg(("q1", "a1"), ("q2", "a2"))

    kept, summary = compressor.compress_messages(
        messages, max_tokens=1, token_counter=_token_counter
    )

    assert kept == messages
    assert summary == ""


def test_messages_to_text_should_flatten_human_ai_pairs():
    compressor = ContextCompressor()
    messages = _msg(("你好", "你好呀"), ("测试", "收到"))

    text = compressor._messages_to_text(messages)

    assert "Human: 你好" in text
    assert "AI: 你好呀" in text
    assert "Human: 测试" in text


def test_summarize_messages_should_return_empty_on_llm_failure(monkeypatch):
    compressor = ContextCompressor()

    def _boom():
        raise RuntimeError("model unavailable")

    monkeypatch.setattr(ContextCompressor, "_load_summary_llm", classmethod(_boom))

    summary = compressor._summarize_messages(_msg(("q", "a")))

    assert summary == ""
