from types import SimpleNamespace
from uuid import uuid4

import pytest

from internal.entity.storage_quota_entity import PARSE_RESERVE_BYTES
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

    def claim_for_completion(self, session_id, ttl_seconds=300):
        return True

    def release_claim(self, session_id):
        return None


class _FakeStorage:
    """分片暂存与合并的替身（永远本地）。"""

    def __init__(self, merge_error=None):
        self.chunks = {}
        self.merged = []
        self.cleaned = []
        self._merge_error = merge_error

    def save_chunk(self, session_id, index, content):
        self.chunks[(session_id, index)] = content
        return len(content)

    def merge_chunks_to_file(self, *, session_id, total_chunks, target_path):
        if self._merge_error is not None:
            raise self._merge_error
        self.merged.append((session_id, total_chunks, target_path))
        with open(target_path, "wb") as fh:
            fh.write(b"x" * 1234)
        return 1234, "digest-abc"

    def cleanup_session(self, session_id):
        self.cleaned.append(session_id)


class _FakeRuntimeStorage:
    """运行时存储代理替身：负责产物落盘与对象管理，跟随激活后端。"""

    def __init__(self, backend="local", download_error=None):
        self.backend = backend
        self.uploaded = []
        self.copied = []
        self.deleted = []
        self.downloaded = []
        self._download_error = download_error

    def active_backend(self):
        return self.backend

    def upload_local_file(self, *, source_path, target_key, mime_type=None):
        self.uploaded.append((source_path, target_key))
        return target_key

    def copy_object(self, source_key, target_key, backend=None):
        self.copied.append((source_key, target_key))
        return 999

    def delete_object(self, key, backend=None):
        self.deleted.append(key)
        return True

    def download_file(self, key, target_file_path, backend=None):
        if self._download_error is not None:
            raise self._download_error
        self.downloaded.append((key, target_file_path))
        with open(target_file_path, "wb") as fh:
            fh.write(b"payload")


class _FakeUploadFileService:
    def __init__(self):
        self.created = []

    def create_upload_file(self, **kwargs):
        record = SimpleNamespace(id=uuid4(), **kwargs)
        self.created.append(kwargs)
        return record


