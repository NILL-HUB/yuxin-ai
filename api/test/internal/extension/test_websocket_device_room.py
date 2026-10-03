"""设备定向推送房间测试。

覆盖：房间键单一事实源、emit_to_device 定向投递、订阅处理器的归属校验与拒绝路径。
"""

import asyncio
from types import SimpleNamespace
from uuid import uuid4

import pytest

from internal.lib.websocket_manager import WebSocketManager, device_room_key, ws_manager


def test_device_room_key_normalizes():
    assert device_room_key(" dev-1 ") == "device:dev-1"
    assert device_room_key("") == "device:"


class _FakeRedisManager:
    def __init__(self):
        self.calls = []

    def emit(self, event, data, room=None):
        self.calls.append((event, data, room))


def test_emit_to_device_targets_device_room(monkeypatch):
    fake = _FakeRedisManager()
    monkeypatch.setattr(
        "internal.extension.socketio_extension.get_redis_manager", lambda: fake
    )

    ws_manager.emit_to_device("dev-1", {"status": "online"}, event="device_status_changed")

    assert fake.calls == [("device_status_changed", {"status": "online"}, "device:dev-1")]


def test_emit_to_device_skips_blank_device(monkeypatch):
    fake = _FakeRedisManager()
    monkeypatch.setattr(
        "internal.extension.socketio_extension.get_redis_manager", lambda: fake
    )

    ws_manager.emit_to_device("", {"status": "online"})

    assert fake.calls == []


def test_emit_to_device_degrades_when_redis_unavailable(monkeypatch):
    def _boom():
        raise RuntimeError("redis down")

    monkeypatch.setattr("internal.extension.socketio_extension.get_redis_manager", _boom)

    # 不抛异常：通知失败不得影响调用方业务主流程
    ws_manager.emit_to_device("dev-1", {"status": "online"})


class _FakeSio:
    def __init__(self):
        self.rooms = []

    async def enter_room(self, sid, room):
        self.rooms.append(("enter", room))

    async def leave_room(self, sid, room):
        self.rooms.append(("leave", room))


@pytest.fixture()
def handler_env(monkeypatch):
    from internal.extension import websocket_handlers as handlers

    sid = f"sid-{uuid4()}"
    account_id = uuid4()
    ws_manager.add_connection(sid, account_id)
    sio = _FakeSio()
    monkeypatch.setattr(
        "internal.extension.socketio_extension.get_socketio", lambda: sio
    )
    yield handlers, sid, account_id, sio
    ws_manager.remove_connection(sid)


def test_subscribe_device_notification_requires_auth(handler_env, monkeypatch):
    handlers, _sid, _account, _sio = handler_env
    result = asyncio.run(handlers.handle_subscribe_device_notification("unknown-sid", {"device_id": "d1"}))
    assert result == {"ok": False, "error": "unauthorized"}


def test_subscribe_device_notification_requires_device_id(handler_env):
    handlers, sid, _account, _sio = handler_env
    result = asyncio.run(handlers.handle_subscribe_device_notification(sid, {}))
    assert result == {"ok": False, "error": "device_id_required"}


def test_subscribe_device_notification_rejects_foreign_device(handler_env, monkeypatch):
    handlers, sid, _account, _sio = handler_env
    monkeypatch.setattr(
        "internal.service.desktop_device_service.DesktopDeviceService.device_bindable",
        lambda self, account_id, device_id: False,
    )

    result = asyncio.run(handlers.handle_subscribe_device_notification(sid, {"device_id": "d1"}))

    assert result == {"ok": False, "error": "device_not_found"}


def test_subscribe_device_notification_enters_room(handler_env, monkeypatch):
    handlers, sid, _account, sio = handler_env
    monkeypatch.setattr(
        "internal.service.desktop_device_service.DesktopDeviceService.device_bindable",
        lambda self, account_id, device_id: True,
    )

    result = asyncio.run(handlers.handle_subscribe_device_notification(sid, {"device_id": "d1"}))

    assert result == {"ok": True, "channel": "device:d1"}
    assert ("enter", "device:d1") in sio.rooms


def test_unsubscribe_device_notification_leaves_room(handler_env):
    handlers, sid, _account, sio = handler_env
    asyncio.run(handlers.handle_unsubscribe_device_notification(sid, {"device_id": "d1"}))
    assert ("leave", "device:d1") in sio.rooms


def test_remove_connection_cleans_device_subscription():
    manager = WebSocketManager()
    account_id = uuid4()
    manager.add_connection("sid-x", account_id)
    manager.subscribe_notification("sid-x", device_room_key("d1"))

    manager.remove_connection("sid-x")

    assert "sid-x" not in manager._notification_subscribers.get(device_room_key("d1"), set())
