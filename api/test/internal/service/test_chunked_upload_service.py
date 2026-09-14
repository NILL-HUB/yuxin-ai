from types import SimpleNamespace
from uuid import uuid4

import pytest

from internal.exception import FailException, ValidateErrorException
from internal.service.chunked_upload_service import ChunkedUploadService


class _FakeSessionService:
    def __init__(self):
        self.sessions = {}
        self.fingerprints = {}

    def create(self, **kwargs):
        session = SimpleNamespace(**kwargs, received_chunks=[])
        self.sessions[session.session_id] = session
        return session

    def get(self, session_id):
        return self.sessions.get(session_id)

    def mark_received(self, session_id, index):
        session = self.sessions.get(session_id)
        if session is not None and index not in session.received_chunks:
            session.received_chunks.append(index)
        return session

    def missing_chunks(self, session_id):
        session = self.sessions.get(session_id)
        if session is None:
            return []
        return [i for i in range(session.total_chunks) if i not in session.received_chunks]

    def abort(self, session_id):
        self.sessions.pop(session_id, None)

    def register_fingerprint(self, account_id, fingerprint, upload_file_id):
        self.fingerprints[(account_id, fingerprint)] = upload_file_id

    def lookup_fingerprint(self, account_id, fingerprint):
        return self.fingerprints.get((account_id, fingerprint))


class _FakeStorage:
    def __init__(self):
        self.chunks = {}
        self.merged = []
        self.cleaned = []
        self.copied = []

    def save_chunk(self, session_id, index, content):
        self.chunks[(session_id, index)] = content
        return len(content)

    def merge_chunks(self, session_id, total_chunks, target_key):
        self.merged.append((session_id, total_chunks, target_key))
        return 1234, "digest-abc"

    def cleanup_session(self, session_id):
        self.cleaned.append(session_id)

    def copy_object(self, source_key, target_key):
        self.copied.append((source_key, target_key))
        return 999


class _FakeUploadFileService:
    def __init__(self):
        self.created = []

    def create_upload_file(self, **kwargs):
        record = SimpleNamespace(id=uuid4(), **kwargs)
        self.created.append(kwargs)
        return record


def _service(*, storage=None, session_service=None, upload_file_service=None,
             max_size=100 * 1024 * 1024, quota_error=None):
    quota_calls = []

    class _Quota:
        def resolve_max_file_size_bytes(self, account_id):
            return max_size

        def check_quota(self, account_id, incoming_bytes):
            quota_calls.append((account_id, incoming_bytes))
            if quota_error:
                raise quota_error

        def add_usage(self, account_id, bytes_delta):
            return bytes_delta

    service = ChunkedUploadService(
        db=SimpleNamespace(),
        storage=storage or _FakeStorage(),
        session_service=session_service or _FakeSessionService(),
        upload_file_service=upload_file_service or _FakeUploadFileService(),
        storage_quota_service=_Quota(),
    )
    return service, quota_calls


def _account():
    return SimpleNamespace(id=uuid4())


def test_init_rejects_file_exceeding_plan_limit():
    service, _calls = _service(max_size=1024)

    with pytest.raises(ValidateErrorException):
        service.init(
            account=_account(), filename="big.mp4", total_size=2048,
            chunk_size=512, total_chunks=4, fingerprint="fp",
        )


def test_init_checks_quota_and_returns_session():
    service, calls = _service()
    account = _account()

    result = service.init(
        account=account, filename="ok.mp4", total_size=1024,
        chunk_size=512, total_chunks=2, fingerprint="fp-1",
    )

    assert result["session_id"]
    assert result["total_chunks"] == 2
    assert calls == [(account.id, 1024)]


def test_init_returns_instant_hit_when_fingerprint_matches():
    session_service = _FakeSessionService()
    existing_id = str(uuid4())
    account = _account()
    session_service.register_fingerprint(str(account.id), "fp-hit", existing_id)

    service, _calls = _service(session_service=session_service)

    result = service.init(
        account=account, filename="dup.mp4", total_size=1024,
        chunk_size=512, total_chunks=2, fingerprint="fp-hit",
    )

    assert result["instant"] is True
    assert result["upload_file_id"] == existing_id


def test_init_rejects_mismatched_chunk_count():
    service, _calls = _service()

    with pytest.raises(ValidateErrorException):
        service.init(
            account=_account(), filename="a.mp4", total_size=1024,
            chunk_size=512, total_chunks=5, fingerprint="fp",
        )


