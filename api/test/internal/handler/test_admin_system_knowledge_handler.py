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
        "visibility_scope": "internal",
    }
    defaults.update(overrides)
    return SimpleNamespace(**defaults)


_SERVICE_PATH = "internal.service.scoped_knowledge_service.SystemKnowledgeService"


class TestAdminSystemKnowledgeHandler:
    def test_list_should_delegate_to_service(self, client, monkeypatch):
        _mock_current_admin(monkeypatch, ["system_knowledge:read"])
        kb = _make_kb()

        def _list(self, *, page=1, page_size=20, search_word=""):
            # 服务端分页后返回 dict 结构，包含兼容旧前端的 items/total 及分页器字段
            return {
                "items": [kb],
                "total": 1,
                "page": page,
                "page_size": page_size,
                "total_pages": 1,
                "total_record": 1,
            }

        monkeypatch.setattr(f"{_SERVICE_PATH}.list_system_knowledge", _list, raising=False)

        resp = client.get("/admin/system-knowledge", headers={"Authorization": "Bearer admin-token"})

        assert resp.status_code == 200
        assert resp.json["code"] == HttpCode.SUCCESS
        # 兼容旧前端的 items/total 仍然保留
        assert resp.json["data"]["total"] == 1
        assert resp.json["data"]["items"][0]["name"] == "系统知识库"
        assert resp.json["data"]["items"][0]["knowledge_scope"] == "system"
        # 分页器字段
        assert resp.json["data"]["page"] == 1
        assert resp.json["data"]["page_size"] == 20
        assert resp.json["data"]["total_pages"] == 1
        assert resp.json["data"]["total_record"] == 1

    def test_list_should_pass_pagination_and_search_params(self, client, monkeypatch):
        """验证 list 接口正确透传分页与搜索参数到 service。"""
        _mock_current_admin(monkeypatch, ["system_knowledge:read"])
        captured = {}

        def _list(self, *, page=1, page_size=20, search_word=""):
            captured.update({"page": page, "page_size": page_size, "search_word": search_word})
            return {"items": [], "total": 0, "page": page, "page_size": page_size, "total_pages": 0, "total_record": 0}

        monkeypatch.setattr(f"{_SERVICE_PATH}.list_system_knowledge", _list, raising=False)

        resp = client.get(
            "/admin/system-knowledge?page=2&page_size=50&search_word=规则",
            headers={"Authorization": "Bearer admin-token"},
        )

        assert resp.status_code == 200
        assert resp.json["code"] == HttpCode.SUCCESS
        assert captured["page"] == 2
        assert captured["page_size"] == 50
        assert captured["search_word"] == "规则"

    def test_create_should_delegate_to_service(self, client, monkeypatch):
        captured = {}
        _mock_current_admin(monkeypatch, ["system_knowledge:write"])
        kb = _make_kb(name="新建知识库")

        def _create(self, *, name, admin_user, description="", visibility_scope="internal"):
            captured.update({
                "name": name,
                "admin_user_id": admin_user.id,
                "description": description,
                "visibility_scope": visibility_scope,
            })
            return kb

        monkeypatch.setattr(f"{_SERVICE_PATH}.create_system_knowledge", _create, raising=False)

        resp = client.post(
            "/admin/system-knowledge",
            json={"name": "新建知识库", "description": "描述", "visibility_scope": "public"},
            headers={"Authorization": "Bearer admin-token"},
        )

        assert resp.status_code == 200
        assert resp.json["code"] == HttpCode.SUCCESS
        assert resp.json["data"]["name"] == "新建知识库"
        assert captured["name"] == "新建知识库"
        assert captured["admin_user_id"] == "admin-1"
        assert captured["description"] == "描述"
        # visibility_scope 应被透传到 service
        assert captured["visibility_scope"] == "public"

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
        kb = _make_kb(id=kb_id, name="更新后", enabled=False, visibility_scope="public")

        def _update(self, knowledge_base_id, *, name=None, description=None, enabled=None, visibility_scope=None):
            captured.update({
                "knowledge_base_id": knowledge_base_id,
                "name": name,
                "description": description,
                "enabled": enabled,
                "visibility_scope": visibility_scope,
            })
            return kb

        monkeypatch.setattr(f"{_SERVICE_PATH}.update_system_knowledge", _update, raising=False)

        resp = client.post(
            f"/admin/system-knowledge/{kb_id}",
            json={"name": "更新后", "enabled": False, "visibility_scope": "public"},
            headers={"Authorization": "Bearer admin-token"},
        )

        assert resp.status_code == 200
        assert resp.json["code"] == HttpCode.SUCCESS
        assert resp.json["data"]["name"] == "更新后"
        assert resp.json["data"]["enabled"] is False
        assert resp.json["data"]["visibility_scope"] == "public"
        assert captured["knowledge_base_id"] == kb_id
        assert captured["name"] == "更新后"
        assert captured["enabled"] is False
        assert captured["description"] is None
        # visibility_scope 应被透传到 service
        assert captured["visibility_scope"] == "public"

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
