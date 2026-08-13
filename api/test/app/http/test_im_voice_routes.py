import asyncio
from types import SimpleNamespace
from uuid import uuid4

from app.http import support
from app.http.asgi_app import quart_app
from internal.service.im_voice_service import ImVoiceService


def _run_coro(coro):
    return asyncio.run(coro)


class _FakeImVoiceService:
    def __init__(self):
        self.calls = []

    def handle_line_webhook(self, raw_body, signature=""):
        self.calls.append(("line", signature))
        return ["识别文本"]

    def handle_whatsapp_webhook(self, raw_body, signature=""):
        self.calls.append(("whatsapp", signature))
        return ["识别文本"]

    def handle_feishu_webhook(self, raw_body, signature="", timestamp="", nonce=""):
        self.calls.append(("feishu", signature, timestamp, nonce))
        return ["识别文本"]

    def handle_dingtalk_webhook(self, raw_body, timestamp="", sign=""):
        self.calls.append(("dingtalk", timestamp, sign))
        return ["识别文本"]


def _setup(monkeypatch):
    service = _FakeImVoiceService()
    monkeypatch.setattr(
        support,
        "_get_service",
        lambda cls: service if cls is ImVoiceService else None,
    )
    return service


def test_line_webhook_route(monkeypatch):
    service = _setup(monkeypatch)

    async def _run():
        async with quart_app.test_client() as client:
            resp = await client.post(
                "/im/line/webhook",
                data=b'{"events":[]}',
                headers={"X-Line-Signature": "sig-1"},
            )
            return resp, await resp.json

    resp, payload = _run_coro(_run())
    assert resp.status_code == 200
    assert payload["data"]["replies"] == ["识别文本"]
    assert service.calls == [("line", "sig-1")]


def test_whatsapp_verify_route(monkeypatch):
    _setup(monkeypatch)
    monkeypatch.setenv("WHATSAPP_WEBHOOK_VERIFY_TOKEN", "verify-token")

    async def _run():
        async with quart_app.test_client() as client:
            resp = await client.get(
                "/im/whatsapp/webhook?hub.mode=subscribe&hub.verify_token=verify-token&hub.challenge=challenge-1"
            )
            return resp, await resp.get_data(as_text=True)

    resp, body = _run_coro(_run())
    assert resp.status_code == 200
    assert body == "challenge-1"


def test_whatsapp_verify_route_rejects_bad_token(monkeypatch):
    _setup(monkeypatch)
    monkeypatch.setenv("WHATSAPP_WEBHOOK_VERIFY_TOKEN", "verify-token")

    async def _run():
        async with quart_app.test_client() as client:
            resp = await client.get(
                "/im/whatsapp/webhook?hub.mode=subscribe&hub.verify_token=bad&hub.challenge=x"
            )
            return resp, await resp.json

    resp, payload = _run_coro(_run())
    assert resp.status_code == 403
    assert payload["code"] == "unauthorized"


def test_whatsapp_webhook_route(monkeypatch):
    service = _setup(monkeypatch)

    async def _run():
        async with quart_app.test_client() as client:
            resp = await client.post(
                "/im/whatsapp/webhook",
                data=b'{"entry":[]}',
                headers={"X-Hub-Signature-256": "sha256=abc"},
            )
            return resp, await resp.json

    resp, payload = _run_coro(_run())
    assert resp.status_code == 200
    assert payload["data"]["replies"] == ["识别文本"]
    assert service.calls == [("whatsapp", "sha256=abc")]


def test_feishu_webhook_url_verification(monkeypatch):
    _setup(monkeypatch)

    async def _run():
        async with quart_app.test_client() as client:
            resp = await client.post(
                "/im/feishu/webhook",
                json={"type": "url_verification", "challenge": "challenge-9"},
            )
            return resp, await resp.get_json()

    resp, payload = _run_coro(_run())
    assert resp.status_code == 200
    assert payload["challenge"] == "challenge-9"


def test_feishu_webhook_route(monkeypatch):
    service = _setup(monkeypatch)

    async def _run():
        async with quart_app.test_client() as client:
            resp = await client.post(
                "/im/feishu/webhook",
                json={"schema": "2.0", "event": {}},
                headers={
                    "X-Lark-Signature": "sig-1",
                    "X-Lark-Request-Timestamp": "1700000000",
                    "X-Lark-Request-Nonce": "nonce-1",
                },
            )
            return resp, await resp.json

    resp, payload = _run_coro(_run())
    assert resp.status_code == 200
    assert payload["data"]["replies"] == ["识别文本"]
    assert service.calls == [("feishu", "sig-1", "1700000000", "nonce-1")]


def test_dingtalk_webhook_route(monkeypatch):
    service = _setup(monkeypatch)

    async def _run():
        async with quart_app.test_client() as client:
            resp = await client.post(
                "/im/dingtalk/webhook?timestamp=1700000000&sign=sig-1",
                json={"msgtype": "audio", "content": {"downloadCode": "code-1"}},
            )
            return resp, await resp.json

    resp, payload = _run_coro(_run())
    assert resp.status_code == 200
    assert payload["data"]["replies"] == ["识别文本"]
    assert service.calls == [("dingtalk", "1700000000", "sig-1")]
