"""设备网关服务单测：链路标记、下行等待、超时与降级、结果回传发布。"""

import json
from unittest import mock

from internal.service.device_gateway_service import (
    DEVICE_LINK_TTL_SECONDS,
    DEVICE_NAMESPACE,
    DEVICE_RESP_CHANNEL_PREFIX,
    DeviceGatewayService,
)


class _FakePubSub:
    def __init__(self, messages=None):
        self.messages = list(messages or [])
        self.channels = []
        self.closed = False

    def subscribe(self, channel):
        self.channels.append(channel)

    def unsubscribe(self, channel=None):
        pass

    def close(self):
        self.closed = True

    def get_message(self, timeout=None):
        if self.messages:
            return self.messages.pop(0)
        return None


class _FakeRedis:
    def __init__(self, messages=None):
        self.kv = {}
        self.published = []
        self.pubsub_obj = _FakePubSub(messages)

    def set(self, key, value, ex=None):
        self.kv[key] = (value, ex)

    def delete(self, key):
        self.kv.pop(key, None)

    def exists(self, key):
        return 1 if key in self.kv else 0

    def publish(self, channel, data):
        self.published.append((channel, data))
        return 0

    def pubsub(self, ignore_subscribe_messages=True):
        return self.pubsub_obj


def _service(redis):
    return DeviceGatewayService(db=None, redis_client=redis)


def test_mark_link_online_sets_key_with_ttl():
    redis = _FakeRedis()
    _service(redis).mark_link_online("dev-1")
    assert redis.kv["device-link:dev-1"] == ("1", DEVICE_LINK_TTL_SECONDS)


def test_is_online_reflects_marker():
    redis = _FakeRedis()
    service = _service(redis)
    assert service.is_online("dev-1") is False
    service.mark_link_online("dev-1")
    assert service.is_online("dev-1") is True
    service.mark_link_offline("dev-1")
    assert service.is_online("dev-1") is False


def test_call_device_offline_returns_none(monkeypatch):
    redis = _FakeRedis()
    emit = mock.Mock()
    monkeypatch.setattr(
        "internal.extension.socketio_extension.get_redis_manager",
        lambda: mock.Mock(emit=emit),
    )

    assert _service(redis).call_device("dev-1", purpose="/file", payload={}) is None
    emit.assert_not_called()


def test_call_device_success_returns_worker_json(monkeypatch):
    worker_json = {"ok": True, "content": "hello"}
    redis = _FakeRedis(
        messages=[{"type": "message", "data": json.dumps({"ok": True, "result": worker_json}).encode("utf-8")}]
    )
    redis.kv["device-link:dev-1"] = ("1", None)
    emitted = {}

    class _Manager:
        def emit(self, event, data, room=None, namespace=None):
            emitted.update({"event": event, "data": data, "room": room, "namespace": namespace})

    monkeypatch.setattr("internal.extension.socketio_extension.get_redis_manager", lambda: _Manager())

    result = _service(redis).call_device("dev-1", purpose="/file", payload={"requester": "a1"}, timeout=5)

    assert result == worker_json
    assert emitted["event"] == "device_dispatch"
    assert emitted["room"] == "device-link:dev-1"
    assert emitted["namespace"] == DEVICE_NAMESPACE
    assert emitted["data"]["purpose"] == "/file"
    assert emitted["data"]["payload"] == {"requester": "a1"}
    assert emitted["data"]["request_id"]
    assert redis.pubsub_obj.channels == [f"{DEVICE_RESP_CHANNEL_PREFIX}{emitted['data']['request_id']}"]
    assert redis.pubsub_obj.closed is True


def test_call_device_transport_error_returns_error(monkeypatch):
    redis = _FakeRedis(
        messages=[{"type": "message", "data": json.dumps({"ok": False, "error": "本机 bridge 不可达"}).encode("utf-8")}]
    )
    redis.kv["device-link:dev-1"] = ("1", None)
    monkeypatch.setattr(
        "internal.extension.socketio_extension.get_redis_manager", lambda: mock.Mock(emit=mock.Mock())
    )

    result = _service(redis).call_device("dev-1", purpose="/file", payload={}, timeout=5)

    assert result == {"ok": False, "error": "本机 bridge 不可达"}


def test_call_device_timeout(monkeypatch):
    redis = _FakeRedis(messages=[])
    redis.kv["device-link:dev-1"] = ("1", None)
    monkeypatch.setattr(
        "internal.extension.socketio_extension.get_redis_manager", lambda: mock.Mock(emit=mock.Mock())
    )

    result = _service(redis).call_device("dev-1", purpose="/file", payload={}, timeout=1)

    assert result["ok"] is False
    assert "超时" in result["error"]
    assert redis.pubsub_obj.closed is True


def test_call_device_emit_failure_returns_gateway_error(monkeypatch):
    redis = _FakeRedis()
    redis.kv["device-link:dev-1"] = ("1", None)

    def _boom():
        raise RuntimeError("redis down")

    monkeypatch.setattr("internal.extension.socketio_extension.get_redis_manager", _boom)

    result = _service(redis).call_device("dev-1", purpose="/file", payload={}, timeout=5)

    assert result["ok"] is False
    assert "网关" in result["error"]
    assert redis.pubsub_obj.closed is True


def test_publish_result_sends_to_request_channel():
    redis = _FakeRedis()
    ok = _service(redis).publish_result("rid-1", ok=True, result={"x": 1})

    assert ok is True
    channel, data = redis.published[0]
    assert channel == f"{DEVICE_RESP_CHANNEL_PREFIX}rid-1"
    assert json.loads(data) == {"ok": True, "result": {"x": 1}, "error": ""}
