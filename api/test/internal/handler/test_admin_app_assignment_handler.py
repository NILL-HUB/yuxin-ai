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


class TestAdminAppAssignmentHandler:
    def test_list_assignments_should_delegate_to_service(self, client, monkeypatch):
        account_id = uuid4()
        captured = {}
        _mock_current_admin(monkeypatch, ["app_assignment:read"])

        def _list(self, account_id_arg):
            captured["account_id"] = account_id_arg
            return {"list": [{"id": "assignment-1", "status": "active", "app": {"id": "app-1", "name": "AI App"}}]}

        monkeypatch.setattr("internal.service.admin_app_assignment_service.AdminAppAssignmentService.list_assignments", _list, raising=False)

        resp = client.get(f"/admin/users/{account_id}/app-assignments", headers={"Authorization": "Bearer admin-token"})

        assert resp.status_code == 200
        assert resp.json["code"] == HttpCode.SUCCESS
        assert resp.json["data"]["list"][0]["app"]["name"] == "AI App"
        assert captured == {"account_id": account_id}

    def test_assign_apps_should_delegate_to_service(self, client, monkeypatch):
        account_id = uuid4()
        app_id = uuid4()
        captured = {}
        _mock_current_admin(monkeypatch, ["app_assignment:update"])

        def _assign(self, account_id_arg, app_ids, *, operator_id=None, ip="", user_agent=""):
            captured.update({"account_id": account_id_arg, "app_ids": app_ids, "operator_id": operator_id, "ip": ip, "user_agent": user_agent})
            return {"assigned": 1, "reactivated": 0, "skipped": 0, "list": []}

        monkeypatch.setattr("internal.service.admin_app_assignment_service.AdminAppAssignmentService.assign_apps", _assign, raising=False)

        resp = client.post(
            f"/admin/users/{account_id}/app-assignments",
            json={"app_ids": [str(app_id)]},
            headers={"Authorization": "Bearer admin-token"},
        )

        assert resp.status_code == 200
        assert resp.json["code"] == HttpCode.SUCCESS
        assert resp.json["data"]["assigned"] == 1
        assert captured == {
            "account_id": account_id,
            "app_ids": [app_id],
            "operator_id": "admin-1",
            "ip": "127.0.0.1",
            "user_agent": "Werkzeug/3.1.6",
        }

    def test_revoke_assignment_should_delegate_to_service(self, client, monkeypatch):
        account_id = uuid4()
        assignment_id = uuid4()
        captured = {}
        _mock_current_admin(monkeypatch, ["app_assignment:update"])

        def _revoke(self, account_id_arg, assignment_id_arg, *, operator_id=None, ip="", user_agent=""):
            captured.update({"account_id": account_id_arg, "assignment_id": assignment_id_arg, "operator_id": operator_id, "ip": ip, "user_agent": user_agent})
            return {"id": str(assignment_id_arg), "status": "revoked"}

        monkeypatch.setattr("internal.service.admin_app_assignment_service.AdminAppAssignmentService.revoke_assignment", _revoke, raising=False)

        resp = client.post(
            f"/admin/users/{account_id}/app-assignments/{assignment_id}/revoke",
            headers={"Authorization": "Bearer admin-token"},
        )

        assert resp.status_code == 200
        assert resp.json["code"] == HttpCode.SUCCESS
        assert resp.json["data"]["status"] == "revoked"
        assert captured == {
            "account_id": account_id,
            "assignment_id": assignment_id,
            "operator_id": "admin-1",
            "ip": "127.0.0.1",
            "user_agent": "Werkzeug/3.1.6",
        }
