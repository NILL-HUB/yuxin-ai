"""upload_to_knowledge_base 工具：对话内把小钰拿到的素材文件建档入库。"""
import importlib
import json
from uuid import uuid4

_PKG = "internal.core.tools.builtin_tools.providers.knowledge_base_tools"

upload_tool = importlib.import_module(f"{_PKG}.upload_to_knowledge_base")


class _FakeAccount:
    id = uuid4()


def test_requires_account_and_kb():
    tool = upload_tool.upload_to_knowledge_base()
    payload = json.loads(tool._run(file_id="u1"))
    assert payload["ok"] is False
    assert "知识库" in payload["error"] or "文件" in payload["error"]


def test_rejects_missing_file_id():
    tool = upload_tool.upload_to_knowledge_base(account_id="acc-1")
    payload = json.loads(tool._run(knowledge_base_id="kb-1"))
    assert payload["ok"] is False
    assert "文件" in payload["error"]


def test_creates_document_from_upload_file(monkeypatch):
    """file_id 命中且归属当前账号时调 create_document_from_upload_file 建档。"""
    calls = {}
    account = _FakeAccount()
    fake_upload_file = type(
        "U", (), {"id": uuid4(), "name": "v.mp4", "extension": "mp4", "account_id": account.id}
    )()

    class _FakeMgr:
        def get(self, model, primary_key):
            calls["file_id"] = primary_key
            return fake_upload_file

    class _FakeKbSvc:
        def create_document_from_upload_file(self, **kw):
            calls.update(kw)
            return type("D", (), {"id": "d1"})()

    monkeypatch.setattr(upload_tool, "_load_account", lambda account_id: account)
    monkeypatch.setattr(upload_tool, "_load_upload_file_manager", lambda: _FakeMgr())
    monkeypatch.setattr(upload_tool, "_load_knowledge_base_service", lambda: _FakeKbSvc())

    tool = upload_tool.upload_to_knowledge_base(account_id=str(account.id))
    payload = json.loads(tool._run(knowledge_base_id="kb-1", file_id=str(fake_upload_file.id)))

    assert payload["ok"] is True
    assert calls["knowledge_base_id"] == "kb-1"
    assert calls["upload_file"] is fake_upload_file
    assert calls["account"] is account


def test_file_not_found_readable_error(monkeypatch):
    """UploadFile 不存在时报可读错误，不抛裸异常。"""
    class _FakeMgr:
        def get(self, model, primary_key):
            return None

    monkeypatch.setattr(upload_tool, "_load_account", lambda account_id: _FakeAccount())
    monkeypatch.setattr(upload_tool, "_load_upload_file_manager", lambda: _FakeMgr())

    tool = upload_tool.upload_to_knowledge_base(account_id="acc-1")
    payload = json.loads(tool._run(knowledge_base_id="kb-1", file_id=str(uuid4())))

    assert payload["ok"] is False
    assert "不存在" in payload["error"]


def test_rejects_other_accounts_file(monkeypatch):
    """文件归属其他账号时拒绝建档，防止越权引用他人文件。"""
    account = _FakeAccount()
    other = uuid4()
    fake_upload_file = type(
        "U", (), {"id": uuid4(), "name": "x.mp4", "extension": "mp4", "account_id": other}
    )()

    class _FakeMgr:
        def get(self, model, primary_key):
            return fake_upload_file

    monkeypatch.setattr(upload_tool, "_load_account", lambda account_id: account)
    monkeypatch.setattr(upload_tool, "_load_upload_file_manager", lambda: _FakeMgr())

    tool = upload_tool.upload_to_knowledge_base(account_id=str(account.id))
    payload = json.loads(tool._run(knowledge_base_id="kb-1", file_id=str(fake_upload_file.id)))

    assert payload["ok"] is False
    assert "不存在" in payload["error"] or "归属" in payload["error"]


def test_factory_passes_account_id():
    tool = upload_tool.upload_to_knowledge_base(
        account_id="acc-9", message_id="m", conversation_id="c"
    )
    assert tool.account_id == "acc-9"