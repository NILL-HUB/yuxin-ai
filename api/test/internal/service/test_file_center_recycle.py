"""文件中心 × 回收站：路径工具与处理器单测。

连真实开发库（与仓库其他 service 测试一致），用唯一 account_id 隔离，
测试结束后清理产生的行。
"""
import uuid

import pytest

from internal.extension.database_extension import db
from internal.model import FileCenterEntry
from internal.service.file_center_paths import (
    build_parent_path_names,
    delete_entries_by_upload_file,
    ensure_path,
)
from internal.service.file_center_service import FileCenterService


@pytest.fixture
def env():
    from app.http.app import app as flask_app
    from internal.model import UploadFile

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


def test_build_parent_path_names_root_first(env):
    svc = FileCenterService()
    acc = uuid.uuid4()
    env.append(acc)
    a = svc.mkdir(acc, parent_id=None, name="A")
    b = svc.mkdir(acc, parent_id=a.id, name="B")
    entry = svc.import_upload_file(
        acc, upload_file_id=uuid.uuid4(), parent_id=b.id, name="f.txt"
    )
    assert build_parent_path_names(entry) == ["A", "B"]


def test_ensure_path_creates_and_reuses(env):
    acc = uuid.uuid4()
    env.append(acc)
    pid = ensure_path(acc, ["A", "B"])
    assert pid is not None
    pid2 = ensure_path(acc, ["A", "B"])
    assert pid2 == pid
    b = (
        db.session.query(FileCenterEntry)
        .filter(FileCenterEntry.id == pid)
        .one_or_none()
    )
    assert build_parent_path_names(type("E", (), {"parent_id": b.id})()) == ["A", "B"]


def test_delete_entries_by_upload_file_removes_node(env):
    svc = FileCenterService()
    acc = uuid.uuid4()
    env.append(acc)
    fid = uuid.uuid4()
    svc.import_upload_file(acc, upload_file_id=fid, parent_id=None, name="x.txt")
    delete_entries_by_upload_file(fid)
    db.session.commit()
    assert svc.list_children(acc, parent_id=None) == []


# --------------------------------------------------------------------------- #
#  快照 / 恢复 / 销毁 三处理器
# --------------------------------------------------------------------------- #
def _make_upload_file(account_id, name="a.txt", key="k/1.txt"):
    from internal.model import UploadFile

    uf = UploadFile(
        id=uuid.uuid4(),
        account_id=account_id,
        name=name,
        key=key,
        size=1,
        extension="txt",
        mime_type="text/plain",
        hash="h",
        storage_backend="local",
    )
    db.session.add(uf)
    db.session.flush()
    return uf


def test_snapshot_upload_file_captures_file_center_path(env):
    from internal.service.recycle_bin_handlers import snapshot_upload_file

    svc = FileCenterService()
    acc = uuid.uuid4()
    env.append(acc)
    folder = svc.mkdir(acc, parent_id=None, name="Docs")
    uf = _make_upload_file(acc)
    svc.import_upload_file(acc, upload_file_id=uf.id, parent_id=folder.id, name="a.txt")
    snap = snapshot_upload_file(uf.id)
    assert snap["file_center"]["parent_path"] == ["Docs"]
    assert snap["file_center"]["name"] == "a.txt"


def test_restore_upload_file_recreates_node_at_path(env):
    from internal.model import UploadFile
    from internal.service.recycle_bin_handlers import restore_upload_file

    svc = FileCenterService()
    acc = uuid.uuid4()
    env.append(acc)
    uf_id = uuid.uuid4()
    snap = {
        "main": {
            "id": uf_id,
            "account_id": acc,
            "name": "a.txt",
            "key": "k/restore.txt",
            "size": 1,
            "extension": "txt",
            "mime_type": "text/plain",
            "hash": "h",
            "storage_backend": "local",
        },
        "file_center": {
            "account_id": str(acc),
            "parent_path": ["Docs"],
            "name": "a.txt",
            "source": "upload",
            "origin": None,
        },
    }
    assert restore_upload_file(snap) is True
    docs = [e for e in svc.list_children(acc, parent_id=None) if e.is_folder]
    assert [d.name for d in docs] == ["Docs"]
    children = svc.list_children(acc, parent_id=docs[0].id)
    assert [c.name for c in children] == ["a.txt"]
    # 清理：恢复出的 UploadFile 记录
    db.session.query(UploadFile).filter(UploadFile.id == uf_id).delete(
        synchronize_session=False
    )
    db.session.commit()


def test_purge_upload_file_cleans_leftover_node(env, monkeypatch):
    import internal.service.storage.storage_migration_service as sms

    from internal.service.recycle_bin_handlers import purge_upload_file

    monkeypatch.setattr(sms, "_delete_object", lambda *_a, **_k: None)
    svc = FileCenterService()
    acc = uuid.uuid4()
    env.append(acc)
    fid = uuid.uuid4()
    svc.import_upload_file(acc, upload_file_id=fid, parent_id=None, name="gone.txt")
    purge_upload_file(
        {
            "main": {
                "id": fid,
                "key": "k/gone.txt",
                "storage_backend": "local",
                "account_id": acc,
                "size": 1,
            }
        }
    )
    db.session.commit()
    assert svc.list_children(acc, parent_id=None) == []