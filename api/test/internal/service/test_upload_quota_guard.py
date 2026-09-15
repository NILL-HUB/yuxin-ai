from types import SimpleNamespace
from uuid import uuid4

import pytest

from internal.exception import ForbiddenException
from internal.service.storage_quota_service import StorageQuotaService


class _QueryStub:
    def __init__(self, *, first_result=None, one_or_none_result=None, all_result=None):
        self._first = first_result
        self._one_or_none = one_or_none_result
        self._all = [] if all_result is None else all_result

    def filter(self, *_a, **_kw):
        return self

    def filter_by(self, **_kw):
        return self

    def join(self, *_a, **_kw):
        return self

    def order_by(self, *_a, **_kw):
        return self

    def with_for_update(self):
        return self

    def first(self):
        return self._first

    def one_or_none(self):
        return self._one_or_none

    def all(self):
        return self._all


class _SessionStub:
    def __init__(self, queries=None):
        self._queries = list(queries or [])

    def query(self, *_a, **_kw):
        if self._queries:
            return self._queries.pop(0)
        return _QueryStub()


def _quota_service(session):
    return StorageQuotaService(db=SimpleNamespace(session=session))


def test_upload_guard_rejects_when_quota_exceeded():
    """配额不足时 check_quota 抛错，代理应阻止上传。"""
    account_id = uuid4()
    service = _quota_service(_SessionStub([
        _QueryStub(first_result=None),
        _QueryStub(all_result=[]),
        _QueryStub(one_or_none_result=SimpleNamespace(used_bytes=5 * (1024 ** 3))),
    ]))
    with pytest.raises(ForbiddenException):
        service.check_quota(account_id, incoming_bytes=1)


def test_upload_guard_passes_and_accumulates():
    """配额充足时校验通过，并能在上传后累加用量。"""
    account_id = uuid4()
    service = _quota_service(_SessionStub([
        _QueryStub(first_result=None),
        _QueryStub(all_result=[]),
        _QueryStub(one_or_none_result=None),
    ]))
    service.check_quota(account_id, incoming_bytes=1024)
    created = []
    service.create = lambda model, **kwargs: created.append(kwargs) or SimpleNamespace(**kwargs)
    service.add_usage(account_id, 1024)
    assert created[0]["used_bytes"] == 1024


def test_measure_upload_size_returns_stream_length():
    from internal.service.storage.runtime_storage_service import RuntimeStorageProxy

    class _Stream:
        def __init__(self, data: bytes):
            self._data = data
            self._pos = 0

        def seek(self, offset, whence=0):
            if whence == 2:
                self._pos = len(self._data)
            else:
                self._pos = offset
            return self._pos

        def tell(self):
            return self._pos

    file = SimpleNamespace(stream=_Stream(b"x" * 2048))
    assert RuntimeStorageProxy._measure_upload_size(file) == 2048


def test_measure_upload_size_falls_back_to_zero_without_stream():
    from internal.service.storage.runtime_storage_service import RuntimeStorageProxy

    assert RuntimeStorageProxy._measure_upload_size(SimpleNamespace()) == 0


def test_measure_upload_size_resets_stream_position():
    """测量后流必须复位到起点，否则后端读取会拿到空内容。"""
    from internal.service.storage.runtime_storage_service import RuntimeStorageProxy

    class _Stream:
        def __init__(self, data: bytes):
            self._data = data
            self._pos = 0

        def seek(self, offset, whence=0):
            if whence == 2:
                self._pos = len(self._data)
            else:
                self._pos = offset
            return self._pos

        def tell(self):
            return self._pos

    stream = _Stream(b"y" * 4096)
    file = SimpleNamespace(stream=stream)
    assert RuntimeStorageProxy._measure_upload_size(file) == 4096
    assert stream.tell() == 0


def test_measure_upload_size_resets_position_even_when_tell_fails():
    """tell 失败时仍应尝试复位，不留在非法位置。"""
    from internal.service.storage.runtime_storage_service import RuntimeStorageProxy

    class _BrokenStream:
        def __init__(self):
            self.reset_called = False

        def seek(self, offset, whence=0):
            if whence == 2:
                return 0
            self.reset_called = True
            return 0

        def tell(self):
            raise OSError("boom")

    stream = _BrokenStream()
    assert RuntimeStorageProxy._measure_upload_size(SimpleNamespace(stream=stream)) == 0
    assert stream.reset_called is True


