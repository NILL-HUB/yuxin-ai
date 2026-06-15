from flask import Flask, g

from internal.middleware.admin_auth import admin_login_required, permission_required
from pkg.response import HttpCode


class TestAdminLoginRequired:
    def test_admin_login_required_should_reject_missing_bearer_token(self, monkeypatch):
        app = Flask(__name__)
        app.config["PROPAGATE_EXCEPTIONS"] = False
        app.config["TESTING"] = True

        @app.errorhandler(Exception)
        def _handle_exception(error):
            from internal.exception.exception import UnauthorizedException
            from pkg.response import unauthorized_message
            if isinstance(error, UnauthorizedException):
                return unauthorized_message(error.message)
            raise error

        @app.get("/admin/protected")
        @admin_login_required
        def _protected():
            return {"ok": True}

        client = app.test_client()
        resp = client.get("/admin/protected")

        assert resp.status_code == 200
        assert resp.json["code"] == HttpCode.UNAUTHORIZED

    def test_admin_login_required_should_set_current_admin_context(self, monkeypatch):
        app = Flask(__name__)
        app.config["TESTING"] = True
        captured = {}

        def _get_current_admin_from_token(self, token):
            captured["token"] = token
            return {
                "id": "admin-1",
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
        )

        @app.get("/admin/protected")
        @admin_login_required
        def _protected():
            return {
                "admin": g.current_admin_user,
                "roles": g.current_admin_roles,
                "permissions": g.current_admin_permissions,
            }

        client = app.test_client()
        resp = client.get("/admin/protected", headers={"Authorization": "Bearer admin-token"})

        assert resp.status_code == 200
        assert resp.json["admin"]["id"] == "admin-1"
        assert resp.json["roles"] == ["super_admin"]
        assert resp.json["permissions"] == ["admin:access"]
        assert captured == {"token": "admin-token"}

    def test_permission_required_should_allow_admin_with_permission(self):
        app = Flask(__name__)
        app.config["TESTING"] = True

        @app.get("/admin/apps")
        @permission_required("app:read")
        def _protected():
            return {"ok": True}

        client = app.test_client()
        with client:
            with client.application.test_request_context(headers={"Authorization": "Bearer admin-token"}):
                g.current_admin_permissions = ["admin:access", "app:read"]
                resp = _protected()

        assert resp == {"ok": True}

    def test_permission_required_should_reject_admin_without_permission(self):
        app = Flask(__name__)
        app.config["TESTING"] = True

        @app.errorhandler(Exception)
        def _handle_exception(error):
            from internal.exception.exception import ForbiddenException
            from pkg.response import forbidden_message
            if isinstance(error, ForbiddenException):
                return forbidden_message(error.message)
            raise error

        @app.get("/admin/apps")
        @permission_required("app:update")
        def _protected():
            return {"ok": True}

        client = app.test_client()
        with client:
            with client.application.test_request_context(headers={"Authorization": "Bearer admin-token"}):
                g.current_admin_permissions = ["app:read"]
                try:
                    _protected()
                except Exception as error:
                    resp = _handle_exception(error)

        assert resp[0].json["code"] == HttpCode.FORBIDDEN
