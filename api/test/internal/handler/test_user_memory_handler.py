from datetime import datetime
from types import SimpleNamespace
from uuid import uuid4

from pkg.response import HttpCode

_SERVICE_PATH = "internal.service.scoped_knowledge_service.UserMemoryService"


def _mock_current_user(monkeypatch, account_id=None):
    account_id = account_id or uuid4()
    fake_user = SimpleNamespace(id=account_id, is_authenticated=True, is_active=True)
    monkeypatch.setattr("flask_login.current_user", fake_user, raising=False)
    return account_id


def _make_memory(**overrides):
    defaults = {
        "id": uuid4(),
        "owner_account_id": uuid4(),
        "memory_type": "preference",
        "content": "我喜欢中文回复",
        "confidence": 3,
        "status": "active",
        "created_from": "manual_input",
        "metadata_": {},
        "created_at": datetime(2025, 1, 1),
        "updated_at": datetime(2025, 1, 1),
    }
    defaults.update(overrides)
    return SimpleNamespace(**defaults)


class TestUserMemoryHandler:
    def test_list_should_return_current_user_memories(self, client, monkeypatch):
        account_id = _mock_current_user(monkeypatch)
        memory = _make_memory(owner_account_id=account_id)

        def _list_memories(self, account):
            return [memory]

        monkeypatch.setattr(f"{_SERVICE_PATH}.list_memories", _list_memories)

        resp = client.get("/user/memory")
        assert resp.json["code"] == HttpCode.SUCCESS
        assert resp.json["data"]["total"] == 1

    def test_create_should_remember_memory(self, client, monkeypatch):
        account_id = _mock_current_user(monkeypatch)
        memory = _make_memory(owner_account_id=account_id)

        def _remember(self, **kwargs):
            return memory

        monkeypatch.setattr(f"{_SERVICE_PATH}.remember", _remember)

        resp = client.post(
            "/user/memory",
            json={"content": "我喜欢简洁回答", "memory_type": "preference"},
        )
        assert resp.json["code"] == HttpCode.SUCCESS

    def test_get_should_return_memory(self, client, monkeypatch):
        account_id = _mock_current_user(monkeypatch)
        memory_id = uuid4()
        memory = _make_memory(id=memory_id, owner_account_id=account_id)

        def _get_memory(self, mid, account):
            return memory

        monkeypatch.setattr(f"{_SERVICE_PATH}.get_memory", _get_memory)

        resp = client.get(f"/user/memory/{memory_id}")
        assert resp.json["code"] == HttpCode.SUCCESS

    def test_update_should_modify_memory(self, client, monkeypatch):
        account_id = _mock_current_user(monkeypatch)
        memory_id = uuid4()
        memory = _make_memory(id=memory_id, owner_account_id=account_id)

        def _update_memory(self, mid, account, **kwargs):
            return memory

        monkeypatch.setattr(f"{_SERVICE_PATH}.update_memory", _update_memory)

        resp = client.post(
            f"/user/memory/{memory_id}",
            json={"content": "更新后的记忆", "enabled": True},
        )
        assert resp.json["code"] == HttpCode.SUCCESS

    def test_delete_should_remove_memory(self, client, monkeypatch):
        account_id = _mock_current_user(monkeypatch)
        memory_id = uuid4()

        def _delete_memory(self, mid, account):
            return True

        monkeypatch.setattr(f"{_SERVICE_PATH}.delete_memory", _delete_memory)

        resp = client.delete(f"/user/memory/{memory_id}")
        assert resp.json["code"] == HttpCode.SUCCESS
