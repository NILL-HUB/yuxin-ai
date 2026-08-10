"""聊天路由模块（从 asgi_app.py 拆分）：async SSE 全链路对话端点。"""
import asyncio
import logging
from uuid import UUID

from quart import Response, request

from app.http import support as _support
from app.http.app import app as flask_app
from app.http.support import (
    _err,
    _resolve_account,
)

logger = logging.getLogger(__name__)


def _get_services():
    return _support._get_services()


def _load_runtime_context(app_id, account_id, image_urls):
    return _support._load_runtime_context(app_id, account_id, image_urls)

_registered = False


def register_routes(quart_app):
    global _registered
    if _registered:
        return
    _registered = True

    @quart_app.post("/api/async/chat/completion")
    @quart_app.post("/async/chat/completion")
    async def async_chat_completion() -> Response:
        """async SSE 聊天完成端点：消费 agent.astream 全链路（方案 B 主路径）。"""
        payload = await request.get_json(force=True, silent=True) or {}
        raw_app_id = str(payload.get("app_id") or "")
        raw_account_id = str(payload.get("account_id") or "")
        if not raw_app_id or not raw_account_id:
            return _err("validate_error", "缺少 app_id 或 account_id", 400)
        try:
            app_id = UUID(raw_app_id)
            account_id = UUID(raw_account_id)
        except (ValueError, TypeError):
            return _err("invalid_param", "app_id 或 account_id 参数无效", 400)
        query = str(payload.get("query") or "")
        image_urls = list(payload.get("image_urls") or [])
        history = list(payload.get("history") or [])
        long_term_memory = str(payload.get("long_term_memory") or "")
        conversation_id = str(payload.get("conversation_id") or "")
        message_id = str(payload.get("message_id") or "")
        enable_deep_thinking = bool(payload.get("enable_deep_thinking") or False)

        # 鉴权：Bearer token 必须有效（用户 JWT sub 与 account_id 一致，或管理员 JWT）
        _, err = await _resolve_account(str(account_id))
        if err is not None:
            return err

        app_runtime_service, _, _, _ = _get_services()
        try:
            account, draft_app_config, llm = await asyncio.to_thread(
                _load_runtime_context, app_id, account_id, image_urls
            )
        except Exception:
            logger.exception("async SSE 上下文加载失败: app_id=%s", app_id)
            return Response(
                b'event: error\ndata:{"error":"context_load_failed"}\n\n',
                mimetype="text/event-stream",
                headers={
                    "Cache-Control": "no-cache",
                    "X-Accel-Buffering": "no",
                },
            )

        async def generate():
            try:
                async for frame in app_runtime_service.stream_agent_events_async(
                    app_id=app_id,
                    account=account,
                    draft_app_config=draft_app_config,
                    llm=llm,
                    query=query,
                    image_urls=image_urls,
                    history=history,
                    long_term_memory=long_term_memory,
                    conversation_id=conversation_id,
                    message_id=message_id,
                    enable_deep_thinking=enable_deep_thinking,
                    flask_app=flask_app,
                ):
                    yield frame.encode("utf-8")
            except Exception:
                logger.exception("async SSE 流执行失败: app_id=%s", app_id)
                yield b'event: error\ndata:{"error":"internal_error"}\n\n'

        return Response(
            generate(),
            mimetype="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "X-Accel-Buffering": "no",
                "Connection": "keep-alive",
            },
        )
