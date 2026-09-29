"""FileCenterService 目录树操作单测。

连真实开发库（与仓库其他 service 测试一致），用唯一 account_id 隔离，
并在测试结束后清理本测试产生的行。
"""
import uuid

import pytest

from internal.exception import NotFoundException, ValidateErrorException
from internal.extension.database_extension import db
from internal.model import FileCenterEntry
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


class _FakeRecycleBin:
    def __init__(self):
        self.calls = []

    def delete_resource(self, **kwargs):
        self.calls.append(kwargs)
        return True


def _svc() -> FileCenterService:
    return FileCenterService()


def test_mkdir_and_list(env):
    acc = uuid.uuid4()
    env.append(acc)
    svc = _svc()
    svc.mkdir(acc, parent_id=None, name="文档")
    names = [e.name for e in svc.list_children(acc, parent_id=None)]
    assert names == ["文档"]
    assert svc.list_children(acc, parent_id=None)[0].is_folder is True


def test_mkdir_duplicate_rejected(env):
    acc = uuid.uuid4()
    env.append(acc)
    svc = _svc()
    parent = svc.mkdir(acc, parent_id=None, name="A")
    svc.mkdir(acc, parent_id=parent.id, name="B")
    with pytest.raises(ValidateErrorException):
        svc.mkdir(acc, parent_id=parent.id, name="B")


def test_list_children_is_account_scoped(env):
    acc_a, acc_b = uuid.uuid4(), uuid.uuid4()
    env.extend([acc_a, acc_b])
    svc = _svc()
    svc.mkdir(acc_a, parent_id=None, name="a1")
    svc.mkdir(acc_b, parent_id=None, name="b1")
    assert [e.name for e in svc.list_children(acc_a, parent_id=None)] == ["a1"]


def test_mkdir_under_foreign_parent_rejected(env):
    acc_a, acc_b = uuid.uuid4(), uuid.uuid4()
    env.extend([acc_a, acc_b])
    svc = _svc()
    parent = svc.mkdir(acc_a, parent_id=None, name="A")
    with pytest.raises(NotFoundException):
        svc.mkdir(acc_b, parent_id=parent.id, name="x")


def test_rename_and_conflict(env):
    acc = uuid.uuid4()
    env.append(acc)
    svc = _svc()
    a = svc.mkdir(acc, parent_id=None, name="A")
    b = svc.mkdir(acc, parent_id=None, name="B")
    assert svc.rename(acc, b.id, "C").name == "C"
    with pytest.raises(ValidateErrorException):
        svc.rename(acc, b.id, "A")


def test_move_cycle_rejected_and_reparent(env):
    acc = uuid.uuid4()
    env.append(acc)
    svc = _svc()
    root = svc.mkdir(acc, parent_id=None, name="R")
    child = svc.mkdir(acc, parent_id=root.id, name="C")
    with pytest.raises(ValidateErrorException):
        svc.move(acc, root.id, child.id)
    a = svc.mkdir(acc, parent_id=None, name="A")
    b = svc.mkdir(acc, parent_id=None, name="B")
    assert svc.move(acc, a.id, b.id).parent_id == b.id


def test_import_upload_file_is_idempotent(env):
    acc = uuid.uuid4()
    env.append(acc)
    svc = _svc()
    fid = uuid.uuid4()
    e1 = svc.import_upload_file(acc, upload_file_id=fid, parent_id=None, name="a.txt")
    e2 = svc.import_upload_file(acc, upload_file_id=fid, parent_id=None, name="a.txt")
    assert e1.id == e2.id
    assert e1.is_folder is False


def test_delete_file_node_recycles_and_removes_node(env):
    acc = uuid.uuid4()
    env.append(acc)
    svc = _svc()
    fake = _FakeRecycleBin()
    svc.recycle_bin_service = fake
    fid = uuid.uuid4()
    entry = svc.import_upload_file(acc, upload_file_id=fid, parent_id=None, name="a.txt")
    svc.delete_node(acc, entry.id)
    assert [c["resource_id"] for c in fake.calls] == [fid]
    assert fake.calls[0]["resource_type"] == "upload_file"
    assert svc.list_children(acc, parent_id=None) == []


def test_delete_folder_recursively_recycles_files(env):
    acc = uuid.uuid4()
    env.append(acc)
    svc = _svc()
    fake = _FakeRecycleBin()
    svc.recycle_bin_service = fake
    folder = svc.mkdir(acc, parent_id=None, name="F")
    f1, f2 = uuid.uuid4(), uuid.uuid4()
    svc.import_upload_file(acc, upload_file_id=f1, parent_id=folder.id, name="1.txt")
    svc.import_upload_file(acc, upload_file_id=f2, parent_id=folder.id, name="2.txt")
    svc.delete_node(acc, folder.id)
    assert sorted(c["resource_id"] for c in fake.calls) == sorted([f1, f2])
    assert svc.list_children(acc, parent_id=None) == []


def test_list_all_files_paginates(env):
    acc = uuid.uuid4()
    env.append(acc)
    svc = _svc()
    svc.import_upload_file(acc, upload_file_id=uuid.uuid4(), parent_id=None, name="1.txt")
    svc.import_upload_file(acc, upload_file_id=uuid.uuid4(), parent_id=None, name="2.txt")
    result = svc.list_all_files(account_id=acc, page=1, page_size=10)
    assert result["total"] == 2
    assert all(item["organized"] is True for item in result["items"])
