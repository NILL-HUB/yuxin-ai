from uuid import uuid4

from pkg.response import HttpCode


def _mock_current_admin(monkeypatch, permissions):
    def _get_current_admin_from_token(self, token):
        return {
            "id": str(uuid4()),
            "email": "root@example.com",
            "name": "Root",
            "avatar": "",
            "status": "active",
            "roles": ["super_admin"],
            "permissions": permissions,
        }

    monkeypatch.setattr(
        "internal.service.admin_user_service.AdminUserService."
        "get_current_admin_from_token",
        _get_current_admin_from_token,
    )


class TestAdminOrchestrationReleaseApi:
    def test_release_check_should_require_permission_and_return_report(
        self,
        client,
        monkeypatch,
    ):
        _mock_current_admin(monkeypatch, ["orchestration_release:read"])

        def _build_report(self):
            return {
                "test_status": {},
                "migration_status": {},
                "feature_flags": [],
                "security_checklist": {},
                "cost_metrics": {},
                "routing_metrics": {},
                "rollback_plan": {"primary_action": "disable_feature_flags"},
                "warnings": [],
            }

        monkeypatch.setattr(
            "internal.service.orchestration_release_check_service."
            "OrchestrationReleaseCheckService.build_report",
            _build_report,
        )

        resp = client.get(
            "/admin/orchestration-release-check",
            headers={"Authorization": "Bearer admin-token"},
        )

        assert resp.status_code == 200
        assert resp.json["code"] == HttpCode.SUCCESS
        assert resp.json["data"]["rollback_plan"] == {
            "primary_action": "disable_feature_flags"
        }
