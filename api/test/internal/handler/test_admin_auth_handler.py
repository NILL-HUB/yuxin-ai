from uuid import uuid4

from pkg.response import HttpCode


class TestAdminAuthHandler:
    def test_admin_auth_login_should_delegate_to_admin_user_service(self, client, monkeypatch):
        captured = {}

        def _password_login(self, email, password):
            captured["email"] = email
            captured["password"] = password
            return {
                "access_token": "admin-token",
                "expire_at": 1893456000,
                "admin_user": {
                    "id": "admin-1",
                    "email": "root@example.com",
                    "name": "Root",
                    "avatar": "",
                    "status": "active",
                },
            }

        monkeypatch.setattr(
            "internal.service.admin_user_service.AdminUserService.password_login",
            _password_login,
        )

        resp = client.post(
            "/admin/auth/login",
            json={"email": "root@example.com", "password": "Root123456"},
        )

        assert resp.status_code == 200
        assert resp.json["code"] == HttpCode.SUCCESS
        assert resp.json["data"]["access_token"] == "admin-token"
        assert resp.json["data"]["admin_user"]["email"] == "root@example.com"
        assert "password" not in resp.json["data"]["admin_user"]
        assert captured == {"email": "root@example.com", "password": "Root123456"}

    def test_admin_auth_login_should_validate_required_fields(self, client):
        resp = client.post("/admin/auth/login", json={"email": "", "password": ""})

        assert resp.status_code == 200
        assert resp.json["code"] == HttpCode.VALIDATE_ERROR

    def test_admin_auth_me_should_require_admin_bearer_token(self, client):
        resp = client.get("/admin/auth/me")

        assert resp.status_code == 200
        assert resp.json["code"] == HttpCode.UNAUTHORIZED

    def test_admin_auth_me_should_return_current_admin_user(self, client, monkeypatch):
        admin_user_id = uuid4()
        captured = {}

        def _get_current_admin_from_token(self, token):
            captured["token"] = token
            return {
                "id": str(admin_user_id),
                "email": "root@example.com",
                "name": "Root",
                "avatar": "",
                "status": "active",
                "roles": ["super_admin"],
                "permissions": ["admin:access"],
            }

        monkeypatch.setattr(
            "internal.service.admin_user_service.AdminUserService.get_current_admin_from_token",
            _get_current_admin_from_token,
            raising=False,
        )

        resp = client.get("/admin/auth/me", headers={"Authorization": "Bearer admin-token"})

        assert resp.status_code == 200
        assert resp.json["code"] == HttpCode.SUCCESS
        assert resp.json["data"]["id"] == str(admin_user_id)
        assert resp.json["data"]["roles"] == ["super_admin"]
        assert resp.json["data"]["permissions"] == ["admin:access"]
        assert captured == {"token": "admin-token"}

    def test_admin_auth_change_password_should_delegate_to_service(self, client, monkeypatch):
        admin_user_id = uuid4()
        captured = {}

        def _get_current_admin_from_token(self, token):
            return {
                "id": str(admin_user_id),
                "username": "admin",
                "email": "",
                "name": "Root",
                "avatar": "",
                "status": "active",
                "roles": ["super_admin"],
                "permissions": ["admin:access"],
            }

        def _change_own_password(self, admin_id, *, current_password, new_password):
            captured.update({
                "admin_id": admin_id,
                "current_password": current_password,
                "new_password": new_password,
            })
            return {
                "id": str(admin_id),
                "username": "admin",
                "email": "",
                "name": "Root",
                "avatar": "",
                "status": "active",
            }

        monkeypatch.setattr(
            "internal.service.admin_user_service.AdminUserService.get_current_admin_from_token",
            _get_current_admin_from_token,
            raising=False,
        )
        monkeypatch.setattr(
            "internal.service.admin_user_service.AdminUserService.change_own_password",
            _change_own_password,
            raising=False,
        )

        resp = client.post(
            "/admin/auth/password",
            json={"current_password": "Root123456", "new_password": "New_123456"},
            headers={"Authorization": "Bearer admin-token"},
        )

        assert resp.status_code == 200
        assert resp.json["code"] == HttpCode.SUCCESS
        assert captured == {
            "admin_id": str(admin_user_id),
            "current_password": "Root123456",
            "new_password": "New_123456",
        }

    def test_admin_auth_logout_should_require_admin_bearer_token(self, client):
        resp = client.post("/admin/auth/logout")

        assert resp.status_code == 200
        assert resp.json["code"] == HttpCode.UNAUTHORIZED

    def test_admin_auth_logout_should_revoke_current_session(self, client, monkeypatch):
        captured = {}

        def _logout(self, token):
            captured["token"] = token

        monkeypatch.setattr(
            "internal.service.admin_user_service.AdminUserService.logout",
            _logout,
            raising=False,
        )

        resp = client.post("/admin/auth/logout", headers={"Authorization": "Bearer admin-token"})

        assert resp.status_code == 200
        assert resp.json["code"] == HttpCode.SUCCESS
        assert resp.json["message"] == "退出登录成功"
        assert captured == {"token": "admin-token"}