def test_save_chunk_marks_session():
    session_service = _FakeSessionService()
    service, _calls = _service(session_service=session_service)
    account = _account()
    session_id = service.init(
        account=account, filename="a.mp4", total_size=1024,
        chunk_size=512, total_chunks=2, fingerprint="fp",
    )["session_id"]

    result = service.save_chunk(session_id=session_id, index=0, content=b"x" * 512)

    assert result["received"] == 1
    assert session_service.sessions[session_id].received_chunks == [0]


def test_save_chunk_rejects_unknown_session():
    service, _calls = _service()

    with pytest.raises(FailException):
        service.save_chunk(session_id="nope", index=0, content=b"x")


def test_save_chunk_rejects_out_of_range_index():
    session_service = _FakeSessionService()
    service, _calls = _service(session_service=session_service)
    account = _account()
    session_id = service.init(
        account=account, filename="a.mp4", total_size=1024,
        chunk_size=512, total_chunks=2, fingerprint="fp",
    )["session_id"]

    with pytest.raises(ValidateErrorException):
        service.save_chunk(session_id=session_id, index=5, content=b"x")


def test_complete_merges_persists_and_cleans_up():
    session_service = _FakeSessionService()
    storage = _FakeStorage()
    upload_file_service = _FakeUploadFileService()
    service, _calls = _service(
        storage=storage, session_service=session_service,
        upload_file_service=upload_file_service,
    )
    account = _account()
    session_id = service.init(
        account=account, filename="final.mp4", total_size=1024,
        chunk_size=512, total_chunks=2, fingerprint="fp-final",
    )["session_id"]
    service.save_chunk(session_id=session_id, index=0, content=b"a" * 512)
    service.save_chunk(session_id=session_id, index=1, content=b"b" * 512)

    result = service.complete(session_id=session_id, account=account)

    assert result["size"] == 1234
    assert storage.merged and storage.merged[0][1] == 2
    assert upload_file_service.created[0]["size"] == 1234
    assert upload_file_service.created[0]["hash"] == "digest-abc"
    assert upload_file_service.created[0]["storage_backend"] == "local"
    assert storage.cleaned == [session_id]
    assert session_service.get(session_id) is None
    assert session_service.lookup_fingerprint(str(account.id), "fp-final") is not None


def test_complete_rejects_when_chunks_missing():
    session_service = _FakeSessionService()
    service, _calls = _service(session_service=session_service)
    account = _account()
    session_id = service.init(
        account=account, filename="partial.mp4", total_size=1024,
        chunk_size=512, total_chunks=2, fingerprint="fp",
    )["session_id"]
    service.save_chunk(session_id=session_id, index=0, content=b"a" * 512)

    with pytest.raises(FailException):
        service.complete(session_id=session_id, account=account)


def test_complete_rejects_other_account():
    session_service = _FakeSessionService()
    service, _calls = _service(session_service=session_service)
    owner = _account()
    session_id = service.init(
        account=owner, filename="a.mp4", total_size=1024,
        chunk_size=512, total_chunks=2, fingerprint="fp",
    )["session_id"]

    with pytest.raises(FailException):
        service.complete(session_id=session_id, account=_account())


def test_status_reports_progress():
    session_service = _FakeSessionService()
    service, _calls = _service(session_service=session_service)
    account = _account()
    session_id = service.init(
        account=account, filename="a.mp4", total_size=1024,
        chunk_size=512, total_chunks=2, fingerprint="fp",
    )["session_id"]
    service.save_chunk(session_id=session_id, index=0, content=b"a" * 512)

    status = service.status(session_id=session_id, account=account)

    assert status["received_chunks"] == [0]
    assert status["missing_chunks"] == [1]
    assert status["is_complete"] is False


def test_abort_cleans_chunks_and_session():
    session_service = _FakeSessionService()
    storage = _FakeStorage()
    service, _calls = _service(storage=storage, session_service=session_service)
    account = _account()
    session_id = service.init(
        account=account, filename="x.mp4", total_size=1024,
        chunk_size=512, total_chunks=2, fingerprint="fp",
    )["session_id"]

    service.abort(session_id=session_id, account=account)

    assert storage.cleaned == [session_id]
    assert session_service.get(session_id) is None


class _FakeQuery:
    def __init__(self, record):
        self._record = record

    def filter(self, *args, **kwargs):
        return self

    def first(self):
        return self._record


class _FakeDbSession:
    def __init__(self, record):
        self._record = record

    def query(self, *args, **kwargs):
        return _FakeQuery(self._record)


class _FakeDb:
    def __init__(self, record):
        self.session = _FakeDbSession(record)


