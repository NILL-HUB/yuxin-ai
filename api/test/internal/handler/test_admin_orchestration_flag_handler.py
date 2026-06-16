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


class TestAdminOrchestrationFlagApi:
    def test_list_should_require_permission_and_return_flags(self, client, monkeypatch):
        _mock_current_admin(monkeypatch, ["orchestration_flag:read"])

        def _list_flags(self):
            return [
                {
                    "code": "ENABLE_ORCHESTRATOR",
                    "name": "Orchestrator",
                    "description": "Enable orchestrator",
                    "enabled": True,
                    "risk_level": "medium",
                    "fallback_behavior": "direct_answer",
                    "updated_by": None,
                }
            ]

        monkeypatch.setattr(
            "internal.service.orchestration_feature_flag_service."
            "OrchestrationFeatureFlagService.list_flags",
            _list_flags,
        )

        resp = client.get(
            "/admin/orchestration-flags",
            headers={"Authorization": "Bearer admin-token"},
        )

        assert resp.status_code == 200
        assert resp.json["code"] == HttpCode.SUCCESS
        assert resp.json["data"][0]["code"] == "ENABLE_ORCHESTRATOR"

    def test_update_should_require_permission_and_delegate(self, client, monkeypatch):
        admin_id = uuid4()

        def _get_current_admin_from_token(self, token):
            return {
                "id": str(admin_id),
                "email": "root@example.com",
                "name": "Root",
                "avatar": "",
                "status": "active",
                "roles": ["super_admin"],
                "permissions": ["orchestration_flag:update"],
            }

        monkeypatch.setattr(
            "internal.service.admin_user_service.AdminUserService."
            "get_current_admin_from_token",
            _get_current_admin_from_token,
        )
        captured = {}

        def _update_flag(self, *, code, enabled, operator_id):
            captured.update({
                "code": code,
                "enabled": enabled,
                "operator_id": operator_id,
            })
            return {
                "code": code,
                "name": "Orchestrator",
                "description": "Enable orchestrator",
                "enabled": enabled,
                "risk_level": "medium",
                "fallback_behavior": "direct_answer",
                "updated_by": str(operator_id),
            }

        monkeypatch.setattr(
            "internal.service.orchestration_feature_flag_service."
            "OrchestrationFeatureFlagService.update_flag",
            _update_flag,
        )

        resp = client.post(
            "/admin/orchestration-flags/ENABLE_ORCHESTRATOR",
            json={"enabled": False},
            headers={"Authorization": "Bearer admin-token"},
        )

        assert resp.status_code == 200
        assert resp.json["data"]["enabled"] is False
        assert captured == {
            "code": "ENABLE_ORCHESTRATOR",
            "enabled": False,
            "operator_id": admin_id,
        }

    def test_update_should_reject_unknown_code(self, client, monkeypatch):
        _mock_current_admin(monkeypatch, ["orchestration_flag:update"])

        def _update_flag(self, *, code, enabled, operator_id):
            raise ValueError("Unknown orchestration feature flag: UNKNOWN")

        monkeypatch.setattr(
            "internal.service.orchestration_feature_flag_service."
            "OrchestrationFeatureFlagService.update_flag",
            _update_flag,
        )

        resp = client.post(
            "/admin/orchestration-flags/UNKNOWN",
            json={"enabled": True},
            headers={"Authorization": "Bearer admin-token"},
        )

        assert resp.status_code == 200
        assert resp.json["code"] == HttpCode.FAIL
