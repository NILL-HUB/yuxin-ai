"""桌面设备注册服务 + 动态 bridge 解析器单元测试。

覆盖「服务端 → 宿主机 worker」断链修复的核心链路：
- DesktopDeviceService.register 幂等 UPSERT
- DesktopDeviceService.resolve_bridge 按账号取默认在线设备并解密 token
- DesktopDeviceService.revoke / list_devices（token 脱敏）
- resolve_desktop_bridge 动态优先 + 静态环境变量回退
"""

from contextlib import contextmanager
from uuid import uuid4

import pytest

from internal.exception import NotFoundException, ValidateErrorException
from internal.model import DesktopDevice
from internal.service import desktop_bridge_resolver as resolver
from internal.service.desktop_device_service import DesktopDeviceService
from internal.service.tool_credential_encryptor import _encrypt_value


class _QueryStub:
    def __init__(self, *, one_or_none_result=None, first_result=None, all_result=None):
        self._one_or_none_result = one_or_none_result
        self._first_result = first_result
        self._all_result = all_result

    def filter(self, *_args, **_kwargs):
        return self

    def order_by(self, *_args, **_kwargs):
        return self

    def one_or_none(self):
        return self._one_or_none_result

    def first(self):
        return self._first_result

    def all(self):
        return self._all_result or []


class _SessionStub:
    def __init__(self, queries=None):
        self._queries = list(queries or [])
        self.added = []
        self.commits = 0

    def query(self, *_args, **_kwargs):
        if self._queries:
            return self._queries.pop(0)
        return _QueryStub()

    def add(self, value):
        self.added.append(value)

    def commit(self):
        self.commits += 1


class _DBStub:
    def __init__(self, session):
        self.session = session

    @contextmanager
    def auto_commit(self):
        yield self.session
        self.session.commit()


def _service(session):
    return DesktopDeviceService(db=_DBStub(session))


def test_register_creates_device_when_absent():
    session = _SessionStub([_QueryStub(one_or_none_result=None)])
    account_id = uuid4()

    result = _service(session).register(
        account_id=account_id,
        device_id="dev-1",
        bridge_origin="http://host.docker.internal:9876/",
        bridge_token="secret-token",
        name="我的电脑",
        platform="win32",
    )

    assert result["device_id"] == "dev-1"
    assert result["bridge_origin"] == "http://host.docker.internal:9876"
    assert result["status"] == "online"
    assert len(session.added) == 1
    created = session.added[0]
    assert isinstance(created, DesktopDevice)
    assert created.account_id == account_id


def test_register_updates_existing_device_idempotently():
    existing = DesktopDevice(
        device_id="dev-1",
        account_id=uuid4(),
        name="旧名",
        platform="win32",
        bridge_origin="http://old:1",
        bridge_token_encrypted=_encrypt_value("old-token"),
        is_default=True,
        status="offline",
    )
    session = _SessionStub([_QueryStub(one_or_none_result=existing)])

    result = _service(session).register(
        account_id=existing.account_id,
        device_id="dev-1",
        bridge_origin="http://host.docker.internal:9876",
        bridge_token="new-token",
        name="新名",
    )

    assert result["bridge_origin"] == "http://host.docker.internal:9876"
    assert existing.bridge_origin == "http://host.docker.internal:9876"
    assert existing.status == "online"
    assert existing.name == "新名"
    assert session.added == [existing]


@pytest.mark.parametrize(
    "kwargs",
    [
        {"device_id": "", "bridge_origin": "http://h:1", "bridge_token": "t"},
        {"device_id": "d", "bridge_origin": "ftp://h:1", "bridge_token": "t"},
        {"device_id": "d", "bridge_origin": "http://h:1", "bridge_token": ""},
    ],
)
def test_register_rejects_invalid_payload(kwargs):
    session = _SessionStub()
    with pytest.raises(ValidateErrorException):
        _service(session).register(account_id=uuid4(), **kwargs)


def test_resolve_bridge_returns_decrypted_token():
    device = DesktopDevice(
        device_id="dev-1",
        account_id=uuid4(),
        name="",
        platform="",
        bridge_origin="http://host.docker.internal:9876/",
        bridge_token_encrypted=_encrypt_value("secret-token"),
        is_default=True,
        status="online",
    )
    session = _SessionStub([_QueryStub(first_result=device)])

    resolved = _service(session).resolve_bridge(device.account_id)

    assert resolved == ("http://host.docker.internal:9876", "secret-token")


