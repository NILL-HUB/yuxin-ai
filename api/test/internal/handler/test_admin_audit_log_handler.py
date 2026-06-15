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


class TestAdminAuditLogHandler:
    def test_list_audit_logs_should_delegate_to_service(self, client, monkeypatch):
        captured = {}
        _mock_current_admin(monkeypatch, ["audit_log:read"])

        def _list(self, *, action, resource_type, admin_user_id, start_time, end_time, current_page, page_size):
            captured.update({
                "action": action,
                "resource_type": resource_type,
                "admin_user_id": admin_user_id,
                "start_time": start_time,
                "end_time": end_time,
                "current_page": current_page,
                "page_size": page_size,
            })
            return {
                "list": [{
                    "id": "log-1",
                    "admin_user_id": "admin-1",
                    "action": "admin_user:disable",
                    "resource_type": "admin_user",
                    "resource_id": "admin-2",
                    "ip": "127.0.0.1",
                    "user_agent": "pytest",
                    "before_data": {"status": "active"},
                    "after_data": {"status": "disabled"},
                    "created_at": 1893456000,
                }],
                "paginator": {"total_record": 1, "total_page": 1, "current_page": 1, "page_size": 20},
            }

        monkeypatch.setattr("internal.service.audit_log_service.AuditLogService.list_audit_logs", _list, raising=False)

        resp = client.get(
            "/admin/audit-logs?action=admin_user:disable&resource_type=admin_user&admin_user_id=admin-1&start_time=1893456000&end_time=1893542400&current_page=1&page_size=20",
            headers={"Authorization": "Bearer admin-token"},
        )

        assert resp.status_code == 200
        assert resp.json["code"] == HttpCode.SUCCESS
        assert resp.json["data"]["list"][0]["action"] == "admin_user:disable"
        assert captured == {
            "action": "admin_user:disable",
            "resource_type": "admin_user",
            "admin_user_id": "admin-1",
            "start_time": 1893456000,
            "end_time": 1893542400,
            "current_page": 1,
            "page_size": 20,
        }

    def test_list_audit_logs_should_reject_missing_permission(self, client, monkeypatch):
        _mock_current_admin(monkeypatch, ["admin:access"])

        resp = client.get("/admin/audit-logs", headers={"Authorization": "Bearer admin-token"})

        assert resp.status_code == 200
        assert resp.json["code"] == HttpCode.FORBIDDEN
