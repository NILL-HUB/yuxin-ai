from types import SimpleNamespace
from uuid import uuid4

from pkg.response import HttpCode

_SUGGESTION_SERVICE = "internal.service.routing_optimization_suggestion_service.RoutingOptimizationSuggestionService"
_POLICY_SERVICE = "internal.service.routing_policy_change_service.RoutingPolicyChangeService"


def _mock_current_admin(monkeypatch, permissions):
    admin_id = uuid4()

    def _get_current_admin_from_token(self, token):
        return {
            "id": str(admin_id),
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
    return admin_id


class TestSuggestionFlowHandler:
    def test_accept_suggestion_should_return_accepted_status(self, client, monkeypatch):
        _mock_current_admin(monkeypatch, ["routing_quality:accept"])
        suggestion_id = uuid4()

        def _accept(self, sid, admin_uid):
            return {"suggestion_id": str(sid), "status": "accepted"}

        monkeypatch.setattr(f"{_SUGGESTION_SERVICE}.accept_suggestion", _accept)

        resp = client.post(
            f"/admin/routing-quality/suggestions/{suggestion_id}/accept",
            headers={"Authorization": "Bearer admin-token"},
        )
        assert resp.json["code"] == HttpCode.SUCCESS
        assert resp.json["data"]["status"] == "accepted"

    def test_dismiss_suggestion_should_return_dismissed_status(self, client, monkeypatch):
        _mock_current_admin(monkeypatch, ["routing_quality:dismiss"])
        suggestion_id = uuid4()

        def _dismiss(self, sid, admin_uid, reason):
            return {"suggestion_id": str(sid), "status": "dismissed"}

        monkeypatch.setattr(f"{_SUGGESTION_SERVICE}.dismiss_suggestion", _dismiss)

        resp = client.post(
            f"/admin/routing-quality/suggestions/{suggestion_id}/dismiss",
            json={"reason": "不适用"},
            headers={"Authorization": "Bearer admin-token"},
        )
        assert resp.json["code"] == HttpCode.SUCCESS
        assert resp.json["data"]["status"] == "dismissed"

    def test_preview_policy_change_should_return_preview(self, client, monkeypatch):
        _mock_current_admin(monkeypatch, ["routing_quality:read"])
        suggestion_id = uuid4()

        preview_data = {
            "suggestion_id": str(suggestion_id),
            "policy_type": "model_routing",
            "target_id": "gpt-4",
            "before_config": {"enabled": True},
            "after_config": {"enabled": False},
            "diff": {"changes": [{"field": "enabled", "before": True, "after": False}]},
            "impact": {"risk_level": "high"},
            "status": "pending",
        }

        def _generate_preview(self, sid):
            return preview_data

        monkeypatch.setattr(f"{_POLICY_SERVICE}.generate_preview", _generate_preview)

        resp = client.get(
            f"/admin/routing-quality/suggestions/{suggestion_id}/preview",
            headers={"Authorization": "Bearer admin-token"},
        )
        assert resp.json["code"] == HttpCode.SUCCESS
        assert resp.json["data"]["policy_type"] == "model_routing"
        assert resp.json["data"]["diff"]["changes"][0]["field"] == "enabled"

    def test_apply_policy_change_should_return_applied_status(self, client, monkeypatch):
        _mock_current_admin(monkeypatch, ["routing_quality:apply"])
        suggestion_id = uuid4()

        def _apply_draft(self, sid, admin_uid, data):
            return {"draft_id": str(uuid4()), "status": "applied", "suggestion_status": "applied"}

        monkeypatch.setattr(f"{_POLICY_SERVICE}.apply_draft", _apply_draft)

        resp = client.post(
            f"/admin/routing-quality/suggestions/{suggestion_id}/apply",
            json={"policy_type": "model_routing", "before_config": {}, "after_config": {}, "diff": {}, "impact": {}},
            headers={"Authorization": "Bearer admin-token"},
        )
        assert resp.json["code"] == HttpCode.SUCCESS
        assert resp.json["data"]["status"] == "applied"

    def test_rollback_policy_change_should_return_rolled_back_status(self, client, monkeypatch):
        _mock_current_admin(monkeypatch, ["routing_quality:rollback"])
        draft_id = uuid4()

        def _rollback_draft(self, did, admin_uid, reason):
            return {"draft_id": str(did), "status": "rolled_back"}

        monkeypatch.setattr(f"{_POLICY_SERVICE}.rollback_draft", _rollback_draft)

        resp = client.post(
            f"/admin/routing-quality/policy-changes/{draft_id}/rollback",
            json={"reason": "配置回滚"},
            headers={"Authorization": "Bearer admin-token"},
        )
        assert resp.json["code"] == HttpCode.SUCCESS
        assert resp.json["data"]["status"] == "rolled_back"

    def test_list_policy_changes_should_return_drafts(self, client, monkeypatch):
        _mock_current_admin(monkeypatch, ["routing_quality:read"])

        drafts = [
            {
                "id": str(uuid4()),
                "suggestion_id": str(uuid4()),
                "policy_type": "model_routing",
                "target_id": "gpt-4",
                "before_config": {},
                "after_config": {},
                "diff": {},
                "impact": {},
                "status": "applied",
                "applied_by": str(uuid4()),
                "applied_at": "2025-01-01T00:00:00",
                "rolled_back_at": None,
                "rollback_reason": "",
            }
        ]

        def _list_drafts(self, status=""):
            return drafts

        monkeypatch.setattr(f"{_POLICY_SERVICE}.list_drafts", _list_drafts)

        resp = client.get(
            "/admin/routing-quality/policy-changes",
            headers={"Authorization": "Bearer admin-token"},
        )
        assert resp.json["code"] == HttpCode.SUCCESS
        assert resp.json["data"]["total"] == 1
        assert resp.json["data"]["items"][0]["status"] == "applied"
