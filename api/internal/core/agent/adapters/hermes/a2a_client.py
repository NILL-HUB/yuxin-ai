"""A2A v1.0 出站客户端（JSON-RPC over HTTP）。

让 Agent 主动调用外部 A2A 对端：解析 Agent Card 或直接用 URL 发
message/send，返回对端最终文本。对齐 Hermes A2A 插件的出站能力。
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from typing import Any

from internal.core.agent.adapters.hermes.a2a_protocol import (
    PROTOCOL_VERSION,
    unwrap_send_message_text,
)

DEFAULT_TIMEOUT = 60


def fetch_agent_card(base_url: str, *, timeout: int = DEFAULT_TIMEOUT) -> dict[str, Any]:
    """读取外部 A2A 对端的 Agent Card。"""
    url = base_url.rstrip("/") + "/.well-known/agent-card.json"
    with urllib.request.urlopen(url, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def send_message(
    endpoint: str,
    text: str,
    *,
    context_id: str = "",
    req_id: str = "1",
    timeout: int = DEFAULT_TIMEOUT,
) -> dict[str, Any]:
    """向 A2A 端点发送 message/send，返回 JSON-RPC 响应。"""
    message: dict[str, Any] = {
        "role": "ROLE_USER",
        "parts": [{"text": text, "mediaType": "text/plain"}],
        "messageId": "msg-" + __import__("uuid").uuid4().hex[:16],
    }
    if context_id:
        message["contextId"] = context_id
    payload = {
        "jsonrpc": "2.0",
        "id": req_id,
        "method": "message/send",
        "params": {"message": message},
    }
    request = urllib.request.Request(
        endpoint,
        data=json.dumps(payload).encode("utf-8"),
        method="POST",
        headers={
            "Content-Type": "application/json",
            "A2A-Version": PROTOCOL_VERSION,
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        try:
            body = json.loads(exc.read().decode("utf-8", errors="replace"))
            return body if isinstance(body, dict) else {"error": {"message": str(exc)}}
        except Exception:
            return {"error": {"message": f"HTTP {exc.code}: {exc.reason}"}}
    except Exception as exc:
        return {"error": {"message": str(exc)}}


def send_message_text(
    endpoint: str,
    text: str,
    *,
    context_id: str = "",
    req_id: str = "1",
    timeout: int = DEFAULT_TIMEOUT,
) -> str:
    """发送消息并直接返回对端最终文本。"""
    response = send_message(
        endpoint,
        text,
        context_id=context_id,
        req_id=req_id,
        timeout=timeout,
    )
    if response.get("error"):
        return f"ERROR: {response['error']}"
    return unwrap_send_message_text(response.get("result"))
