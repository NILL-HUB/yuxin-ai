import hashlib
import os
from types import SimpleNamespace

import pytest

from internal.service.storage import local_storage_service as module
from internal.service.storage.local_storage_service import LocalStorageService


@pytest.fixture
def isolated_storage(monkeypatch, tmp_path):
    """把本地存储根与分片根都指向临时目录，避免污染真实 storage。"""
    upload_root = tmp_path / "uploads"
    chunk_root = tmp_path / "chunks"
    monkeypatch.setattr(module, "_get_local_storage_root", lambda: str(upload_root))
    monkeypatch.setattr(module, "_get_chunk_upload_root", lambda override=None: str(chunk_root))
    (upload_root / "2026" / "09" / "14").mkdir(parents=True, exist_ok=True)
    return SimpleNamespace(upload_root=upload_root, chunk_root=chunk_root)


def _service():
    return LocalStorageService(upload_file_service=SimpleNamespace())


def test_save_chunk_writes_bytes_and_returns_size(isolated_storage):
    service = _service()

    written = service.save_chunk("sess-1", 0, b"hello")

    assert written == 5
    path = service._chunk_path("sess-1", 0)
    assert os.path.isfile(path)
    with open(path, "rb") as fh:
        assert fh.read() == b"hello"


def test_save_chunk_overwrites_same_index(isolated_storage):
    service = _service()
    service.save_chunk("s", 0, b"first")
    service.save_chunk("s", 0, b"second")

    with open(service._chunk_path("s", 0), "rb") as fh:
        assert fh.read() == b"second"


def test_merge_chunks_produces_ordered_output_and_hash(isolated_storage):
    service = _service()
    session_id = "sess-merge"
    parts = [b"AAA", b"BBB", b"CCC"]
    for index, part in enumerate(parts):
        service.save_chunk(session_id, index, part)

    target_key = "2026/09/14/merged.mp4"
    size, digest = service.merge_chunks(session_id, len(parts), target_key)

    assert size == 9
    assert digest == hashlib.sha3_256(b"AAABBBCCC").hexdigest()

    with open(service._object_path(target_key), "rb") as fh:
        assert fh.read() == b"AAABBBCCC"


def test_merge_chunks_raises_when_chunk_missing(isolated_storage):
    from internal.exception import FailException

    service = _service()
    service.save_chunk("sess-x", 0, b"AAA")

    with pytest.raises(FailException):
        service.merge_chunks("sess-x", 3, "2026/09/14/x.mp4")


def test_merge_chunks_removes_partial_target_when_merge_fails(isolated_storage):
    """合并中途失败必须回收半成品目标对象，否则会留下不计配额的孤儿文件。"""
    from internal.exception import FailException

    service = _service()
    session_id = "sess-partial"
    service.save_chunk(session_id, 0, b"AAA")
    # 故意缺少 index=1，合并会在写出 index=0 之后失败

    target_key = "2026/09/14/partial.mp4"
    with pytest.raises(FailException):
        service.merge_chunks(session_id, 3, target_key)

    assert not os.path.isfile(service._object_path(target_key))


def test_merge_chunks_removes_partial_target_when_chunk_read_raises(isolated_storage, monkeypatch):
    """分片读取抛非 FailException 异常时同样要回收半成品。"""
    service = _service()
    session_id = "sess-write-fail"
    service.save_chunk(session_id, 0, b"AAA")
    service.save_chunk(session_id, 1, b"BBB")

    target_key = "2026/09/14/writefail.mp4"
    # 先解析出绝对路径：monkeypatch 会影响路径解析，断言必须用已解析的真实路径
    target_path = service._object_path(target_key)
    real_open = open
    poisoned = service._chunk_path(session_id, 1)

    def _exploding_open(path, mode="r", *args, **kwargs):
        if mode == "rb" and str(path) == str(poisoned):
            raise OSError("read blew up")
        return real_open(path, mode, *args, **kwargs)

    monkeypatch.setattr("builtins.open", _exploding_open)

    with pytest.raises(OSError):
        service.merge_chunks(session_id, 2, target_key)

    assert not os.path.isfile(target_path)


def test_cleanup_session_removes_chunk_dir(isolated_storage):
    service = _service()
    service.save_chunk("sess-clean", 0, b"data")
    assert os.path.isdir(service._chunk_dir("sess-clean"))

    service.cleanup_session("sess-clean")

    assert not os.path.isdir(service._chunk_dir("sess-clean"))


def test_cleanup_stale_session_dirs_removes_inactive_only(isolated_storage):
    """只清理不再活跃的会话目录，活跃的保留。"""
    service = _service()
    service.save_chunk("active-sess", 0, b"data")
    service.save_chunk("stale-sess", 0, b"data")

    cleaned = service.cleanup_stale_session_dirs(lambda sid: sid == "active-sess")

    assert cleaned == ["stale-sess"]
    assert os.path.isdir(service._chunk_dir("active-sess"))
    assert not os.path.isdir(service._chunk_dir("stale-sess"))


def test_copy_object_duplicates_file_server_side(isolated_storage):
    service = _service()
    source_key = "2026/09/14/source.mp4"
    source_path = service._object_path(source_key)
    os.makedirs(os.path.dirname(source_path), exist_ok=True)
    with open(source_path, "wb") as fh:
        fh.write(b"payload")

    target_key = "2026/09/14/copy.mp4"
    size = service.copy_object(source_key, target_key)

    assert size == 7
    with open(service._object_path(target_key), "rb") as fh:
        assert fh.read() == b"payload"