def test_instant_upload_copies_object_and_creates_record():
    storage = _FakeStorage()
    upload_file_service = _FakeUploadFileService()
    account = _account()
    source = SimpleNamespace(
        id=uuid4(), account_id=account.id, name="src.mp4",
        key="2024/01/01/src.mp4", extension="mp4",
        mime_type="video/mp4", hash="hash-src",
    )
    service, _calls = _service(storage=storage, upload_file_service=upload_file_service)
    service.db = _FakeDb(source)

    result = service.instant_upload(
        account=account, upload_file_id=str(source.id), fingerprint="fp-source"
    )

    assert result["size"] == 999
    assert storage.copied and storage.copied[0][0] == source.key
    assert upload_file_service.created[0]["size"] == 999
    assert upload_file_service.created[0]["storage_backend"] == "local"


def test_instant_upload_rejects_other_account():
    """秒传必须先校验归属，防止复制他人文件。"""
    from uuid import uuid4 as _uuid4

    class _Query:
        def filter(self, *_a, **_kw):
            return self

        def first(self):
            return SimpleNamespace(
                id=_uuid4(), account_id=_uuid4(),  # 属于另一个账号
                key="2026/09/14/other.mp4", name="other.mp4",
                extension="mp4", mime_type="video/mp4", size=10, hash="h",
            )

    service, _calls = _service()
    service.db = SimpleNamespace(session=SimpleNamespace(query=lambda *_a, **_kw: _Query()))
    account = _account()

    with pytest.raises(FailException):
        service.instant_upload(account=account, upload_file_id=str(_uuid4()), fingerprint="fp")


def test_instant_upload_rejects_invalid_identifier():
    service, _calls = _service()

    with pytest.raises(ValidateErrorException):
        service.instant_upload(account=_account(), upload_file_id="not-a-uuid", fingerprint="fp")


def test_instant_upload_checks_quota_before_copy():
    """秒传复制前必须做配额校验。"""
    from internal.exception import ForbiddenException
    from uuid import uuid4 as _uuid4

    account = _account()

    class _Query:
        def filter(self, *_a, **_kw):
            return self

        def first(self):
            return SimpleNamespace(
                id=_uuid4(), account_id=account.id,
                key="2026/09/14/src.mp4", name="src.mp4",
                extension="mp4", mime_type="video/mp4", size=8192, hash="h",
            )

    service, calls = _service(quota_error=ForbiddenException("quota exceeded"))
    service.db = SimpleNamespace(session=SimpleNamespace(query=lambda *_a, **_kw: _Query()))

    with pytest.raises(ForbiddenException):
        service.instant_upload(account=account, upload_file_id=str(_uuid4()), fingerprint="fp")


def test_init_rejects_non_positive_chunk_size():
    service, _calls = _service()

    with pytest.raises(ValidateErrorException):
        service.init(
            account=_account(), filename="a.mp4", total_size=1024,
            chunk_size=0, total_chunks=1, fingerprint="fp",
        )


def test_save_chunk_rejects_empty_content():
    session_service = _FakeSessionService()
    service, _calls = _service(session_service=session_service)
    account = _account()
    session_id = service.init(
        account=account, filename="a.mp4", total_size=1024,
        chunk_size=512, total_chunks=2, fingerprint="fp",
    )["session_id"]

    with pytest.raises(ValidateErrorException):
        service.save_chunk(session_id=session_id, index=0, content=b"")


def test_status_rejects_other_account():
    session_service = _FakeSessionService()
    service, _calls = _service(session_service=session_service)
    session_id = service.init(
        account=_account(), filename="a.mp4", total_size=1024,
        chunk_size=512, total_chunks=2, fingerprint="fp",
    )["session_id"]

    with pytest.raises(FailException):
        service.status(session_id=session_id, account=_account())


def test_abort_rejects_other_account():
    session_service = _FakeSessionService()
    service, _calls = _service(session_service=session_service)
    session_id = service.init(
        account=_account(), filename="a.mp4", total_size=1024,
        chunk_size=512, total_chunks=2, fingerprint="fp",
    )["session_id"]

    with pytest.raises(FailException):
        service.abort(session_id=session_id, account=_account())


def test_complete_recovers_when_persist_fails():
    """落库失败时应回收已合并的目标对象，且会话不被销毁（可重试）。"""
    session_service = _FakeSessionService()
    storage = _FakeStorage()
    storage.deleted = []

    def _delete_object(key):
        storage.deleted.append(key)
        return True

    storage.delete_object = _delete_object

    class _BrokenUploadFileService:
        def create_upload_file(self, **kwargs):
            raise RuntimeError("db down")

    service, _calls = _service(
        storage=storage, session_service=session_service,
        upload_file_service=_BrokenUploadFileService(),
    )
    account = _account()
    session_id = service.init(
        account=account, filename="a.mp4", total_size=1024,
        chunk_size=512, total_chunks=2, fingerprint="fp-fail",
    )["session_id"]
    service.save_chunk(session_id=session_id, index=0, content=b"a" * 512)
    service.save_chunk(session_id=session_id, index=1, content=b"b" * 512)

    with pytest.raises(RuntimeError):
        service.complete(session_id=session_id, account=account)

    assert storage.deleted, "落库失败应回收合并产物"
    assert session_service.get(session_id) is not None, "会话应保留以便重试"


