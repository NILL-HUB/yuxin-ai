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
