"""Environment-backed configuration for the context compression layer."""

from __future__ import annotations

import os

ENV_ENABLED = "CONTEXT_COMPRESSION_ENABLED"
ENV_MIN_TOKENS = "CONTEXT_COMPRESSION_MIN_TOKENS"
ENV_MIN_CHARS = "CONTEXT_COMPRESSION_MIN_CHARS"
ENV_MODEL = "CONTEXT_COMPRESSION_MODEL"
ENV_PROTECT_RECENT = "CONTEXT_COMPRESSION_PROTECT_RECENT"
ENV_MAX_ITEMS = "CONTEXT_COMPRESSION_MAX_ITEMS"
ENV_MAX_LOG_LINES = "CONTEXT_COMPRESSION_MAX_LOG_LINES"

DEFAULT_MIN_TOKENS = 250
DEFAULT_MIN_CHARS = 1000
DEFAULT_MODEL = "gpt-4o"
DEFAULT_PROTECT_RECENT = 2
DEFAULT_MAX_ITEMS = 15
DEFAULT_MAX_LOG_LINES = 60


def _env_bool(name: str, default: bool = False) -> bool:
    value = os.getenv(name, "").strip().lower()
    if not value:
        return default
    return value in {"1", "true", "yes", "on"}


def _env_int(name: str, default: int) -> int:
    try:
        value = int(os.getenv(name, "").strip())
    except (TypeError, ValueError):
        return default
    return value if value > 0 else default


def is_enabled() -> bool:
    return _env_bool(ENV_ENABLED, default=False)


def get_min_tokens() -> int:
    return _env_int(ENV_MIN_TOKENS, DEFAULT_MIN_TOKENS)


def get_min_chars() -> int:
    return _env_int(ENV_MIN_CHARS, DEFAULT_MIN_CHARS)


def get_model() -> str:
    return os.getenv(ENV_MODEL, DEFAULT_MODEL).strip() or DEFAULT_MODEL


def get_protect_recent() -> int:
    return _env_int(ENV_PROTECT_RECENT, DEFAULT_PROTECT_RECENT)


def get_max_items() -> int:
    return _env_int(ENV_MAX_ITEMS, DEFAULT_MAX_ITEMS)


def get_max_log_lines() -> int:
    return _env_int(ENV_MAX_LOG_LINES, DEFAULT_MAX_LOG_LINES)
