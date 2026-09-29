"""FileCenterService read_file / save_artifact 单测（替身存储，不依赖真实后端）。"""
import os
import uuid

import pytest

from internal.extension.database_extension import db
from internal.model import FileCenterEntry, UploadFile
from internal.service.file_center_service import FileCenterService


@pytest.fixture
def env():
    from app.http.app import app as flask_app

    with flask_app.app_context():
        accounts: list = []
        yield accounts
        if accounts:
            db.session.query(FileCenterEntry).filter(
                FileCenterEntry.account_id.in_(accounts)
            ).delete(synchronize_session=False)
            db.session.query(UploadFile).filter(
                UploadFile.account_id.in_(accounts)
            ).delete(synchronize_session=False)
            db.session.commit()


class _FakeUploadFile:
    def __init__(self, name, size=5):
        self.id = uuid.uuid4()
        self.name = name
        self.size = size


class _FakeStorage:
    """替身存储：upload_bytes 建 UploadFile 记录；download_file 写临时文本。"""

    def __init__(self):
        self.uploaded: list[dict] = []
        self.text = "hello\nworld\nthird"

    def upload_bytes(self, *, filename, content, account_id, folder="artifacts", **kw):
        uf = _FakeUploadFile(filename, size=len(content))
        db.session.add(
            UploadFile(
                id=uf.id,
                account_id=account_id,
                name=filename,
                key=f"artifacts/{uf.id}.txt",
                size=uf.size,
                extension="txt",
                mime_type="text/plain",
                hash="h",
                storage_backend="local",
            )
        )
        db.session.flush()
        self.uploaded.append({"filename": filename, "content": content})
        return uf

    def download_file(self, key, target_file_path, backend=None):
        with open(target_file_path, "w", encoding="utf-8") as fh:
            fh.write(self.text)


def _svc_with_fake_storage():
    svc = FileCenterService()
    fake = _FakeStorage()
    svc.storage = fake
    return svc, fake


def test_save_artifact_creates_node_and_upload_file(env):
    svc, fake = _svc_with_fake_storage()
    acc = uuid.uuid4()
    env.append(acc)
    res = svc.save_artifact(acc, name="note.txt", content="hello")
    assert res["name"] == "note.txt"
    assert fake.uploaded[0]["content"] == b"hello"
    roots = svc.list_children(acc, parent_id=None)
    # 默认落「产物/」目录
    assert [e.name for e in roots] == ["产物"]
    children = svc.list_children(acc, parent_id=roots[0].id)
    assert [c.name for c in children] == ["note.txt"]
    assert children[0].source == "artifact"


def test_read_file_returns_text_and_respects_limit(env):
    svc, _ = _svc_with_fake_storage()
    acc = uuid.uuid4()
    env.append(acc)
    svc.save_artifact(acc, name="note.txt", content="hello")
    folder = [e for e in svc.list_children(acc, parent_id=None) if e.is_folder][0]
    entry = svc.list_children(acc, parent_id=folder.id)[0]
    result = svc.read_file(acc, entry.id)
    assert result["content"] == "hello\nworld\nthird"
    limited = svc.read_file(acc, entry.id, limit=2)
    assert limited["content"] == "hello\nworld"


def test_read_file_rejects_folder(env):
    from internal.exception import ValidateErrorException

    svc, _ = _svc_with_fake_storage()
    acc = uuid.uuid4()
    env.append(acc)
    folder = svc.mkdir(acc, parent_id=None, name="F")
    with pytest.raises(ValidateErrorException):
        svc.read_file(acc, folder.id)