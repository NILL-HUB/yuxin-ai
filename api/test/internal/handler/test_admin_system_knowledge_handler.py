from types import SimpleNamespace
from uuid import uuid4

from pkg.response import HttpCode


def _mock_current_admin(monkeypatch, permissions):
    def _get_current_admin_from_token(self, token):
        return {
            "id": "admin-1",
            "email": "root@example.com",
            "name": "Root",
            "avatar": "",
            "status": "active",
            "roles": ["super_admin"],
            "permissions": permissions,
        }

    monkeypatch.setattr(
        "internal.service.admin_user_service.AdminUserService.get_current_admin_from_token",
        _get_current_admin_from_token,
    )


def _make_kb(**overrides):
    defaults = {
        "id": uuid4(),
        "name": "系统知识库",
        "description": "系统级描述",
        "knowledge_scope": "system",
        "owner_admin_user_id": uuid4(),
        "enabled": True,
        "created_at": 1893456000,
        "updated_at": 1893542400,
    }
    defaults.update(overrides)
    return SimpleNamespace(**defaults)


_SERVICE_PATH = "internal.service.scoped_knowledge_service.SystemKnowledgeService"


class TestAdminSystemKnowledgeHandler:
    def test_list_should_delegate_to_service(self, client, monkeypatch):
        _mock_current_admin(monkeypatch, ["system_knowledge:read"])
        kb = _make_kb()

        def _list(self):
            return [kb]

        monkeypatch.setattr(f"{_SERVICE_PATH}.list_system_knowledge", _list, raising=False)

        resp = client.get("/admin/system-knowledge", headers={"Authorization": "Bearer admin-token"})

        assert resp.status_code == 200
        assert resp.json["code"] == HttpCode.SUCCESS
        assert resp.json["data"]["total"] == 1
        assert resp.json["data"]["items"][0]["name"] == "系统知识库"
        assert resp.json["data"]["items"][0]["knowledge_scope"] == "system"

    def test_create_should_delegate_to_service(self, client, monkeypatch):
        captured = {}
        _mock_current_admin(monkeypatch, ["system_knowledge:write"])
        kb = _make_kb(name="新建知识库")

        def _create(self, *, name, admin_user, description=""):
            captured.update({"name": name, "admin_user_id": admin_user.id, "description": description})
            return kb

        monkeypatch.setattr(f"{_SERVICE_PATH}.create_system_knowledge", _create, raising=False)

        resp = client.post(
            "/admin/system-knowledge",
            json={"name": "新建知识库", "description": "描述"},
            headers={"Authorization": "Bearer admin-token"},
        )

        assert resp.status_code == 200
        assert resp.json["code"] == HttpCode.SUCCESS
        assert resp.json["data"]["name"] == "新建知识库"
        assert captured["name"] == "新建知识库"
        assert captured["admin_user_id"] == "admin-1"
        assert captured["description"] == "描述"

    def test_create_should_reject_missing_name(self, client, monkeypatch):
        _mock_current_admin(monkeypatch, ["system_knowledge:write"])

        resp = client.post(
            "/admin/system-knowledge",
            json={"description": "无名称"},
            headers={"Authorization": "Bearer admin-token"},
        )

        assert resp.status_code == 200
        assert resp.json["code"] == HttpCode.VALIDATE_ERROR

    def test_get_should_delegate_to_service(self, client, monkeypatch):
        kb_id = uuid4()
        captured = {}
        _mock_current_admin(monkeypatch, ["system_knowledge:read"])
        kb = _make_kb(id=kb_id)

        def _get(self, knowledge_base_id):
            captured["knowledge_base_id"] = knowledge_base_id
            return kb

        monkeypatch.setattr(f"{_SERVICE_PATH}.get_system_knowledge", _get, raising=False)

        resp = client.get(f"/admin/system-knowledge/{kb_id}", headers={"Authorization": "Bearer admin-token"})

        assert resp.status_code == 200
        assert resp.json["code"] == HttpCode.SUCCESS
        assert resp.json["data"]["id"] == str(kb_id)
        assert captured["knowledge_base_id"] == kb_id

    def test_update_should_delegate_to_service(self, client, monkeypatch):
        kb_id = uuid4()
        captured = {}
        _mock_current_admin(monkeypatch, ["system_knowledge:write"])
        kb = _make_kb(id=kb_id, name="更新后", enabled=False)

        def _update(self, knowledge_base_id, *, name=None, description=None, enabled=None):
            captured.update({
                "knowledge_base_id": knowledge_base_id,
                "name": name,
                "description": description,
                "enabled": enabled,
            })
            return kb

        monkeypatch.setattr(f"{_SERVICE_PATH}.update_system_knowledge", _update, raising=False)

        resp = client.post(
            f"/admin/system-knowledge/{kb_id}",
            json={"name": "更新后", "enabled": False},
            headers={"Authorization": "Bearer admin-token"},
        )

        assert resp.status_code == 200
        assert resp.json["code"] == HttpCode.SUCCESS
        assert resp.json["data"]["name"] == "更新后"
        assert resp.json["data"]["enabled"] is False
        assert captured["knowledge_base_id"] == kb_id
        assert captured["name"] == "更新后"
        assert captured["enabled"] is False
        assert captured["description"] is None

    def test_delete_should_delegate_to_service(self, client, monkeypatch):
        kb_id = uuid4()
        captured = {}
        _mock_current_admin(monkeypatch, ["system_knowledge:write"])

        def _delete(self, knowledge_base_id):
            captured["knowledge_base_id"] = knowledge_base_id

        monkeypatch.setattr(f"{_SERVICE_PATH}.delete_system_knowledge", _delete, raising=False)

        resp = client.delete(f"/admin/system-knowledge/{kb_id}", headers={"Authorization": "Bearer admin-token"})

        assert resp.status_code == 200
        assert resp.json["code"] == HttpCode.SUCCESS
        assert resp.json["data"]["id"] == str(kb_id)
        assert captured["knowledge_base_id"] == kb_id

    def test_list_should_reject_missing_permission(self, client, monkeypatch):
        _mock_current_admin(monkeypatch, ["admin:access"])

        resp = client.get("/admin/system-knowledge", headers={"Authorization": "Bearer admin-token"})

        assert resp.status_code == 200
        assert resp.json["code"] == HttpCode.FORBIDDEN
