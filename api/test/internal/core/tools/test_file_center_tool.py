"""file_center 工具测试（替身服务，不触真实库/存储）。"""
import json
import uuid

import app.http.module as module
from internal.core.tools.builtin_tools.providers.file_center import file_center


class _FakeEntry:
    def __init__(self, name="A", is_folder=True):
        self.id = uuid.uuid4()
        self.name = name
        self.is_folder = is_folder
        self.upload_file_id = None


class _FakeService:
    def __init__(self):
        self.calls = []

    def list_children(self, account_id, parent_id=None):
        self.calls.append(("list_children", str(account_id)))
        return [_FakeEntry("Docs")]

    def mkdir(self, account_id, *, parent_id=None, name=""):
        self.calls.append(("mkdir", name))
        return _FakeEntry(name)

    def save_artifact(self, account_id, *, name, content, parent_id=None, folder="产物"):
        self.calls.append(("save_artifact", name, content))
        return {"ok": True, "entry_id": str(uuid.uuid4()), "upload_file_id": str(uuid.uuid4()), "name": name}

    def read_file(self, account_id, entry_id, *, limit=0):
        return {"ok": True, "name": "a.txt", "content": "hello"}


def _patch_service(monkeypatch):
    service = _FakeService()
    monkeypatch.setattr(module.injector, "get", lambda cls: service)
    return service


def test_list_returns_items(monkeypatch):
    _patch_service(monkeypatch)
    tool = file_center(requester=str(uuid.uuid4()))
    out = json.loads(tool._run(op="list"))
    assert out["ok"] is True
    assert out["items"][0]["name"] == "Docs"


def test_missing_requester_returns_error():
    tool = file_center()
    out = json.loads(tool._run(op="list"))
    assert out["ok"] is False
    assert "账号" in out["error"]


def test_mkdir_forwards_name(monkeypatch):
    service = _patch_service(monkeypatch)
    tool = file_center(requester=str(uuid.uuid4()))
    out = json.loads(tool._run(op="mkdir", name="报告"))
    assert out["ok"] is True
    assert out["name"] == "报告"
    assert ("mkdir", "报告") in service.calls


def test_save_artifact(monkeypatch):
    service = _patch_service(monkeypatch)
    tool = file_center(requester=str(uuid.uuid4()))
    out = json.loads(tool._run(op="save_artifact", name="note.txt", content="hi"))
    assert out["ok"] is True
    assert ("save_artifact", "note.txt", "hi") in service.calls


def test_unknown_op_returns_error(monkeypatch):
    _patch_service(monkeypatch)
    tool = file_center(requester=str(uuid.uuid4()))
    out = json.loads(tool._run(op="nonsense"))
    assert out["ok"] is False
    assert "未知操作" in out["error"]