"""/device 命名空间处理器测试：鉴权、进房、链路标记生命周期。"""

import asyncio

import pytest

from internal.extension import device_gateway_handlers as handlers


class _FakeSio:
    def __init__(self):
        self.rooms = []

    async def enter_room(self, sid, room, namespace=None):
        self.rooms.append((room, namespace))


class _FakeGatewayService:
    def __init__(self):
        self.online = []
        self.offline = []

    def mark_link_online(self, device_id):
        self.online.append(device_id)

    def mark_link_offline(self, device_id):
        self.offline.append(device_id)


class _FakeDeviceService:
    def __init__(self, verified=True):
        self.verified = verified
        self.calls = []

    def verify_bridge_token(self, device_id, token):
        self.calls.append((device_id, token))
        return self.verified


@pytest.fixture(autouse=True)
def _clear_sid_map():
    handlers._sid_devices.clear()
    yield
    handlers._sid_devices.clear()


def _patch(monkeypatch, *, verified=True):
    sio = _FakeSio()
    gateway = _FakeGatewayService()
    device_service = _FakeDeviceService(verified)
    monkeypatch.setattr(handlers, "get_socketio", lambda: sio)
    monkeypatch.setattr(handlers, "_get_gateway_service", lambda: gateway)
    monkeypatch.setattr(handlers, "_get_device_service", lambda: device_service)
    return sio, gateway, device_service


def test_connect_enters_link_room_and_marks_online(monkeypatch):
    sio, gateway, device_service = _patch(monkeypatch)

    ok = asyncio.run(
        handlers.handle_device_connect("sid-1", auth={"device_id": "dev-1", "bridge_token": "tok"})
    )

    assert ok is True
    assert sio.rooms == [("device-link:dev-1", handlers.DEVICE_NAMESPACE)]
    assert gateway.online == ["dev-1"]
    assert device_service.calls == [("dev-1", "tok")]
    assert handlers._sid_devices["sid-1"] == "dev-1"


def test_connect_rejects_missing_or_invalid_credentials(monkeypatch):
    sio, gateway, _ = _patch(monkeypatch)

    assert asyncio.run(handlers.handle_device_connect("sid-1", auth={})) is False
    assert asyncio.run(
        handlers.handle_device_connect("sid-1", auth={"device_id": "dev-1", "bridge_token": ""})
    ) is False

    sio2, gateway2, _ = _patch(monkeypatch, verified=False)
    assert asyncio.run(
        handlers.handle_device_connect("sid-2", auth={"device_id": "dev-1", "bridge_token": "bad"})
    ) is False
    assert sio2.rooms == []
    assert gateway2.online == []
    assert handlers._sid_devices == {}


def test_ping_refreshes_link_marker(monkeypatch):
    _sio, gateway, _ = _patch(monkeypatch)
    asyncio.run(handlers.handle_device_connect("sid-1", auth={"device_id": "dev-1", "bridge_token": "tok"}))

    asyncio.run(handlers.handle_device_ping("sid-1", {}))

    assert gateway.online == ["dev-1", "dev-1"]


def test_disconnect_clears_marker_only_after_last_connection(monkeypatch):
    _sio, gateway, _ = _patch(monkeypatch)
    asyncio.run(handlers.handle_device_connect("sid-1", auth={"device_id": "dev-1", "bridge_token": "tok"}))
    asyncio.run(handlers.handle_device_connect("sid-2", auth={"device_id": "dev-1", "bridge_token": "tok"}))

    asyncio.run(handlers.handle_device_disconnect("sid-1"))
    assert gateway.offline == []

    asyncio.run(handlers.handle_device_disconnect("sid-2"))
    assert gateway.offline == ["dev-1"]


def test_disconnect_unknown_sid_is_noop(monkeypatch):
    _sio, gateway, _ = _patch(monkeypatch)
    asyncio.run(handlers.handle_device_disconnect("sid-x"))
    assert gateway.offline == []
