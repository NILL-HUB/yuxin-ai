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


class TestAdminRbacHandler:
    def test_list_roles_should_delegate_to_service(self, client, monkeypatch):
        _mock_current_admin(monkeypatch, ["role:read"])
        monkeypatch.setattr(
            "internal.service.admin_rbac_service.AdminRbacService.list_roles",
            lambda self: [{"id": "role-1", "code": "super_admin", "name": "超级管理员", "description": "拥有全部权限", "is_system": True, "permissions": ["admin:access"]}],
            raising=False,
        )

        resp = client.get("/admin/roles", headers={"Authorization": "Bearer admin-token"})

        assert resp.status_code == 200
        assert resp.json["code"] == HttpCode.SUCCESS
        assert resp.json["data"][0]["code"] == "super_admin"

    def test_get_role_should_delegate_to_service(self, client, monkeypatch):
        _mock_current_admin(monkeypatch, ["role:read"])
        role_id = uuid4()
        captured = {}

        def _get(self, role_id_arg):
            captured["role_id"] = role_id_arg
            return {"id": str(role_id_arg), "code": "ops", "name": "运营", "description": "运营角色", "is_system": False, "permissions": []}

        monkeypatch.setattr("internal.service.admin_rbac_service.AdminRbacService.get_role", _get, raising=False)

        resp = client.get(f"/admin/roles/{role_id}", headers={"Authorization": "Bearer admin-token"})

        assert resp.status_code == 200
        assert resp.json["code"] == HttpCode.SUCCESS
        assert resp.json["data"]["id"] == str(role_id)
        assert captured == {"role_id": role_id}

    def test_create_role_should_delegate_to_service(self, client, monkeypatch):
        _mock_current_admin(monkeypatch, ["role:create"])
        permission_id = str(uuid4())
        captured = {}

        def _create(self, *, code, name, description, permission_ids, operator_id, ip, user_agent):
            captured.update({
                "code": code,
                "name": name,
                "description": description,
                "permission_ids": permission_ids,
                "operator_id": operator_id,
                "ip": ip,
                "user_agent": user_agent,
            })
            return {"id": "role-2", "code": code, "name": name, "description": description, "is_system": False, "permissions": []}

        monkeypatch.setattr("internal.service.admin_rbac_service.AdminRbacService.create_role", _create, raising=False)

        resp = client.post(
            "/admin/roles",
            json={"code": "ops", "name": "运营", "description": "运营角色", "permission_ids": [permission_id]},
            headers={"Authorization": "Bearer admin-token"},
        )

        assert resp.status_code == 200
        assert resp.json["code"] == HttpCode.SUCCESS
        assert captured == {
            "code": "ops",
            "name": "运营",
            "description": "运营角色",
            "permission_ids": [permission_id],
            "operator_id": "admin-1",
            "ip": "127.0.0.1",
            "user_agent": "Werkzeug/3.1.6",
        }

    def test_update_role_should_delegate_to_service(self, client, monkeypatch):
        _mock_current_admin(monkeypatch, ["role:update"])
        role_id = uuid4()
        captured = {}

        def _update(self, role_id_arg, *, name=None, description=None, permission_ids=None, operator_id=None, ip="", user_agent=""):
            captured.update({
                "role_id": role_id_arg,
                "name": name,
                "description": description,
                "permission_ids": permission_ids,
                "operator_id": operator_id,
                "ip": ip,
                "user_agent": user_agent,
            })
            return {"id": str(role_id_arg), "code": "ops", "name": name, "description": description, "is_system": False, "permissions": []}

        monkeypatch.setattr("internal.service.admin_rbac_service.AdminRbacService.update_role", _update, raising=False)

        resp = client.patch(
            f"/admin/roles/{role_id}",
            json={"name": "运营 2", "description": "更新", "permission_ids": []},
            headers={"Authorization": "Bearer admin-token"},
        )

        assert resp.status_code == 200
        assert resp.json["code"] == HttpCode.SUCCESS
        assert captured == {
            "role_id": role_id,
            "name": "运营 2",
            "description": "更新",
            "permission_ids": [],
            "operator_id": "admin-1",
            "ip": "127.0.0.1",
            "user_agent": "Werkzeug/3.1.6",
        }

    def test_delete_role_should_delegate_to_service(self, client, monkeypatch):
        _mock_current_admin(monkeypatch, ["role:delete"])
        role_id = uuid4()
        captured = {}

        def _delete(self, role_id_arg, *, operator_id=None, ip="", user_agent=""):
            captured.update({
                "role_id": role_id_arg,
                "operator_id": operator_id,
                "ip": ip,
                "user_agent": user_agent,
            })

        monkeypatch.setattr("internal.service.admin_rbac_service.AdminRbacService.delete_role", _delete, raising=False)

        resp = client.delete(f"/admin/roles/{role_id}", headers={"Authorization": "Bearer admin-token"})

        assert resp.status_code == 200
        assert resp.json["code"] == HttpCode.SUCCESS
        assert resp.json["message"] == "删除角色成功"
        assert captured == {
            "role_id": role_id,
            "operator_id": "admin-1",
            "ip": "127.0.0.1",
            "user_agent": "Werkzeug/3.1.6",
        }

    def test_list_permissions_should_delegate_to_service(self, client, monkeypatch):
        _mock_current_admin(monkeypatch, ["permission:read"])
        monkeypatch.setattr(
            "internal.service.admin_rbac_service.AdminRbacService.list_permissions",
            lambda self: [{"id": "permission-1", "code": "admin:access", "name": "访问管理后台", "resource": "admin", "action": "access"}],
            raising=False,
        )

        resp = client.get("/admin/permissions", headers={"Authorization": "Bearer admin-token"})

        assert resp.status_code == 200
        assert resp.json["code"] == HttpCode.SUCCESS
        assert resp.json["data"][0]["code"] == "admin:access"
