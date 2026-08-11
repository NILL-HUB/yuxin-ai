"""Context compression layer adapted from Headroom's core design.

This module keeps only the in-process compression part that yuxin-ai needs:
compress long tool outputs before they reach the LLM, protect short/user
messages, and fail open when Headroom is unavailable.
"""

from __future__ import annotations

from .compressor import (
    CompressionResult,
    compress_content,
    compress_dict_messages,
    compress_langchain_tool_messages,
    get_compression_stats,
    is_available,
    is_enabled,
    reset_compression_stats,
)

__all__ = [
    "CompressionResult",
    "compress_content",
    "compress_dict_messages",
    "compress_langchain_tool_messages",
    "get_compression_stats",
    "is_available",
    "is_enabled",
    "reset_compression_stats",
]