def test_complete_registers_document_when_knowledge_base_given(monkeypatch):
    session_service = _FakeSessionService()
    service, _calls = _service(session_service=session_service)
    account = _account()
    session_id = service.init(
        account=account, filename="kb.mp4", total_size=1024,
        chunk_size=512, total_chunks=2, fingerprint="fp-kb",
    )["session_id"]
    service.save_chunk(session_id=session_id, index=0, content=b"a" * 512)
    service.save_chunk(session_id=session_id, index=1, content=b"b" * 512)

    recorded = {}

    class _Knowledge:
        def assert_upload_allowed(self, knowledge_base_id, extension, account):
            return None

        def create_document_from_upload_file(self, **kwargs):
            recorded.update(kwargs)
            return SimpleNamespace(id=uuid4())

    monkeypatch.setattr(service, "_knowledge_base_service", lambda: _Knowledge())

    result = service.complete(
        session_id=session_id, account=account, knowledge_base_id=str(uuid4())
    )

    assert "document_id" in result
    assert recorded["upload_file"].size == 1234


def test_complete_rejects_mismatched_base_type_before_merge(monkeypatch):
    """板块类型不匹配时应在合并前拒绝，不产生合并产物与 UploadFile。"""
    from internal.exception import ValidateErrorException

    session_service = _FakeSessionService()
    storage = _FakeStorage()
    upload_file_service = _FakeUploadFileService()
    service, _calls = _service(
        storage=storage, session_service=session_service,
        upload_file_service=upload_file_service,
    )
    account = _account()
    session_id = service.init(
        account=account, filename="promo.mp4", total_size=1024,
        chunk_size=512, total_chunks=2, fingerprint="fp-type",
    )["session_id"]
    service.save_chunk(session_id=session_id, index=0, content=b"a" * 512)
    service.save_chunk(session_id=session_id, index=1, content=b"b" * 512)

    class _Knowledge:
        def assert_upload_allowed(self, knowledge_base_id, extension, account):
            raise ValidateErrorException("板块类型不允许")

    monkeypatch.setattr(service, "_knowledge_base_service", lambda: _Knowledge())

    with pytest.raises(ValidateErrorException):
        service.complete(
            session_id=session_id, account=account, knowledge_base_id=str(uuid4())
        )

    assert storage.merged == [], "不应执行合并"
    assert upload_file_service.created == [], "不应创建 UploadFile 记录"
    assert session_service.get(session_id) is not None, "会话应保留"


def test_complete_rolls_back_when_document_creation_fails(monkeypatch):
    """建档失败时应回滚合并产物与 UploadFile 记录，并保留会话可重试。"""
    session_service = _FakeSessionService()
    storage = _FakeStorage()
    storage.deleted = []
    storage.delete_object = lambda key: storage.deleted.append(key) or True
    upload_file_service = _FakeUploadFileService()
    upload_file_service.deleted = []
    upload_file_service.delete = lambda instance: upload_file_service.deleted.append(instance) or instance

    service, _calls = _service(
        storage=storage, session_service=session_service,
        upload_file_service=upload_file_service,
    )
    account = _account()
    session_id = service.init(
        account=account, filename="a.mp4", total_size=1024,
        chunk_size=512, total_chunks=2, fingerprint="fp-roll",
    )["session_id"]
    service.save_chunk(session_id=session_id, index=0, content=b"a" * 512)
    service.save_chunk(session_id=session_id, index=1, content=b"b" * 512)

    class _Knowledge:
        def assert_upload_allowed(self, knowledge_base_id, extension, account):
            return None

        def create_document_from_upload_file(self, **kwargs):
            raise RuntimeError("建档失败")

    monkeypatch.setattr(service, "_knowledge_base_service", lambda: _Knowledge())

    with pytest.raises(RuntimeError):
        service.complete(
            session_id=session_id, account=account, knowledge_base_id=str(uuid4())
        )

    assert storage.deleted, "应回收合并产物"
    assert upload_file_service.deleted, "应删除 UploadFile 记录"
    assert session_service.get(session_id) is not None, "会话应保留可重试"

