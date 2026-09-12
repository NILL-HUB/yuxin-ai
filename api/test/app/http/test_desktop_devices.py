"""桌面设备注册路由测试：POST /desktop/devices/register、GET /desktop/devices、
POST /desktop/devices/<device_id>/revoke。

验证「服务端 → 宿主机 worker」断链修复的入口：桌面端登录后上报 bridge 地址与
token，服务端按账号存储；测试以假服务替换 _get_service 检查参数透传与校验错误。
"""

import asyncio
from types import SimpleNamespace
from uuid import uuid4

import app.http.asgi_app as asgi_app
from app.http import support
from app.http.desktop_routes import register_routes
from internal.exception import ValidateErrorException

register_routes(asgi_app.quart_app)


def _mock_resolve_account(monkeypatch, account):
    async def _fake_resolve_account(account_id_override=None):
        return account, None

    monkeypatch.setattr(support, "_resolve_account", _fake_resolve_account)
    return account


class _FakeDeviceService:
    def __init__(self, *, register_error=None):
        self.calls = []
        self._register_error = register_error

    def register(self, *, account_id, device_id, bridge_origin, bridge_token, name, platform):
        self.calls.append(
            ("register", str(account_id), device_id, bridge_origin, bridge_token, name, platform)
        )
        if self._register_error is not None:
            raise self._register_error
        return {
            "device_id": device_id,
            "name": name,
            "platform": platform,
            "bridge_origin": bridge_origin,
            "is_default": True,
            "status": "online",
            "last_seen_at": None,
        }

    def list_devices(self, account_id):
        self.calls.append(("list", str(account_id)))
        return [{"device_id": "dev-1", "bridge_origin": "http://host.docker.internal:9876"}]

    def revoke(self, account_id, device_id):
        self.calls.append(("revoke", str(account_id), device_id))
        return True


def _setup(monkeypatch, service):
    account = SimpleNamespace(id=uuid4())
    _mock_resolve_account(monkeypatch, account)
    monkeypatch.setattr(support, "_get_service", lambda cls: service)
    return account


def test_register_device_passes_payload(monkeypatch):
    service = _FakeDeviceService()
    account = _setup(monkeypatch, service)

    async def _run():
        async with asgi_app.quart_app.test_client() as client:
            resp = await client.post(
                "/desktop/devices/register",
                json={
                    "device_id": "dev-1",
                    "bridge_origin": "http://host.docker.internal:9876",
                    "bridge_token": "secret-token",
                    "name": "我的电脑",
                    "platform": "win32",
                },
            )
            return resp, await resp.json

    resp, payload = asyncio.run(_run())
    assert resp.status_code == 200
    assert payload["code"] == "success"
    assert payload["data"]["device_id"] == "dev-1"
    assert service.calls[0][2] == "dev-1"
    assert service.calls[0][4] == "secret-token"
    assert service.calls[0][1] == str(account.id)


def test_register_device_returns_validate_error(monkeypatch):
    service = _FakeDeviceService(register_error=ValidateErrorException("device_id 不能为空"))
    _setup(monkeypatch, service)

    async def _run():
        async with asgi_app.quart_app.test_client() as client:
            resp = await client.post("/desktop/devices/register", json={})
            return resp, await resp.json

    resp, payload = asyncio.run(_run())
    assert resp.status_code == 400
    assert payload["code"] == "validate_error"


def test_list_devices(monkeypatch):
    service = _FakeDeviceService()
    account = _setup(monkeypatch, service)

    async def _run():
        async with asgi_app.quart_app.test_client() as client:
            resp = await client.get("/desktop/devices")
            return resp, await resp.json

    resp, payload = asyncio.run(_run())
    assert resp.status_code == 200
    assert payload["code"] == "success"
    assert payload["data"][0]["device_id"] == "dev-1"
    assert service.calls[0] == ("list", str(account.id))


def test_revoke_device(monkeypatch):
    service = _FakeDeviceService()
    account = _setup(monkeypatch, service)

    async def _run():
        async with asgi_app.quart_app.test_client() as client:
            resp = await client.post("/desktop/devices/dev-1/revoke")
            return resp, await resp.json

    resp, payload = asyncio.run(_run())
    assert resp.status_code == 200
    assert payload["data"]["revoked"] is True
    assert service.calls[0] == ("revoke", str(account.id), "dev-1")
