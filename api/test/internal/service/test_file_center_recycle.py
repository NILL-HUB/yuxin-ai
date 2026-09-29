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

    with flask_app.app_context():
        accounts: list = []
        yield accounts
        if accounts:
            db.session.query(FileCenterEntry).filter(
                FileCenterEntry.account_id.in_(accounts)
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