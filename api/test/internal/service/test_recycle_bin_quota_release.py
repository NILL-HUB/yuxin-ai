"""回收站物理销毁时释放账号存储配额。

配额在删除/进回收站时不释放（底层文件留存期内仍占用存储），只有留存期结束的
物理销毁（purge）才真正删除底层对象，因此释放必须发生在 purge 阶段。
"""
from types import SimpleNamespace
from uuid import uuid4

import pytest

from internal.service import recycle_bin_handlers as handlers
from internal.service.storage import storage_migration_service


class _FakeQuotaService:
    def __init__(self):
        self.calls = []

    def release_usage(self, account_id, bytes_delta):
        self.calls.append((account_id, bytes_delta))
        return 0


@pytest.fixture
def fake_quota(monkeypatch):
    fake = _FakeQuotaService()
    monkeypatch.setattr(handlers, "_get_storage_quota_service", lambda: fake, raising=False)
    return fake


@pytest.fixture
def fake_delete(monkeypatch):
    deleted = []
    monkeypatch.setattr(
        storage_migration_service,
        "_delete_object",
        lambda backend, key: deleted.append((backend, key)),
    )
    return deleted


def test_purge_knowledge_document_releases_quota(monkeypatch, fake_quota, fake_delete):
    account_id = str(uuid4())
    snapshot = {
        "upload_file": {
            "account_id": account_id,
            "size": 2048,
            "key": "knowledge/doc-1.pdf",
            "storage_backend": "local",
        }
    }

    handlers.purge_knowledge_document(snapshot)

    assert fake_delete == [("local", "knowledge/doc-1.pdf")]
    assert fake_quota.calls == [(account_id, 2048)]


def test_purge_knowledge_base_releases_quota_for_each_document(fake_quota, fake_delete):
    account_id = str(uuid4())
    snapshot = {
        "main": {"id": "kb-1"},
        "documents": [
            {
                "_upload_file": {
                    "account_id": account_id,
                    "size": 1000,
                    "key": "knowledge/a.txt",
                    "storage_backend": "cos",
                }
            },
            {
                "_upload_file": {
                    "account_id": account_id,
                    "size": 2500,
                    "key": "knowledge/b.txt",
                    "storage_backend": "cos",
                }
            },
            {"_upload_file": None},
        ],
    }

    handlers.purge_knowledge_base(snapshot)

    assert fake_delete == [("cos", "knowledge/a.txt"), ("cos", "knowledge/b.txt")]
    assert fake_quota.calls == [(account_id, 1000), (account_id, 2500)]


def test_purge_knowledge_document_skips_release_when_account_missing(fake_quota, fake_delete):
    snapshot = {
        "upload_file": {
            "size": 512,
            "key": "knowledge/doc-2.pdf",
            "storage_backend": "local",
        }
    }

    handlers.purge_knowledge_document(snapshot)

    assert fake_delete == [("local", "knowledge/doc-2.pdf")]
    assert fake_quota.calls == []


def test_purge_knowledge_document_skips_release_when_size_missing(fake_quota, fake_delete):
    account_id = str(uuid4())
    snapshot = {
        "upload_file": {
            "account_id": account_id,
            "key": "knowledge/doc-3.pdf",
            "storage_backend": "local",
        }
    }

    handlers.purge_knowledge_document(snapshot)

    assert fake_delete == [("local", "knowledge/doc-3.pdf")]
    assert fake_quota.calls == []


def test_purge_knowledge_base_does_not_release_when_fields_incomplete(fake_quota, fake_delete):
    snapshot = {
        "documents": [
            {"_upload_file": {"size": 100, "key": "knowledge/c.txt"}},
            {"_upload_file": {"account_id": str(uuid4()), "key": "knowledge/d.txt"}},
        ],
    }

    handlers.purge_knowledge_base(snapshot)

    assert fake_delete == [("local", "knowledge/c.txt"), ("local", "knowledge/d.txt")]
    assert fake_quota.calls == []


def test_release_storage_quota_swallows_service_error(monkeypatch, fake_delete):
    """配额释放失败不得让 purge 抛异常（否则会被误判为底层删除失败而重试）。"""
    account_id = str(uuid4())

    class _BrokenQuotaService:
        def release_usage(self, *_a, **_k):
            raise RuntimeError("db unavailable")

    monkeypatch.setattr(
        handlers, "_get_storage_quota_service", lambda: _BrokenQuotaService(), raising=False
    )

    snapshot = {
        "upload_file": {
            "account_id": account_id,
            "size": 4096,
            "key": "knowledge/doc-4.pdf",
            "storage_backend": "local",
        }
    }

    # 不抛异常即为通过
    handlers.purge_knowledge_document(snapshot)
    assert fake_delete == [("local", "knowledge/doc-4.pdf")]


def test_purge_upload_file_releases_quota(fake_quota, fake_delete):
    """独立 upload_file 回收站条目的物理销毁同样应释放配额。"""
    account_id = str(uuid4())
    snapshot = {
        "main": {
            "account_id": account_id,
            "size": 8192,
            "key": "uploads/standalone.bin",
            "storage_backend": "oss",
        }
    }

    handlers.purge_upload_file(snapshot)

    assert fake_delete == [("oss", "uploads/standalone.bin")]
    assert fake_quota.calls == [(account_id, 8192)]