def test_upload_bytes_checks_quota_for_account():
    """upload_bytes 也应对已登录账号做配额校验。"""
    from internal.exception import ForbiddenException
    from internal.service.storage.runtime_storage_service import RuntimeStorageProxy
    from internal.service.storage_quota_service import StorageQuotaService

    account_id = uuid4()
    quota = StorageQuotaService(db=SimpleNamespace(session=_SessionStub([
        _QueryStub(first_result=None),
        _QueryStub(all_result=[]),
        _QueryStub(one_or_none_result=SimpleNamespace(used_bytes=5 * (1024 ** 3))),
    ])))
    proxy = RuntimeStorageProxy(
        upload_file_service=SimpleNamespace(),
        storage_config_service=SimpleNamespace(),
        storage_quota_service=quota,
        db=SimpleNamespace(),
    )
    with pytest.raises(ForbiddenException):
        proxy.upload_bytes(filename="a.txt", content=b"x" * 1024, account_id=account_id)


def test_upload_bytes_skips_quota_for_anonymous():
    """account_id 为 None 时跳过校验（系统产物）。"""
    from internal.service.storage.runtime_storage_service import RuntimeStorageProxy
    from internal.service.storage_quota_service import StorageQuotaService

    calls = []
    quota = StorageQuotaService(db=SimpleNamespace(session=_SessionStub([])))
    quota.check_quota = lambda *a, **k: calls.append("check")
    proxy = RuntimeStorageProxy(
        upload_file_service=SimpleNamespace(),
        storage_config_service=SimpleNamespace(),
        storage_quota_service=quota,
        db=SimpleNamespace(),
    )
    proxy._get_service = lambda *a, **k: SimpleNamespace(
        upload_bytes=lambda **kw: SimpleNamespace(size=10)
    )
    proxy.upload_bytes(filename="a.txt", content=b"x" * 10, account_id=None)
    assert calls == []


def test_upload_file_includes_parse_reserve():
    """素材直传（upload_file）的准入校验须含解析预留。"""
    from internal.entity.storage_quota_entity import PARSE_RESERVE_BYTES
    from internal.service.storage.runtime_storage_service import RuntimeStorageProxy

    calls = []

    class _Quota:
        def check_quota(self, account_id, incoming_bytes):
            calls.append((account_id, incoming_bytes))

        def add_usage(self, account_id, bytes_delta):
            return bytes_delta

    proxy = RuntimeStorageProxy(
        upload_file_service=SimpleNamespace(),
        storage_config_service=SimpleNamespace(),
        storage_quota_service=_Quota(),
        db=SimpleNamespace(),
    )
    proxy._get_service = lambda *a, **k: SimpleNamespace(
        upload_file=lambda file, only_image, account: SimpleNamespace(size=100)
    )
    account = SimpleNamespace(id=uuid4())

    class _Stream:
        def __init__(self, n):
            self._n = n
            self._pos = 0

        def seek(self, offset, whence=0):
            self._pos = self._n if whence == 2 else offset
            return self._pos

        def tell(self):
            return self._pos

    proxy.upload_file(SimpleNamespace(stream=_Stream(100)), account=account)

    assert calls == [(account.id, 100 + PARSE_RESERVE_BYTES)]


def test_upload_bytes_does_not_add_parse_reserve():
    """产物写入路径（upload_bytes）不得掺入解析预留。

    它是帧/Agent 产物的写入通道，每帧都加 8MB 预留会反复卡门槛。
    """
    from internal.entity.storage_quota_entity import PARSE_RESERVE_BYTES
    from internal.service.storage.runtime_storage_service import RuntimeStorageProxy

    calls = []

    class _Quota:
        def check_quota(self, account_id, incoming_bytes):
            calls.append((account_id, incoming_bytes))

        def add_usage(self, account_id, bytes_delta):
            return bytes_delta

    proxy = RuntimeStorageProxy(
        upload_file_service=SimpleNamespace(),
        storage_config_service=SimpleNamespace(),
        storage_quota_service=_Quota(),
        db=SimpleNamespace(),
    )
    proxy._get_service = lambda *a, **k: SimpleNamespace(
        upload_bytes=lambda **kw: SimpleNamespace(key="f.jpg", size=10)
    )
    account_id = uuid4()

    proxy.upload_bytes(filename="f.jpg", content=b"x" * 10, account_id=account_id)

    assert calls == [(account_id, 10)]
    assert calls[0][1] != 10 + PARSE_RESERVE_BYTES
