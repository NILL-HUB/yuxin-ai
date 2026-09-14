from uuid import uuid4

from internal.service.chunked_upload_session_service import (
    ChunkedUploadSession,
    ChunkedUploadSessionService,
)


class _FakeRedis:
    """最小 Redis 桩：仅实现本服务用到的命令。"""

    def __init__(self):
        self.store: dict = {}
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

    def sadd(self, key, *members):
        bucket = self.store.setdefault(key, set())
        if not isinstance(bucket, set):
            bucket = set()
            self.store[key] = bucket
        added = 0
        for member in members:
            target = member if isinstance(member, bytes) else str(member).encode()
            if target not in bucket:
                bucket.add(target)
                added += 1
        return added

    def smembers(self, key):
        bucket = self.store.get(key)
        if not isinstance(bucket, set):
            return set()
        return {
            member if isinstance(member, bytes) else str(member).encode()
            for member in bucket
        }

    def expire(self, key, ttl):
        if key in self.store:
            self.expires[key] = int(ttl)
            return 1
        return 0

    def srem(self, key, *members):
        bucket = self.store.get(key)
        if not isinstance(bucket, set):
            return 0
        removed = 0
        for member in members:
            target = member if isinstance(member, bytes) else str(member).encode()
            if target in bucket:
                bucket.discard(target)
                removed += 1
        return removed

    def set(self, key, value, nx=False, ex=None):
        if nx and key in self.store:
            return None
        self.store[key] = value if isinstance(value, bytes) else str(value).encode()
        if ex is not None:
            self.expires[key] = int(ex)
        return True


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


def test_mark_received_keeps_all_indices_under_interleaved_writes():
    """多次登记不同分片后，集合应完整保留（SADD 幂等且不丢更新）。"""
    service = _service()
    session = service.create(**_session_kwargs(total_chunks=5, total_size=25 * 1024 * 1024))

    for index in [0, 2, 4, 1, 3]:
        service.mark_received(session.session_id, index)

    loaded = service.get(session.session_id)
    assert loaded is not None
    assert loaded.received_chunks == [0, 1, 2, 3, 4]
    assert loaded.is_complete is True
    assert service.missing_chunks(session.session_id) == []


def test_mark_received_sets_received_key_ttl():
    redis = _FakeRedis()
    service = _service(redis)
    session = service.create(**_session_kwargs())

    service.mark_received(session.session_id, 0)

    assert redis.expires[service._received_key(session.session_id)] == 86400


def test_abort_removes_session_from_tracking_set():
    service = _service()
    session = service.create(**_session_kwargs())

    assert session.session_id in service.active_sessions()
    service.abort(session.session_id)
    assert session.session_id not in service.active_sessions()


def test_is_alive_reflects_session_existence():
    service = _service()
    session = service.create(**_session_kwargs())
    assert service.is_alive(session.session_id) is True

    service.abort(session.session_id)
    assert service.is_alive(session.session_id) is False
