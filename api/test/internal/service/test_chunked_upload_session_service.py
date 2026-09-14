import json
from types import SimpleNamespace
from uuid import uuid4

from internal.service.chunked_upload_session_service import (
    ChunkedUploadSession,
    ChunkedUploadSessionService,
)


class _FakeRedis:
    """最小 Redis 桩：仅实现本服务用到的命令。"""

    def __init__(self):
        self.store: dict[str, bytes] = {}
        self.expires: dict[str, int] = {}

    def setex(self, key, ttl, value):
        self.store[key] = value if isinstance(value, bytes) else str(value).encode()
        self.expires[key] = int(ttl)

    def get(self, key):
        return self.store.get(key)

    def delete(self, *keys):
        for key in keys:
            self.store.pop(key, None)
            self.expires.pop(key, None)

    def exists(self, key):
        return 1 if key in self.store else 0


def _service(redis=None):
    return ChunkedUploadSessionService(redis=redis or _FakeRedis())


def _session_kwargs(**overrides):
    base = dict(
        session_id=str(uuid4()),
        account_id=str(uuid4()),
        filename="promo.mp4",
        total_size=20 * 1024 * 1024,
        chunk_size=5 * 1024 * 1024,
        total_chunks=4,
        fingerprint="abc123",
    )
    base.update(overrides)
    return base


def test_create_session_persists_state_and_returns_model():
    service = _service()
    session = service.create(**_session_kwargs())

    assert isinstance(session, ChunkedUploadSession)
    assert session.total_chunks == 4
    assert session.received_chunks == []

    loaded = service.get(session.session_id)
    assert loaded is not None
    assert loaded.filename == "promo.mp4"
    assert loaded.fingerprint == "abc123"


def test_create_session_sets_ttl():
    redis = _FakeRedis()
    service = _service(redis)
    session = service.create(**_session_kwargs())

    key = service._key(session.session_id)
    assert redis.expires[key] == 86400


def test_get_returns_none_for_unknown_session():
    assert _service().get("missing-session") is None


def test_mark_received_is_idempotent_and_ordered():
    service = _service()
    session = service.create(**_session_kwargs())

    service.mark_received(session.session_id, 0)
    service.mark_received(session.session_id, 1)
    service.mark_received(session.session_id, 1)

    loaded = service.get(session.session_id)
    assert loaded is not None
    assert loaded.received_chunks == [0, 1]
    assert loaded.is_complete is False


def test_mark_received_marks_complete_when_all_present():
    service = _service()
    session = service.create(**_session_kwargs(total_chunks=2, total_size=10 * 1024 * 1024))

    service.mark_received(session.session_id, 0)
    service.mark_received(session.session_id, 1)

    loaded = service.get(session.session_id)
    assert loaded is not None
    assert loaded.is_complete is True


def test_missing_chunks_reports_pending_indices():
    service = _service()
    session = service.create(**_session_kwargs(total_chunks=4))

    service.mark_received(session.session_id, 0)
    service.mark_received(session.session_id, 3)

    assert service.missing_chunks(session.session_id) == [1, 2]


def test_abort_removes_session():
    service = _service()
    session = service.create(**_session_kwargs())

    service.abort(session.session_id)

    assert service.get(session.session_id) is None


def test_register_and_lookup_fingerprint():
    service = _service()
    account_id = str(uuid4())
    upload_file_id = str(uuid4())

    service.register_fingerprint(account_id, "fp-1", upload_file_id)

    assert service.lookup_fingerprint(account_id, "fp-1") == upload_file_id
    assert service.lookup_fingerprint(account_id, "fp-unknown") is None
