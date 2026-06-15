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


class TestAdminUserHandler:
    def test_list_admin_users_should_delegate_to_service(self, client, monkeypatch):
        captured = {}
        _mock_current_admin(monkeypatch, ["admin_user:read"])

        def _list(self, *, search, status, current_page, page_size):
            captured.update({
                "search": search,
                "status": status,
                "current_page": current_page,
                "page_size": page_size,
            })
            return {
                "list": [{"id": "admin-1", "email": "root@example.com", "name": "Root", "avatar": "", "status": "active", "roles": ["super_admin"]}],
                "paginator": {"total_record": 1, "total_page": 1, "current_page": 1, "page_size": 20},
            }

        monkeypatch.setattr("internal.service.admin_user_service.AdminUserService.list_admin_users", _list, raising=False)

        resp = client.get(
            "/admin/admin-users?search=root&status=active&current_page=1&page_size=20",
            headers={"Authorization": "Bearer admin-token"},
        )

        assert resp.status_code == 200
        assert resp.json["code"] == HttpCode.SUCCESS
        assert resp.json["data"]["list"][0]["email"] == "root@example.com"
        assert captured == {"search": "root", "status": "active", "current_page": 1, "page_size": 20}

    def test_get_admin_user_should_delegate_to_service(self, client, monkeypatch):
        admin_user_id = uuid4()
        captured = {}
        _mock_current_admin(monkeypatch, ["admin_user:read"])

        def _get(self, admin_id):
            captured["admin_id"] = admin_id
            return {"id": str(admin_id), "email": "ops@example.com", "name": "Ops", "avatar": "", "status": "active", "roles": []}

        monkeypatch.setattr("internal.service.admin_user_service.AdminUserService.get_admin_user", _get, raising=False)

        resp = client.get(f"/admin/admin-users/{admin_user_id}", headers={"Authorization": "Bearer admin-token"})

        assert resp.status_code == 200
        assert resp.json["code"] == HttpCode.SUCCESS
        assert resp.json["data"]["id"] == str(admin_user_id)
        assert captured == {"admin_id": admin_user_id}

    def test_create_admin_user_should_delegate_to_service(self, client, monkeypatch):
        captured = {}
        role_id = str(uuid4())
        _mock_current_admin(monkeypatch, ["admin_user:create"])

        def _create(self, *, email, name, password, role_ids, operator_id, ip, user_agent):
            captured.update({
                "email": email,
                "name": name,
                "password": password,
                "role_ids": role_ids,
                "operator_id": operator_id,
                "ip": ip,
                "user_agent": user_agent,
            })
            return {"id": "admin-2", "email": email, "name": name, "avatar": "", "status": "active", "roles": []}

        monkeypatch.setattr("internal.service.admin_user_service.AdminUserService.create_admin_user", _create, raising=False)

        resp = client.post(
            "/admin/admin-users",
            json={"email": "ops@example.com", "name": "Ops", "password": "Ops123456", "role_ids": [role_id]},
            headers={"Authorization": "Bearer admin-token"},
        )

        assert resp.status_code == 200
        assert resp.json["code"] == HttpCode.SUCCESS
        assert resp.json["data"]["email"] == "ops@example.com"
        assert captured == {
            "email": "ops@example.com",
            "name": "Ops",
            "password": "Ops123456",
            "role_ids": [role_id],
            "operator_id": "admin-1",
            "ip": "127.0.0.1",
            "user_agent": "Werkzeug/3.1.6",
        }

    def test_update_admin_user_should_delegate_to_service(self, client, monkeypatch):
        admin_user_id = uuid4()
        captured = {}
        _mock_current_admin(monkeypatch, ["admin_user:update"])

        def _update(self, admin_id, *, name=None, status=None, role_ids=None, operator_id=None, ip="", user_agent=""):
            captured.update({
                "admin_id": admin_id,
                "name": name,
                "status": status,
                "role_ids": role_ids,
                "operator_id": operator_id,
                "ip": ip,
                "user_agent": user_agent,
            })
            return {"id": str(admin_id), "email": "ops@example.com", "name": name, "avatar": "", "status": status, "roles": []}

        monkeypatch.setattr("internal.service.admin_user_service.AdminUserService.update_admin_user", _update, raising=False)

        resp = client.patch(
            f"/admin/admin-users/{admin_user_id}",
            json={"name": "Ops 2", "status": "disabled", "role_ids": []},
            headers={"Authorization": "Bearer admin-token"},
        )

        assert resp.status_code == 200
        assert resp.json["code"] == HttpCode.SUCCESS
        assert captured == {
            "admin_id": admin_user_id,
            "name": "Ops 2",
            "status": "disabled",
            "role_ids": [],
            "operator_id": "admin-1",
            "ip": "127.0.0.1",
            "user_agent": "Werkzeug/3.1.6",
        }

    def test_disable_admin_user_should_delegate_to_service(self, client, monkeypatch):
        admin_user_id = uuid4()
        captured = {}
        _mock_current_admin(monkeypatch, ["admin_user:disable"])

        def _disable(self, admin_id, *, operator_id=None, ip="", user_agent=""):
            captured.update({
                "admin_id": admin_id,
                "operator_id": operator_id,
                "ip": ip,
                "user_agent": user_agent,
            })

        monkeypatch.setattr("internal.service.admin_user_service.AdminUserService.disable_admin_user", _disable, raising=False)

        resp = client.post(
            f"/admin/admin-users/{admin_user_id}/disable",
            headers={"Authorization": "Bearer admin-token"},
        )

        assert resp.status_code == 200
        assert resp.json["code"] == HttpCode.SUCCESS
        assert resp.json["message"] == "禁用管理员成功"
        assert captured == {
            "admin_id": admin_user_id,
            "operator_id": "admin-1",
            "ip": "127.0.0.1",
            "user_agent": "Werkzeug/3.1.6",
        }

    def test_list_admin_users_should_reject_missing_permission(self, client, monkeypatch):
        _mock_current_admin(monkeypatch, ["admin:access"])

        resp = client.get("/admin/admin-users", headers={"Authorization": "Bearer admin-token"})

        assert resp.status_code == 200
        assert resp.json["code"] == HttpCode.FORBIDDEN
