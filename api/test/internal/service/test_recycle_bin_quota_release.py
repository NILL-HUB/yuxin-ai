"""回收站物理销毁时释放账号存储配额。

配额在删除/进回收站时不释放（底层文件留存期内仍占用存储），只有留存期结束的
物理销毁（purge）才真正删除底层对象，因此释放必须发生在 purge 阶段。
"""
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