def test_resolve_bridge_returns_none_without_online_device():
    session = _SessionStub([_QueryStub(first_result=None)])

    assert _service(session).resolve_bridge(uuid4()) is None


def test_resolve_bridge_returns_none_when_token_undecryptable():
    device = DesktopDevice(
        device_id="dev-1",
        account_id=uuid4(),
        name="",
        platform="",
        bridge_origin="http://host.docker.internal:9876",
        bridge_token_encrypted="not-a-valid-fernet-token",
        is_default=True,
        status="online",
    )
    session = _SessionStub([_QueryStub(first_result=device)])

    assert _service(session).resolve_bridge(device.account_id) is None


def test_list_devices_masks_token():
    device = DesktopDevice(
        device_id="dev-1",
        account_id=uuid4(),
        name="我的电脑",
        platform="win32",
        bridge_origin="http://host.docker.internal:9876",
        bridge_token_encrypted=_encrypt_value("secret-token"),
        is_default=True,
        status="online",
    )
    session = _SessionStub([_QueryStub(all_result=[device])])

    rows = _service(session).list_devices(device.account_id)

    assert len(rows) == 1
    assert "bridge_token" not in rows[0]
    assert "bridge_token_encrypted" not in rows[0]


def test_revoke_marks_device_revoked():
    device = DesktopDevice(
        device_id="dev-1",
        account_id=uuid4(),
        name="",
        platform="",
        bridge_origin="http://host.docker.internal:9876",
        bridge_token_encrypted=_encrypt_value("secret-token"),
        is_default=True,
        status="online",
    )
    session = _SessionStub([_QueryStub(one_or_none_result=device)])

    assert _service(session).revoke(device.account_id, "dev-1") is True
    assert device.status == "revoked"


def test_revoke_raises_when_device_missing():
    session = _SessionStub([_QueryStub(one_or_none_result=None)])

    with pytest.raises(NotFoundException):
        _service(session).revoke(uuid4(), "missing")


def test_resolver_prefers_dynamic_device(monkeypatch):
    monkeypatch.setattr(
        DesktopDeviceService,
        "resolve_bridge",
        lambda self, account_id: ("http://host.docker.internal:9876", "dynamic"),
    )
    monkeypatch.setenv("DESKTOP_BRIDGE_URL", "http://fallback:1")
    monkeypatch.setenv("DESKTOP_BRIDGE_TOKEN", "fallback")

    assert resolver.resolve_desktop_bridge("acct-1") == (
        "http://host.docker.internal:9876",
        "dynamic",
    )


def test_resolver_falls_back_to_static_env(monkeypatch):
    monkeypatch.setattr(DesktopDeviceService, "resolve_bridge", lambda self, account_id: None)
    monkeypatch.setenv("DESKTOP_BRIDGE_URL", "http://fallback:1/")
    monkeypatch.setenv("DESKTOP_BRIDGE_TOKEN", "fallback")

    assert resolver.resolve_desktop_bridge("acct-1") == ("http://fallback:1", "fallback")


def test_resolver_falls_back_when_dynamic_lookup_raises(monkeypatch):
    def _boom(self, account_id):
        raise RuntimeError("db down")

    monkeypatch.setattr(DesktopDeviceService, "resolve_bridge", _boom)
    monkeypatch.setenv("DESKTOP_BRIDGE_URL", "http://fallback:1")
    monkeypatch.setenv("DESKTOP_BRIDGE_TOKEN", "fallback")

    assert resolver.resolve_desktop_bridge("acct-1") == ("http://fallback:1", "fallback")


def test_resolver_skips_dynamic_without_account(monkeypatch):
    called = []

    monkeypatch.setattr(
        DesktopDeviceService,
        "resolve_bridge",
        lambda self, account_id: called.append(account_id) or ("http://x:1", "y"),
    )
    monkeypatch.setenv("DESKTOP_BRIDGE_URL", "http://fallback:1")
    monkeypatch.setenv("DESKTOP_BRIDGE_TOKEN", "fallback")

    assert resolver.resolve_desktop_bridge(None) == ("http://fallback:1", "fallback")
    assert called == []


def test_resolver_returns_none_without_any_source(monkeypatch):
    monkeypatch.delenv("DESKTOP_BRIDGE_URL", raising=False)
    monkeypatch.delenv("DESKTOP_BRIDGE_TOKEN", raising=False)

    assert resolver.resolve_desktop_bridge(None) is None
