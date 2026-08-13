"""HMAC 签名出站 Webhook 推送。

对齐 NousResearch/hermes-agent v0.20 的签名出站 webhook 能力
（session/tool/lifecycle 事件推送到外部 HTTP 端点），按本项目
多租户形态重写为无状态工具：

- HMAC-SHA256 签名（`X-Webhook-Signature` + `X-Webhook-Timestamp`）
- 幂等事件 ID，接收方可按 `X-Webhook-Event-Id` 去重
- 轻量重试（指数退避），失败返回结构化错误
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
import time
import urllib.error
import urllib.request
from typing import Any

logger = logging.getLogger(__name__)

DEFAULT_TIMEOUT_SECONDS = 10
DEFAULT_MAX_ATTEMPTS = 3


def sign_payload(payload: dict[str, Any], secret: str) -> tuple[str, str]:
    """返回 (签名, 时间戳)。签名 = base64(hmac_sha256(secret, timestamp.body))。"""
    timestamp = str(int(time.time()))
    body = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    digest = hmac.new(
        secret.encode("utf-8"),
        f"{timestamp}.{body}".encode("utf-8"),
        hashlib.sha256,
    ).digest()
    signature = base64.b64encode(digest).decode("ascii")
    return signature, timestamp


def build_event(
    *,
    event_type: str,
    subject_type: str,
    subject_id: str,
    payload: dict[str, Any],
    event_id: str | None = None,
) -> dict[str, Any]:
    """构造统一事件信封，接收方可以按 event_id 幂等消费。"""
    import uuid

    return {
        "event_id": event_id or str(uuid.uuid4()),
        "event_type": event_type,
        "subject_type": subject_type,
        "subject_id": str(subject_id),
        "timestamp": int(time.time()),
        "data": payload,
    }


def _build_headers(
    secret: str,
    payload: dict[str, Any],
    event_id: str,
) -> dict[str, str]:
    signature, timestamp = sign_payload(payload, secret)
    return {
        "Content-Type": "application/json; charset=utf-8",
        "User-Agent": "YuxinAI-Webhook/1.0",
        "X-Webhook-Signature": signature,
        "X-Webhook-Timestamp": timestamp,
        "X-Webhook-Event-Id": event_id,
    }


def deliver_webhook(
    url: str,
    secret: str,
    event: dict[str, Any],
    *,
    timeout: int = DEFAULT_TIMEOUT_SECONDS,
    max_attempts: int = DEFAULT_MAX_ATTEMPTS,
) -> dict[str, Any]:
    """推送事件到外部端点，返回投递结果。

    失败时按指数退避重试；最终失败返回结构化错误，不抛异常。
    """
    if not url or not secret:
        return {"ok": False, "error": "webhook url/secret 未配置"}
    body = json.dumps(event, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=body,
        method="POST",
        headers=_build_headers(secret, event, str(event.get("event_id", ""))),
    )
    last_error = ""
    for attempt in range(1, max(1, max_attempts) + 1):
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                status = int(getattr(response, "status", 200) or 200)
                return {
                    "ok": 200 <= status < 300,
                    "attempts": attempt,
                    "status": status,
                    "event_id": event.get("event_id"),
                }
        except urllib.error.HTTPError as exc:
            last_error = f"HTTP {exc.code}: {exc.reason}"
        except Exception as exc:  # noqa: BLE001
            last_error = str(exc)
        if attempt < max_attempts:
            time.sleep(min(2 ** (attempt - 1), 5))
    return {"ok": False, "attempts": max_attempts, "error": last_error, "event_id": event.get("event_id")}
