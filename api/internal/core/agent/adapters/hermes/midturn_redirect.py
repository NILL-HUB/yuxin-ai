"""mid-turn redirect：确认等待期的执行中纠正。

用户在 Agent 等待高风险工具授权时发送纠正消息，Agent 不执行原动作，
把纠正作为新用户消息注入当前轮，重新规划后继续。

实现：临时消息存 Redis（TTL 与确认等待窗口一致），由确认轮询消费。
"""

from __future__ import annotations

import logging
import os
import threading
import time
from typing import Any

logger = logging.getLogger(__name__)
_REDIRECT_LOCK = threading.Lock()

_REDIRECT_PREFIX = "tool_confirmation:redirect:"
_REQUEST_REDIRECT_PREFIX = "agent_request:redirect:"
_DEFAULT_TTL_SECONDS = 1200
_DEFAULT_REQUEST_TTL_SECONDS = 600
_MEMORY_REDIRECTS: dict[str, tuple[str, float]] = {}


def _redis():
    from app.http.module import injector
    from redis import Redis

    return injector.get(Redis)


def _redis_key(confirmation_id: str) -> str:
    return f"{_REDIRECT_PREFIX}{confirmation_id}"


def _request_redis_key(request_id: str) -> str:
    return f"{_REQUEST_REDIRECT_PREFIX}{request_id}"


def set_redirect(confirmation_id: str, message: str) -> bool:
    """写入纠正消息；返回是否写入成功（Redis 不可用时返回 False）。"""
    try:
        ttl = int(os.getenv("TOOL_CONFIRMATION_WAIT_SECONDS", _DEFAULT_TTL_SECONDS) or _DEFAULT_TTL_SECONDS)
        _redis().setex(_redis_key(confirmation_id), max(60, ttl), message)
        return True
    except Exception:
        logger.warning("写入 mid-turn redirect 失败，confirmation_id=%s", confirmation_id, exc_info=True)
        return False


def consume_redirect(confirmation_id: str) -> str:
    """读取并清除纠正消息；无消息返回空串。"""
    key = _redis_key(confirmation_id)
    try:
        client = _redis()
        value = client.get(key)
        if value:
            client.delete(key)
            return str(value or "")
    except Exception:
        logger.warning("读取 mid-turn redirect 失败，confirmation_id=%s", confirmation_id, exc_info=True)
    return ""


def set_request_redirect(request_id: str, message: str) -> bool:
    """按执行 request_id 暂存纠正消息，供 Agent 任意执行阶段轮前注入。"""
    ttl = int(
        os.getenv(
            "MIDTURN_REDIRECT_TTL_SECONDS",
            _DEFAULT_REQUEST_TTL_SECONDS,
        )
        or _DEFAULT_REQUEST_TTL_SECONDS
    )
    try:
        _redis().setex(_request_redis_key(request_id), max(30, ttl), message)
        return True
    except Exception:
        logger.warning("写入 request redirect 失败，回退内存: request_id=%s", request_id, exc_info=True)
    _MEMORY_REDIRECTS[str(request_id)] = (message, time.time() + max(30, ttl))
    return True


def consume_request_redirect(request_id: str) -> str:
    """读取并清除一次执行级别的纠正消息；无消息返回空串。"""
    key = _request_redis_key(request_id)
    try:
        client = _redis()
        value = client.get(key)
        if value:
            client.delete(key)
            return str(value or "")
    except Exception:
        logger.warning("读取 request redirect 失败，回退内存: request_id=%s", request_id, exc_info=True)
    with _REDIRECT_LOCK:
        entry = _MEMORY_REDIRECTS.pop(str(request_id), None)
    if entry is None:
        return ""
    message, expires_at = entry
    if time.time() > expires_at:
        return ""
    return message


def build_redirect_decision(message: str) -> str:
    return f"redirect:{message}"
