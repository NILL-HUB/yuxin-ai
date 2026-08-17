"""IM 语音消息 webhook 端点。

提供 LINE 与 WhatsApp 的语音消息事件入口：签名校验 -> 媒体下载 -> ASR 转写
-> 回复原会话。飞书/钉钉/QQ 的事件接入随后续平台回调配置逐个补齐。
"""

import hmac
import json
import os

from quart import Response, request

from app.http import support as _support
from app.http.support import _json_resp, _ok


def _get_service(cls):
    return _support._get_service(cls)


def register_routes(quart_app):
    from app.http import asgi_app as a
    from internal.service.im_voice_service import ImVoiceService

    @quart_app.post("/im/line/webhook")
    async def im_line_webhook():
        raw_body = await request.get_data()
        signature = str(request.headers.get("X-Line-Signature", "") or "")
        service = _get_service(ImVoiceService)
        replies = await a._to_thread(service.handle_line_webhook, raw_body, signature)
        return _ok({"replies": replies})

    @quart_app.get("/im/whatsapp/webhook")
    async def im_whatsapp_verify():
        mode = str(request.args.get("hub.mode") or "")
        token = str(request.args.get("hub.verify_token") or "")
        challenge = str(request.args.get("hub.challenge") or "")
        expected = str(os.getenv("WHATSAPP_WEBHOOK_VERIFY_TOKEN", "") or "")
        if mode == "subscribe" and expected and hmac.compare_digest(token, expected):
            return Response(challenge, mimetype="text/plain")
        return _json_resp(code="unauthorized", message="invalid verification token", status=403)

    @quart_app.post("/im/whatsapp/webhook")
    async def im_whatsapp_webhook():
        raw_body = await request.get_data()
        signature = str(request.headers.get("X-Hub-Signature-256", "") or "")
        service = _get_service(ImVoiceService)
        replies = await a._to_thread(service.handle_whatsapp_webhook, raw_body, signature)
        return _ok({"replies": replies})

    @quart_app.post("/im/feishu/webhook")
    async def im_feishu_webhook():
        raw_body = await request.get_data()
        try:
            body = json.loads(raw_body or b"{}")
        except ValueError:
            body = {}

        if body.get("type") == "url_verification":
            header = body.get("header") if isinstance(body.get("header"), dict) else {}
            incoming_token = str(header.get("token") or body.get("token") or "")
            expected_token = str(os.getenv("FEISHU_VERIFICATION_TOKEN", "") or "")
            if not expected_token:
                return _json_resp(
                    code="unauthorized",
                    message="FEISHU_VERIFICATION_TOKEN 未配置，webhook 端点已禁用",
                    status=401,
                )
            if not hmac.compare_digest(incoming_token, expected_token):
                return _json_resp(
                    code="unauthorized",
                    message="invalid verification token",
                    status=401,
                )
            return Response(
                json.dumps({"challenge": body.get("challenge", "")}, ensure_ascii=False),
                mimetype="application/json",
            )

        signature = str(request.headers.get("X-Lark-Signature", "") or "")
        timestamp = str(request.headers.get("X-Lark-Request-Timestamp", "") or "")
        nonce = str(request.headers.get("X-Lark-Request-Nonce", "") or "")
        service = _get_service(ImVoiceService)
        replies = await a._to_thread(
            service.handle_feishu_webhook,
            raw_body,
            signature,
            timestamp,
            nonce,
        )
        return _ok({"replies": replies})

    @quart_app.post("/im/dingtalk/webhook")
    async def im_dingtalk_webhook():
        raw_body = await request.get_data()
        timestamp = str(request.args.get("timestamp", "") or "")
        sign = str(request.args.get("sign", "") or "")
        service = _get_service(ImVoiceService)
        replies = await a._to_thread(
            service.handle_dingtalk_webhook,
            raw_body,
            timestamp,
            sign,
        )
        return _ok({"replies": replies})