def _service(*, storage=None, runtime_storage=None, session_service=None,
             upload_file_service=None, max_size=100 * 1024 * 1024, quota_error=None,
             backend="local"):
    quota_calls = []

    class _Quota:
        def resolve_max_file_size_bytes(self, account_id):
            return max_size

        def check_quota(self, account_id, incoming_bytes, reserve_bytes=0):
            quota_calls.append(("check", account_id, incoming_bytes, reserve_bytes))
            if quota_error:
                raise quota_error

        def consume_quota(self, account_id, incoming_bytes, reserve_bytes=0):
            quota_calls.append(("consume", account_id, incoming_bytes, reserve_bytes))
            if quota_error:
                raise quota_error
            return incoming_bytes

        def add_usage(self, account_id, bytes_delta):
            quota_calls.append(("add", account_id, bytes_delta))
            return bytes_delta

        def release_usage(self, account_id, bytes_delta):
            quota_calls.append(("release", account_id, bytes_delta))
            return 0

    service = ChunkedUploadService(
        db=SimpleNamespace(),
        storage=storage or _FakeStorage(),
        runtime_storage=runtime_storage or _FakeRuntimeStorage(backend=backend),
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
    assert calls == [("check", account.id, 1024, 0)]


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

    result = service.save_chunk(session_id=session_id, index=0, content=b"x" * 512, account=account)

    assert result["received"] == 1
    assert session_service.sessions[session_id].received_chunks == [0]


def test_save_chunk_rejects_unknown_session():
    service, _calls = _service()

    with pytest.raises(FailException):
        service.save_chunk(session_id="nope", index=0, content=b"x", account=_account())


def test_save_chunk_rejects_out_of_range_index():
    session_service = _FakeSessionService()
    service, _calls = _service(session_service=session_service)
    account = _account()
    session_id = service.init(
        account=account, filename="a.mp4", total_size=1024,
        chunk_size=512, total_chunks=2, fingerprint="fp",
    )["session_id"]

    with pytest.raises(ValidateErrorException):
        service.save_chunk(session_id=session_id, index=5, content=b"x", account=account)


def test_complete_uploads_to_active_backend_when_cos_activated():
    """激活后端为 cos 时，分片产物必须落到 cos（而非本地），并如实记录 storage_backend。"""
    session_service = _FakeSessionService()
    storage = _FakeStorage()
    runtime_storage = _FakeRuntimeStorage(backend="cos")
    upload_file_service = _FakeUploadFileService()
    service, _calls = _service(
        storage=storage, runtime_storage=runtime_storage,
        session_service=session_service, upload_file_service=upload_file_service,
    )
    account = _account()
    session_id = service.init(
        account=account, filename="big.mp4", total_size=1024,
        chunk_size=512, total_chunks=2, fingerprint="fp-cos",
    )["session_id"]
    service.save_chunk(session_id=session_id, index=0, content=b"a" * 512, account=account)
    service.save_chunk(session_id=session_id, index=1, content=b"b" * 512, account=account)

    result = service.complete(session_id=session_id, account=account)

    # 关键断言：产物经激活后端落盘，而不是写死本地
    assert runtime_storage.uploaded, "产物必须经激活后端落盘"
    _, target_key = runtime_storage.uploaded[0]
    assert target_key == result["key"]
    assert upload_file_service.created[0]["storage_backend"] == "cos"
    assert result["size"] == 1234


def test_complete_cleans_local_temp_file_after_upload():
    """落盘后必须清理本地合并临时文件，避免磁盘泄漏。"""
    import os

    session_service = _FakeSessionService()
    runtime_storage = _FakeRuntimeStorage(backend="cos")
    service, _calls = _service(runtime_storage=runtime_storage, session_service=session_service)
    account = _account()
    session_id = service.init(
        account=account, filename="t.mp4", total_size=1024,
        chunk_size=512, total_chunks=2, fingerprint="fp-temp",
    )["session_id"]
    service.save_chunk(session_id=session_id, index=0, content=b"a" * 512, account=account)
    service.save_chunk(session_id=session_id, index=1, content=b"b" * 512, account=account)

    service.complete(session_id=session_id, account=account)

    temp_path, _ = runtime_storage.uploaded[0]
    assert not os.path.exists(temp_path), "合并临时文件应已清理"


def test_complete_recovers_object_when_upload_to_backend_fails():
    """落盘失败必须回收目标对象、释放预占配额，并保留会话可重试。"""
    session_service = _FakeSessionService()

    class _FailingRuntimeStorage(_FakeRuntimeStorage):
        def upload_local_file(self, *, source_path, target_key, mime_type=None):
            raise RuntimeError("cos down")

    runtime_storage = _FailingRuntimeStorage(backend="cos")
    service, calls = _service(runtime_storage=runtime_storage, session_service=session_service)
    account = _account()
    session_id = service.init(
        account=account, filename="x.mp4", total_size=1024,
        chunk_size=512, total_chunks=2, fingerprint="fp-upfail",
    )["session_id"]
    calls.clear()
    service.save_chunk(session_id=session_id, index=0, content=b"a" * 512, account=account)
    service.save_chunk(session_id=session_id, index=1, content=b"b" * 512, account=account)

    with pytest.raises(RuntimeError):
        service.complete(session_id=session_id, account=account)

    assert runtime_storage.deleted, "落盘失败应回收目标对象"
    assert ("release", account.id, 1024) in calls, "应释放预占配额"
    assert session_service.get(session_id) is not None, "会话应保留可重试"


def test_instant_upload_cross_backend_copies_via_active_backend():
    """源文件在旧后端（local）而激活后端为 cos 时，应下载后落到 cos，不留在本地。"""
    runtime_storage = _FakeRuntimeStorage(backend="cos")
    upload_file_service = _FakeUploadFileService()
    account = _account()
    source = SimpleNamespace(
        id=uuid4(), account_id=account.id, name="legacy.mp4",
        key="2024/01/01/legacy.mp4", extension="mp4",
        mime_type="video/mp4", hash="h", size=7, storage_backend="local",
    )
    service, _calls = _service(
        runtime_storage=runtime_storage, upload_file_service=upload_file_service
    )
    service.db = _FakeDb(source)

    result = service.instant_upload(
        account=account, upload_file_id=str(source.id), fingerprint="fp-cross"
    )

    assert runtime_storage.downloaded, "跨后端必须先从旧后端下载"
    assert runtime_storage.uploaded, "跨后端必须再落到激活后端"
    assert not runtime_storage.copied, "跨后端不应走同后端复制"
    assert upload_file_service.created[0]["storage_backend"] == "cos"
    assert result["size"] == 7


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
    service.save_chunk(session_id=session_id, index=0, content=b"a" * 512, account=account)
    service.save_chunk(session_id=session_id, index=1, content=b"b" * 512, account=account)

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
    service.save_chunk(session_id=session_id, index=0, content=b"a" * 512, account=account)

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
    service.save_chunk(session_id=session_id, index=0, content=b"a" * 512, account=account)

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
    runtime_storage = _FakeRuntimeStorage()
    upload_file_service = _FakeUploadFileService()
    account = _account()
    source = SimpleNamespace(
        id=uuid4(), account_id=account.id, name="src.mp4",
        key="2024/01/01/src.mp4", extension="mp4",
        mime_type="video/mp4", hash="hash-src", storage_backend="local",
    )
    service, _calls = _service(runtime_storage=runtime_storage, upload_file_service=upload_file_service)
    service.db = _FakeDb(source)

    result = service.instant_upload(
        account=account, upload_file_id=str(source.id), fingerprint="fp-source"
    )

    assert result["size"] == 999
    assert runtime_storage.copied and runtime_storage.copied[0][0] == source.key
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

    assert calls == [("consume", account.id, 8192, PARSE_RESERVE_BYTES)]


def test_complete_consumes_quota_atomically_instead_of_add_usage():
    """complete 必须用 consume_quota（锁内校验+累加）而非 add_usage，避免并发超卖。"""
    session_service = _FakeSessionService()
    storage = _FakeStorage()
    service, calls = _service(storage=storage, session_service=session_service)
    account = _account()
    session_id = service.init(
        account=account, filename="final.mp4", total_size=1024,
        chunk_size=512, total_chunks=2, fingerprint="fp-atomic",
    )["session_id"]
    calls.clear()
    service.save_chunk(session_id=session_id, index=0, content=b"a" * 512, account=account)
    service.save_chunk(session_id=session_id, index=1, content=b"b" * 512, account=account)

    service.complete(session_id=session_id, account=account)

    assert calls == [("consume", account.id, 1024, PARSE_RESERVE_BYTES)]
    assert not any(call[0] == "add" for call in calls)


def test_complete_releases_reserved_quota_and_keeps_session_when_merge_fails():
    """合并失败：必须释放已预占的配额、不清理分片目录、保留会话供用户重试。"""
    session_service = _FakeSessionService()
    storage = _FakeStorage(merge_error=OSError("disk exploded"))
    service, calls = _service(storage=storage, session_service=session_service)
    account = _account()
    session_id = service.init(
        account=account, filename="big.mp4", total_size=1024,
        chunk_size=512, total_chunks=2, fingerprint="fp-mergefail",
    )["session_id"]
    calls.clear()
    service.save_chunk(session_id=session_id, index=0, content=b"a" * 512, account=account)
    service.save_chunk(session_id=session_id, index=1, content=b"b" * 512, account=account)

    with pytest.raises(OSError):
        service.complete(session_id=session_id, account=account)

    assert calls == [
        ("consume", account.id, 1024, PARSE_RESERVE_BYTES),
        ("release", account.id, 1024),
    ]
    assert storage.cleaned == []
    assert session_service.get(session_id) is not None


def test_complete_releases_reserved_quota_when_declaring_document_fails():
    """建档失败：释放预占配额，并回滚已合并对象与 UploadFile 记录。"""
    session_service = _FakeSessionService()
    runtime_storage = _FakeRuntimeStorage()
    upload_file_service = _FakeUploadFileService()
    service, calls = _service(
        runtime_storage=runtime_storage, session_service=session_service,
        upload_file_service=upload_file_service,
    )
    account = _account()
    session_id = service.init(
        account=account, filename="final.mp4", total_size=1024,
        chunk_size=512, total_chunks=2, fingerprint="fp-docfail",
    )["session_id"]
    calls.clear()
    service.save_chunk(session_id=session_id, index=0, content=b"a" * 512, account=account)
    service.save_chunk(session_id=session_id, index=1, content=b"b" * 512, account=account)

    class _KnowledgeService:
        def assert_upload_allowed(self, *args, **kwargs):
            return SimpleNamespace(id=uuid4())

        def create_document_from_upload_file(self, **kwargs):
            raise FailException("建档失败")

    service._knowledge_base_service = lambda: _KnowledgeService()

    with pytest.raises(FailException):
        service.complete(
            session_id=session_id, account=account, knowledge_base_id=str(uuid4())
        )

    assert ("release", account.id, 1024) in calls
    assert runtime_storage.uploaded, "落盘应已发生"
    assert runtime_storage.deleted, "应回收已落盘产物"
    assert session_service.get(session_id) is not None


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
        service.save_chunk(session_id=session_id, index=0, content=b"", account=account)


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
    """落库失败时应回收已落盘的目标对象，且会话不被销毁（可重试）。"""
    session_service = _FakeSessionService()
    runtime_storage = _FakeRuntimeStorage()

    class _BrokenUploadFileService:
        def create_upload_file(self, **kwargs):
            raise RuntimeError("db down")

    service, _calls = _service(
        runtime_storage=runtime_storage, session_service=session_service,
        upload_file_service=_BrokenUploadFileService(),
    )
    account = _account()
    session_id = service.init(
        account=account, filename="a.mp4", total_size=1024,
        chunk_size=512, total_chunks=2, fingerprint="fp-fail",
    )["session_id"]
    service.save_chunk(session_id=session_id, index=0, content=b"a" * 512, account=account)
    service.save_chunk(session_id=session_id, index=1, content=b"b" * 512, account=account)

    with pytest.raises(RuntimeError):
        service.complete(session_id=session_id, account=account)

    assert runtime_storage.uploaded, "应已落盘"
    assert runtime_storage.deleted, "落库失败应回收产物"
    assert session_service.get(session_id) is not None, "会话应保留以便重试"


def test_complete_registers_document_when_knowledge_base_given(monkeypatch):
    session_service = _FakeSessionService()
    service, _calls = _service(session_service=session_service)
    account = _account()
    session_id = service.init(
        account=account, filename="kb.mp4", total_size=1024,
        chunk_size=512, total_chunks=2, fingerprint="fp-kb",
    )["session_id"]
    service.save_chunk(session_id=session_id, index=0, content=b"a" * 512, account=account)
    service.save_chunk(session_id=session_id, index=1, content=b"b" * 512, account=account)

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
    service.save_chunk(session_id=session_id, index=0, content=b"a" * 512, account=account)
    service.save_chunk(session_id=session_id, index=1, content=b"b" * 512, account=account)

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
    """建档失败时应回滚已落盘产物与 UploadFile 记录，并保留会话可重试。"""
    session_service = _FakeSessionService()
    runtime_storage = _FakeRuntimeStorage()
    upload_file_service = _FakeUploadFileService()
    upload_file_service.deleted = []
    upload_file_service.delete = lambda instance: upload_file_service.deleted.append(instance) or instance

    service, _calls = _service(
        runtime_storage=runtime_storage, session_service=session_service,
        upload_file_service=upload_file_service,
    )
    account = _account()
    session_id = service.init(
        account=account, filename="a.mp4", total_size=1024,
        chunk_size=512, total_chunks=2, fingerprint="fp-roll",
    )["session_id"]
    service.save_chunk(session_id=session_id, index=0, content=b"a" * 512, account=account)
    service.save_chunk(session_id=session_id, index=1, content=b"b" * 512, account=account)

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

    assert runtime_storage.deleted, "应回收已落盘产物"
    assert upload_file_service.deleted, "应删除 UploadFile 记录"
    assert session_service.get(session_id) is not None, "会话应保留可重试"


def test_instant_upload_creates_document_when_knowledge_base_given(monkeypatch):
    """秒传传入 knowledge_base_id 时应建档并回填 document_id。"""
    from uuid import uuid4 as _uuid4

    account = _account()

    class _Query:
        def filter(self, *_a, **_kw):
            return self

        def first(self):
            return SimpleNamespace(
                id=_uuid4(), account_id=account.id, key="2026/09/14/src.mp4",
                name="src.mp4", extension="mp4", mime_type="video/mp4",
                size=1024, hash="h",
            )

    service, _calls = _service()
    service.db = SimpleNamespace(session=SimpleNamespace(query=lambda *_a, **_kw: _Query()))

    recorded = {}

    class _Knowledge:
        def assert_upload_allowed(self, knowledge_base_id, extension, account):
            recorded["precheck"] = (knowledge_base_id, extension)

        def create_document_from_upload_file(self, **kwargs):
            recorded["created"] = kwargs
            return SimpleNamespace(id=_uuid4())

    monkeypatch.setattr(service, "_knowledge_base_service", lambda: _Knowledge())

    result = service.instant_upload(
        account=account, upload_file_id=str(_uuid4()),
        fingerprint="fp-kb-instant", knowledge_base_id=str(_uuid4()),
    )

    assert "document_id" in result
    assert "precheck" in recorded
    assert "created" in recorded


def test_instant_upload_rolls_back_when_document_creation_fails(monkeypatch):
    """秒传建档失败时应回滚复制产物与 UploadFile 记录。"""
    from uuid import uuid4 as _uuid4

    account = _account()

    class _Query:
        def filter(self, *_a, **_kw):
            return self

        def first(self):
            return SimpleNamespace(
                id=_uuid4(), account_id=account.id, key="2026/09/14/src.mp4",
                name="src.mp4", extension="mp4", mime_type="video/mp4",
                size=1024, hash="h",
            )

    runtime_storage = _FakeRuntimeStorage()
    upload_file_service = _FakeUploadFileService()
    upload_file_service.deleted = []
    upload_file_service.delete = lambda inst: upload_file_service.deleted.append(inst) or inst

    service, _calls = _service(runtime_storage=runtime_storage, upload_file_service=upload_file_service)
    service.db = SimpleNamespace(session=SimpleNamespace(query=lambda *_a, **_kw: _Query()))

    class _Knowledge:
        def assert_upload_allowed(self, *_a, **_kw):
            return None

        def create_document_from_upload_file(self, **_kw):
            raise RuntimeError("建档失败")

    monkeypatch.setattr(service, "_knowledge_base_service", lambda: _Knowledge())

    with pytest.raises(RuntimeError):
        service.instant_upload(
            account=account, upload_file_id=str(_uuid4()),
            fingerprint="fp", knowledge_base_id=str(_uuid4()),
        )

    assert runtime_storage.deleted, "应回滚秒传复制产物"
    assert upload_file_service.deleted, "应回滚 UploadFile 记录"


def test_save_chunk_rejects_other_account():
    session_service = _FakeSessionService()
    service, _calls = _service(session_service=session_service)
    session_id = service.init(
        account=_account(), filename="a.mp4", total_size=1024,
        chunk_size=512, total_chunks=2, fingerprint="fp",
    )["session_id"]

    with pytest.raises(FailException):
        service.save_chunk(session_id=session_id, index=0, content=b"x" * 512, account=_account())


def test_complete_rejects_when_session_already_claimed(monkeypatch):
    """会话已被占用时应拒绝并发 complete。"""
    session_service = _FakeSessionService()
    service, _calls = _service(session_service=session_service)
    account = _account()
    session_id = service.init(
        account=account, filename="a.mp4", total_size=1024,
        chunk_size=512, total_chunks=2, fingerprint="fp-claim",
    )["session_id"]
    service.save_chunk(session_id=session_id, index=0, content=b"a" * 512, account=account)
    service.save_chunk(session_id=session_id, index=1, content=b"b" * 512, account=account)
    session_service.claim_for_completion = lambda _sid: False

    with pytest.raises(FailException):
        service.complete(session_id=session_id, account=account)


def test_complete_passes_parse_reserve_to_consume_quota():
    """分片 complete 的配额预占必须带解析预留，挡住「刚好传满」的场景。"""
    from internal.entity.storage_quota_entity import PARSE_RESERVE_BYTES

    session_service = _FakeSessionService()
    storage = _FakeStorage()
    service, calls = _service(storage=storage, session_service=session_service)
    account = _account()
    session_id = service.init(
        account=account, filename="final.mp4", total_size=1024,
        chunk_size=512, total_chunks=2, fingerprint="fp-reserve",
    )["session_id"]
    calls.clear()
    service.save_chunk(session_id=session_id, index=0, content=b"a" * 512, account=account)
    service.save_chunk(session_id=session_id, index=1, content=b"b" * 512, account=account)

    service.complete(session_id=session_id, account=account)

    assert calls == [("consume", account.id, 1024, PARSE_RESERVE_BYTES)]


def test_instant_upload_passes_parse_reserve_to_consume_quota():
    """秒传的配额预占同样必须带解析预留。"""
    from internal.entity.storage_quota_entity import PARSE_RESERVE_BYTES
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

    service, calls = _service()
    service.db = SimpleNamespace(session=SimpleNamespace(query=lambda *_a, **_kw: _Query()))

    service.instant_upload(account=account, upload_file_id=str(_uuid4()), fingerprint="fp-reserve-2")

    assert calls == [("consume", account.id, 8192, PARSE_RESERVE_BYTES)]