def test_purge_upload_file_skips_release_when_fields_incomplete(fake_quota, fake_delete):
    snapshot = {"main": {"size": 128, "key": "uploads/incomplete.bin"}}

    handlers.purge_upload_file(snapshot)

    assert fake_delete == [("local", "uploads/incomplete.bin")]
    assert fake_quota.calls == []


class TestFrameFilesReleasedOnPurge:
    """删除素材必须连带清理帧文件并释放其配额（成对修复）。

    背景：帧的 upload_file 记录此前**永不清理**（purge 只删主文件），已是孤儿；
    而帧自 P3 起就经由存储代理计了配额（`_persist_frame` → `upload_bytes`）。
    只删主文件 = 用户删掉素材后帧仍占额，扣掉的空间永不归还，即配额泄漏。
    """

    def test_purge_deletes_and_releases_frame_files(self, fake_quota, fake_delete):
        """主文件 + 全部帧文件都要删对象并释放配额。"""
        account_id = str(uuid4())
        snapshot = {
            "upload_file": {
                "account_id": account_id, "size": 100, "key": "main.mp4",
                "storage_backend": "local",
            },
            "frames": [
                {"account_id": account_id, "size": 10, "key": "frames/f1.jpg",
                 "storage_backend": "local"},
                {"account_id": account_id, "size": 20, "key": "frames/f2.jpg",
                 "storage_backend": "local"},
            ],
        }

        handlers.purge_knowledge_document(snapshot)

        assert fake_delete == [
            ("local", "main.mp4"),
            ("local", "frames/f1.jpg"),
            ("local", "frames/f2.jpg"),
        ]
        assert fake_quota.calls == [
            (account_id, 100),
            (account_id, 10),
            (account_id, 20),
        ]

    def test_purge_tolerates_snapshot_without_frames(self, fake_quota, fake_delete):
        """老快照无 frames 字段时不得报错（向后兼容）。"""
        account_id = str(uuid4())
        snapshot = {
            "upload_file": {
                "account_id": account_id, "size": 1, "key": "main.mp4",
                "storage_backend": "local",
            }
        }

        handlers.purge_knowledge_document(snapshot)

        assert fake_delete == [("local", "main.mp4")]
        assert fake_quota.calls == [(account_id, 1)]

    def test_purge_knowledge_base_deletes_and_releases_frames(self, fake_quota, fake_delete):
        """整库销毁时，每个文档的帧文件同样要删对象并释放配额。"""
        account_id = str(uuid4())
        snapshot = {
            "main": {"id": "kb-1"},
            "documents": [
                {
                    "_upload_file": {
                        "account_id": account_id, "size": 1000, "key": "main.mp4",
                        "storage_backend": "cos",
                    },
                    "_frames": [
                        {"account_id": account_id, "size": 30, "key": "frames/f1.jpg",
                         "storage_backend": "cos"},
                    ],
                },
                {
                    "_upload_file": None,
                    "_frames": [
                        {"account_id": account_id, "size": 40, "key": "frames/f2.jpg",
                         "storage_backend": "cos"},
                    ],
                },
            ],
        }

        handlers.purge_knowledge_base(snapshot)

        assert fake_delete == [
            ("cos", "main.mp4"),
            ("cos", "frames/f1.jpg"),
            ("cos", "frames/f2.jpg"),
        ]
        assert fake_quota.calls == [
            (account_id, 1000),
            (account_id, 30),
            (account_id, 40),
        ]

    def test_collect_document_frame_files_queries_by_frame_url(self, monkeypatch):
        """快照需按 frame_url 采集帧 UploadFile 记录，否则销毁时无从释放。"""
        from internal.model import UploadFile

        captured = {}

        class _Query:
            def filter(self, *args, **kwargs):
                captured["filtered"] = True
                return self

            def all(self):
                return [UploadFile(
                    account_id=uuid4(), name="f1.jpg", key="f1.jpg", size=10,
                    extension="jpg", mime_type="image/jpeg", hash="h",
                    storage_backend="local",
                )]

        monkeypatch.setattr(
            handlers, "db",
            SimpleNamespace(session=SimpleNamespace(query=lambda *a, **k: _Query())),
        )

        segment = SimpleNamespace(metadata_={"frame_url": "f1.jpg"})
        frames = handlers._collect_document_frame_files([segment])

        assert captured["filtered"] is True
        assert frames[0]["key"] == "f1.jpg"
        assert frames[0]["size"] == 10

    def test_collect_document_frame_files_skips_segments_without_frame(self, monkeypatch):
        """无 frame_url 的片段（非视频帧、或留存失败置空）不应参与查询。"""
        segments = [
            SimpleNamespace(metadata_={"media_type": "video", "frame_url": ""}),
            SimpleNamespace(metadata_={"media_type": "audio"}),
        ]

        assert handlers._collect_document_frame_files(segments) == []
