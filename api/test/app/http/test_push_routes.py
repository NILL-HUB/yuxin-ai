"""推送令牌注册路由测试：参数透传、校验错误、停用幂等。"""

import asyncio
from types import SimpleNamespace
from uuid import uuid4

import app.http.asgi_app as asgi_app
from app.http import support
from app.http.push_routes import register_routes
from internal.exception import ValidateErrorException

register_routes(asgi_app.quart_app)


class _FakePushDeviceService:
    def __init__(self):
        self.calls = []

    def register(self, *, account_id, platform, provider, token):
        self.calls.append(("register", str(account_id), platform, provider, token))
        if provider == "wechat":
            raise ValidateErrorException("provider 只能是 getui / umeng")
        return {"provider": provider, "platform": platform, "token": token, "enabled": True}

    def unregister(self, *, account_id, provider, token):
        self.calls.append(("unregister", str(account_id), provider, token))
        return {"unregistered": True, "found": True}


def _setup(monkeypatch):
    account = SimpleNamespace(id=uuid4())
    service = _FakePushDeviceService()

    async def _fake_resolve_account(account_id_override=None):
        return account, None

    monkeypatch.setattr(support, "_resolve_account", _fake_resolve_account)
    monkeypatch.setattr(support, "_get_service", lambda cls: service)
    return account, service


def test_register_push_device_passes_payload(monkeypatch):
    account, service = _setup(monkeypatch)

    async def _run():
        async with asgi_app.quart_app.test_client() as client:
            resp = await client.post(
                "/push/devices/register",
                json={"platform": "android", "provider": "getui", "token": "cid-1"},
            )
            return resp, await resp.get_json()

    resp, payload = asyncio.run(_run())
    assert resp.status_code == 200
    assert payload["data"]["enabled"] is True
    assert service.calls[0] == ("register", str(account.id), "android", "getui", "cid-1")


def test_register_push_device_returns_validate_error(monkeypatch):
    _setup(monkeypatch)

    async def _run():
        async with asgi_app.quart_app.test_client() as client:
            resp = await client.post(
                "/push/devices/register",
                json={"platform": "android", "provider": "wechat", "token": "t"},
            )
            return resp, await resp.get_json()

    resp, payload = asyncio.run(_run())
    assert resp.status_code == 400
    assert payload["code"] == "validate_error"


def test_unregister_push_device(monkeypatch):
    account, service = _setup(monkeypatch)

    async def _run():
        async with asgi_app.quart_app.test_client() as client:
            resp = await client.post(
                "/push/devices/unregister",
                json={"provider": "umeng", "token": "dt-1"},
            )
            return resp, await resp.get_json()

    resp, payload = asyncio.run(_run())
    assert resp.status_code == 200
    assert payload["data"]["unregistered"] is True
    assert service.calls[0] == ("unregister", str(account.id), "umeng", "dt-1")
