import asyncio
from types import SimpleNamespace
from uuid import uuid4

from internal.exception import UnauthorizedException
from internal.extension.websocket_handlers import (
    handle_connect,
    handle_subscribe_agent_notification,
    handle_subscribe_document_index_notification,
    register_socketio_handlers,
)


def _run(coro):
    return asyncio.run(coro)


def test_handle_connect_should_bind_authenticated_sid(monkeypatch):
    account_id = uuid4()
    add_calls: list[tuple[str, object]] = []

    monkeypatch.setattr(
        "internal.extension.websocket_handlers._resolve_socket_account_id",
        lambda auth=None: account_id,
    )
    monkeypatch.setattr(
        "internal.extension.websocket_handlers.ws_manager",
        SimpleNamespace(add_connection=lambda sid, resolved_account_id: add_calls.append((sid, resolved_account_id))),
    )

    result = _run(handle_connect("sid-1", None, {"token": "jwt-token"}))

    assert result is None
    assert add_calls == [("sid-1", account_id)]


def test_handle_connect_should_reject_invalid_token(monkeypatch):
    monkeypatch.setattr(
        "internal.extension.websocket_handlers._resolve_socket_account_id",
        lambda auth=None: (_ for _ in ()).throw(UnauthorizedException("bad token")),
    )
    monkeypatch.setattr(
        "internal.extension.websocket_handlers.ws_manager",
        SimpleNamespace(add_connection=lambda *_args, **_kwargs: None),
    )

    result = _run(handle_connect("sid-2", None, {"token": "bad-token"}))

    assert result is False


def test_handle_subscribe_document_notification_should_ack_with_server_channel(monkeypatch):
    account_id = uuid4()
    subscribe_calls: list[tuple[str, str]] = []
    room_calls: list[tuple[str, str]] = []

    async def fake_enter_room(sid, room):
        room_calls.append((sid, room))

    monkeypatch.setattr(
        "internal.extension.websocket_handlers.ws_manager",
        SimpleNamespace(
            get_connection=lambda sid: SimpleNamespace(account_id=account_id, sid=sid),
            subscribe_notification=lambda sid, channel: subscribe_calls.append((sid, channel)),
        ),
    )
    monkeypatch.setattr(
        "internal.extension.socketio_extension.get_socketio",
        lambda: SimpleNamespace(enter_room=fake_enter_room),
    )

    result = _run(handle_subscribe_document_index_notification("sid-3", None))

    assert result == {"ok": True, "channel": str(account_id)}
    assert subscribe_calls == [("sid-3", str(account_id))]
    assert room_calls == [("sid-3", str(account_id))]


def test_handle_subscribe_agent_notification_should_ack_with_prefixed_channel(monkeypatch):
    account_id = uuid4()
    subscribe_calls: list[tuple[str, str]] = []
    room_calls: list[tuple[str, str]] = []

    async def fake_enter_room(sid, room):
        room_calls.append((sid, room))

    monkeypatch.setattr(
        "internal.extension.websocket_handlers.ws_manager",
        SimpleNamespace(
            get_connection=lambda sid: SimpleNamespace(account_id=account_id, sid=sid),
            subscribe_notification=lambda sid, channel: subscribe_calls.append((sid, channel)),
        ),
    )
    monkeypatch.setattr(
        "internal.extension.socketio_extension.get_socketio",
        lambda: SimpleNamespace(enter_room=fake_enter_room),
    )

    result = _run(handle_subscribe_agent_notification("sid-4", None))

    expected_channel = f"agent:{account_id}"
    assert result == {"ok": True, "channel": expected_channel}
    assert subscribe_calls == [("sid-4", expected_channel)]
    assert room_calls == [("sid-4", expected_channel)]


def test_handle_subscribe_document_notification_should_reject_unauthenticated_sid(monkeypatch):
    monkeypatch.setattr(
        "internal.extension.websocket_handlers.ws_manager",
        SimpleNamespace(
            get_connection=lambda _sid: None,
            subscribe_notification=lambda *_args, **_kwargs: None,
        ),
    )

    result = _run(handle_subscribe_document_index_notification("sid-5", None))

    assert result == {"ok": False, "error": "unauthorized"}


def test_register_socketio_handlers_should_bind_expected_events():
    event_calls: list[tuple[str, str]] = []

    class FakeSocketIO:
        def on(self, event: str):
            def deco(handler):
                event_calls.append((event, handler.__name__))
                return handler

            return deco

    register_socketio_handlers(FakeSocketIO())

    assert event_calls == [
        ("connect", "handle_connect"),
        ("disconnect", "handle_disconnect"),
        ("subscribe_message", "handle_subscribe_message"),
        ("unsubscribe_message", "handle_unsubscribe_message"),
        ("subscribe_document_index_notification", "handle_subscribe_document_index_notification"),
        ("unsubscribe_document_index_notification", "handle_unsubscribe_document_index_notification"),
        ("subscribe_agent_notification", "handle_subscribe_agent_notification"),
        ("unsubscribe_agent_notification", "handle_unsubscribe_agent_notification"),
    ]
