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


class TestAdminCustomerUserHandler:
    def test_list_customer_users_should_delegate_to_service(self, client, monkeypatch):
        captured = {}
        _mock_current_admin(monkeypatch, ["user:read"])

        def _list(self, *, keyword, status, current_page, page_size):
            captured.update({
                "keyword": keyword,
                "status": status,
                "current_page": current_page,
                "page_size": page_size,
            })
            return {
                "list": [{
                    "id": "user-1",
                    "email": "user@example.com",
                    "name": "User",
                    "avatar": "",
                    "status": "active",
                    "disabled_at": None,
                    "disabled_by": None,
                    "disabled_reason": "",
                    "last_login_at": 1893456000,
                    "last_login_ip": "127.0.0.1",
                    "created_at": 1861920000,
                }],
                "paginator": {"total_record": 1, "total_page": 1, "current_page": 1, "page_size": 20},
            }

        monkeypatch.setattr("internal.service.admin_customer_user_service.AdminCustomerUserService.list_customer_users", _list, raising=False)

        resp = client.get(
            "/admin/users?keyword=user&status=active&current_page=1&page_size=20",
            headers={"Authorization": "Bearer admin-token"},
        )

        assert resp.status_code == 200
        assert resp.json["code"] == HttpCode.SUCCESS
        assert resp.json["data"]["list"][0]["email"] == "user@example.com"
        assert captured == {"keyword": "user", "status": "active", "current_page": 1, "page_size": 20}

    def test_get_customer_user_should_delegate_to_service(self, client, monkeypatch):
        account_id = uuid4()
        captured = {}
        _mock_current_admin(monkeypatch, ["user:read"])

        def _get(self, account_id_arg):
            captured["account_id"] = account_id_arg
            return {
                "id": str(account_id_arg),
                "email": "user@example.com",
                "name": "User",
                "avatar": "",
                "status": "active",
                "disabled_at": None,
                "disabled_by": None,
                "disabled_reason": "",
                "last_login_at": 1893456000,
                "last_login_ip": "127.0.0.1",
                "created_at": 1861920000,
                "sessions": [],
            }

        monkeypatch.setattr("internal.service.admin_customer_user_service.AdminCustomerUserService.get_customer_user", _get, raising=False)

        resp = client.get(f"/admin/users/{account_id}", headers={"Authorization": "Bearer admin-token"})

        assert resp.status_code == 200
        assert resp.json["code"] == HttpCode.SUCCESS
        assert resp.json["data"]["id"] == str(account_id)
        assert captured == {"account_id": account_id}

    def test_disable_customer_user_should_delegate_to_service(self, client, monkeypatch):
        account_id = uuid4()
        captured = {}
        _mock_current_admin(monkeypatch, ["user:disable"])

        def _disable(self, account_id_arg, *, reason="", operator_id=None, ip="", user_agent=""):
            captured.update({
                "account_id": account_id_arg,
                "reason": reason,
                "operator_id": operator_id,
                "ip": ip,
                "user_agent": user_agent,
            })
            return {
                "id": str(account_id_arg),
                "email": "user@example.com",
                "name": "User",
                "avatar": "",
                "status": "disabled",
                "disabled_at": 1893456000,
                "disabled_by": operator_id,
                "disabled_reason": reason,
                "last_login_at": 1893456000,
                "last_login_ip": "127.0.0.1",
                "created_at": 1861920000,
            }

        monkeypatch.setattr("internal.service.admin_customer_user_service.AdminCustomerUserService.disable_customer_user", _disable, raising=False)

        resp = client.post(
            f"/admin/users/{account_id}/disable",
            json={"reason": "risk"},
            headers={"Authorization": "Bearer admin-token"},
        )

        assert resp.status_code == 200
        assert resp.json["code"] == HttpCode.SUCCESS
        assert resp.json["data"]["status"] == "disabled"
        assert captured == {
            "account_id": account_id,
            "reason": "risk",
            "operator_id": "admin-1",
            "ip": "127.0.0.1",
            "user_agent": "Werkzeug/3.1.6",
        }

    def test_enable_customer_user_should_delegate_to_service(self, client, monkeypatch):
        account_id = uuid4()
        captured = {}
        _mock_current_admin(monkeypatch, ["user:update"])

        def _enable(self, account_id_arg, *, operator_id=None, ip="", user_agent=""):
            captured.update({
                "account_id": account_id_arg,
                "operator_id": operator_id,
                "ip": ip,
                "user_agent": user_agent,
            })
            return {
                "id": str(account_id_arg),
                "email": "user@example.com",
                "name": "User",
                "avatar": "",
                "status": "active",
                "disabled_at": None,
                "disabled_by": None,
                "disabled_reason": "",
                "last_login_at": 1893456000,
                "last_login_ip": "127.0.0.1",
                "created_at": 1861920000,
            }

        monkeypatch.setattr("internal.service.admin_customer_user_service.AdminCustomerUserService.enable_customer_user", _enable, raising=False)

        resp = client.post(f"/admin/users/{account_id}/enable", headers={"Authorization": "Bearer admin-token"})

        assert resp.status_code == 200
        assert resp.json["code"] == HttpCode.SUCCESS
        assert resp.json["data"]["status"] == "active"
        assert captured == {
            "account_id": account_id,
            "operator_id": "admin-1",
            "ip": "127.0.0.1",
            "user_agent": "Werkzeug/3.1.6",
        }

    def test_revoke_customer_user_sessions_should_delegate_to_service(self, client, monkeypatch):
        account_id = uuid4()
        captured = {}
        _mock_current_admin(monkeypatch, ["user:update"])

        def _revoke(self, account_id_arg, *, operator_id=None, ip="", user_agent=""):
            captured.update({
                "account_id": account_id_arg,
                "operator_id": operator_id,
                "ip": ip,
                "user_agent": user_agent,
            })
            return {"revoked_sessions": 2}

        monkeypatch.setattr("internal.service.admin_customer_user_service.AdminCustomerUserService.revoke_customer_user_sessions", _revoke, raising=False)

        resp = client.post(f"/admin/users/{account_id}/sessions/revoke", headers={"Authorization": "Bearer admin-token"})

        assert resp.status_code == 200
        assert resp.json["code"] == HttpCode.SUCCESS
        assert resp.json["data"] == {"revoked_sessions": 2}
        assert captured == {
            "account_id": account_id,
            "operator_id": "admin-1",
            "ip": "127.0.0.1",
            "user_agent": "Werkzeug/3.1.6",
        }

    def test_list_customer_users_should_reject_missing_permission(self, client, monkeypatch):
        _mock_current_admin(monkeypatch, ["admin:access"])

        resp = client.get("/admin/users", headers={"Authorization": "Bearer admin-token"})

        assert resp.status_code == 200
        assert resp.json["code"] == HttpCode.FORBIDDEN
