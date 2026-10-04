"""设备网关结果回传路由测试：设备 Bearer 鉴权、字段校验、发布与降级。"""

import asyncio

import app.http.asgi_app as asgi_app
from app.http import support
from app.http.desktop_routes import register_routes
from internal.service.desktop_device_service import DesktopDeviceService
from internal.service.device_gateway_service import DeviceGatewayService

register_routes(asgi_app.quart_app)


class _FakeDeviceService:
    def __init__(self, verified=True):
        self.verified = verified
        self.calls = []

    def verify_bridge_token(self, device_id, token):
        self.calls.append((device_id, token))
        return self.verified


class _FakeGatewayService:
    def __init__(self, published=True):
        self.published = published
        self.calls = []

    def publish_result(self, request_id, *, ok, result=None, error=""):
        self.calls.append(
            {"request_id": request_id, "ok": ok, "result": result, "error": error}
        )
        return self.published


def _setup(monkeypatch, device_service, gateway_service):
    mapping = {DesktopDeviceService: device_service, DeviceGatewayService: gateway_service}
    monkeypatch.setattr(support, "_get_service", lambda cls: mapping[cls])


def test_result_requires_device_bearer(monkeypatch):
    device_service = _FakeDeviceService(verified=False)
    gateway_service = _FakeGatewayService()
    _setup(monkeypatch, device_service, gateway_service)

    async def _run():
        async with asgi_app.quart_app.test_client() as client:
            resp = await client.post(
                "/desktop/gateway/result",
                json={"device_id": "dev-1", "request_id": "rid-1", "ok": True, "result": {"x": 1}},
                headers={"Authorization": "Bearer bad-token"},
            )
            return resp, await resp.json

    resp, payload = asyncio.run(_run())
    assert resp.status_code == 401
    assert payload["code"] == "unauthorized"
    assert gateway_service.calls == []


def test_result_publishes_after_verification(monkeypatch):
    device_service = _FakeDeviceService(verified=True)
    gateway_service = _FakeGatewayService(published=True)
    _setup(monkeypatch, device_service, gateway_service)

    async def _run():
        async with asgi_app.quart_app.test_client() as client:
            resp = await client.post(
                "/desktop/gateway/result",
                json={"device_id": "dev-1", "request_id": "rid-1", "ok": True, "result": {"content": "hi"}},
                headers={"Authorization": "Bearer good-token"},
            )
            return resp, await resp.json

    resp, payload = asyncio.run(_run())
    assert resp.status_code == 200
    assert payload["data"]["accepted"] is True
    assert device_service.calls == [("dev-1", "good-token")]
    assert gateway_service.calls == [
        {"request_id": "rid-1", "ok": True, "result": {"content": "hi"}, "error": ""}
    ]


def test_result_validates_required_fields(monkeypatch):
    device_service = _FakeDeviceService(verified=True)
    gateway_service = _FakeGatewayService()
    _setup(monkeypatch, device_service, gateway_service)

    async def _run():
        async with asgi_app.quart_app.test_client() as client:
            resp = await client.post(
                "/desktop/gateway/result",
                json={"device_id": "dev-1"},
                headers={"Authorization": "Bearer good-token"},
            )
            return resp, await resp.json

    resp, payload = asyncio.run(_run())
    assert resp.status_code == 400
    assert payload["code"] == "validate_error"
    assert gateway_service.calls == []


def test_result_degrades_when_publish_fails(monkeypatch):
    device_service = _FakeDeviceService(verified=True)
    gateway_service = _FakeGatewayService(published=False)
    _setup(monkeypatch, device_service, gateway_service)

    async def _run():
        async with asgi_app.quart_app.test_client() as client:
            resp = await client.post(
                "/desktop/gateway/result",
                json={"device_id": "dev-1", "request_id": "rid-1", "ok": False, "error": "bridge 超时"},
                headers={"Authorization": "Bearer good-token"},
            )
            return resp, await resp.js
