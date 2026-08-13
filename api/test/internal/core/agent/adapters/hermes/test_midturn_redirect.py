from internal.core.agent.adapters.hermes.midturn_redirect import (
    build_redirect_decision,
    consume_redirect,
    consume_request_redirect,
    set_redirect,
    set_request_redirect,
)


class _FakeRedis:
    def __init__(self):
        self._data = {}

    def setex(self, key, ttl, value):
        self._data[key] = value

    def get(self, key):
        return self._data.get(key)

    def delete(self, key):
        self._data.pop(key, None)


def test_set_and_consume_redirect(monkeypatch):
    client = _FakeRedis()
    monkeypatch.setattr(
        "internal.core.agent.adapters.hermes.midturn_redirect._redis",
        lambda: client,
    )
    assert set_redirect("conf-1", "只清理回收站") is True
    assert consume_redirect("conf-1") == "只清理回收站"
    assert consume_redirect("conf-1") == ""


def test_consume_redirect_empty_when_unset(monkeypatch):
    monkeypatch.setattr(
        "internal.core.agent.adapters.hermes.midturn_redirect._redis",
        lambda: _FakeRedis(),
    )
    assert consume_redirect("conf-2") == ""


def test_build_redirect_decision_prefix():
    assert build_redirect_decision("新指令") == "redirect:新指令"


def test_set_and_consume_request_redirect_memory(monkeypatch):
    def _no_redis():
        raise RuntimeError("redis down")

    monkeypatch.setattr(
        "internal.core.agent.adapters.hermes.midturn_redirect._redis",
        _no_redis,
    )

    assert set_request_redirect("req-1", "只清理回收站") is True
    assert consume_request_redirect("req-1") == "只清理回收站"
    assert consume_request_redirect("req-1") == ""


def test_set_and_consume_request_redirect_redis(monkeypatch):
    client = _FakeRedis()
    monkeypatch.setattr(
        "internal.core.agent.adapters.hermes.midturn_redirect._redis",
        lambda: client,
    )

    assert set_request_redirect("req-2", "新指令") is True
    assert consume_request_redirect("req-2") == "新指令"
    assert consume_request_redirect("req-2") == ""
