"""A2A v1.0 HTTP 端点。

- `GET /.well-known/agent-card.json`：Agent Card 发现
- `POST /a2a`：JSON-RPC 2.0（message/send、tasks/get）

支持 Bearer token 可选鉴权（`A2A_API_TOKEN` 配置后启用）。
"""

import json
from typing import Any, AsyncGenerator

from quart import Response, request

from app.http import support as _support
from app.http.support import _json_resp, _ok


def _get_service(cls):
    return _support._get_service(cls)


def _token_enabled() -> bool:
    import os

    return bool(str(os.getenv("A2A_API_TOKEN") or "").strip())


def _authorized() -> bool:
    import hmac
    import os

    expected = str(os.getenv("A2A_API_TOKEN") or "").strip()
    if not expected:
        return True
    header = request.headers.get("Authorization", "")
    if not header.lower().startswith("bearer "):
        return False
    return hmac.compare_digest(header[7:].strip(), expected)


def register_routes(quart_app):
    from internal.service.a2a_gateway_service import A2AGatewayService

    @quart_app.get("/.well-known/agent-card.json")
    async def a2a_agent_card():
        if _token_enabled() and not _authorized():
            return _json_resp(code="unauthorized", message="unauthorized", status=401)
        from app.http import asgi_app as a

        service = a._get_service(A2AGatewayService)
        base_url = str(request.host_url or "").rstrip("/")
        card = service.get_agent_card(base_url=base_url)
        return Response(
            json.dumps(card, ensure_ascii=False, indent=2),
            mimetype="application/json",
        )

    @quart_app.post("/a2a")
    async def a2a_jsonrpc():
        if _token_enabled() and not _authorized():
            return _json_resp(code="unauthorized", message="unauthorized", status=401)
        from app.http import asgi_app as a

        try:
            body = await request.get_json(force=True, silent=True)
        except Exception:
            body = None
        if not isinstance(body, dict):
            return _json_resp(code="parse_error", message="invalid jsonrpc payload", status=400)
        req_id = body.get("id")
        method = str(body.get("method") or "")
        params = body.get("params") or {}
        if not isinstance(params, dict):
            params = {}

        service = a._get_service(A2AGatewayService)
        if method == "message/send":
            result = await a._to_thread(service.handle_message_send, req_id, params)
            return _ok(result)
        if method == "tasks/get":
            result = await a._to_thread(service.handle_tasks_get, req_id, params)
            return _ok(result)
        if method == "tasks/cancel":
            result = await a._to_thread(service.handle_tasks_cancel, req_id, params)
            return _ok(result)
        if method == "message/stream":
            return await _a2a_message_stream(service, req_id, params)
        return _ok(
            {
                "jsonrpc": "2.0",
                "id": req_id,
                "error": {"code": -32601, "message": f"method not found: {method}"},
            }
        )


async def _a2a_message_stream(service, req_id, params):
    """A2A v1.0 message/stream：SSE 返回 statusUpdate + 最终 message。"""

    async def _stream() -> AsyncGenerator[str, Any]:
        # 先发 WORKING 状态，再委派并返回最终 Task。
        working = {
            "task": {
                "id": "pending",
                "status": {"state": "TASK_STATE_WORKING"},
            }
        }
        yield f"event: statusUpdate\ndata: {json.dumps(working, ensure_ascii=False)}\n\n"

        response = await _support._to_thread(
            service.handle_message_stream, req_id, params
        )
        if response.get("error"):
            payload = {
                "task": {
                    "id": "failed",
                    "status": {
                        "state": "TASK_STATE_FAILED",
                        "message": {"role": "ROLE_AGENT", "parts": [{"text": str(response["error"])}]},
                    },
                }
            }
            yield f"event: message\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n"
            return
        result = response.get("result") or {}
        task = result.get("task") or {}
        payload = {"task": task}
        yield f"event: message\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n"

    return Response(_stream(), mimetype="text/event-stream")
