from types import SimpleNamespace
from uuid import uuid4

from pkg.response import HttpCode


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


_RETENTION_DESCRIBE = {
    "retention_days": 30,
    "default_retention_days": 30,
    "min_retention_days": 1,
    "max_retention_days": 3650,
    "code": "ROUTING_LOG_RETENTION_DAYS",
}


class TestRoutingLogHandler:
    def test_get_retention_should_return_configured_days(self, client, monkeypatch):
        _mock_current_admin(monkeypatch, ["routing_log:read"])
        monkeypatch.setattr(
            "internal.service.routing_log_retention_service."
            "RoutingLogRetentionService.describe",
            lambda self: _RETENTION_DESCRIBE | {"retention_days": 45},
        )

        resp = client.get(
            "/admin/routing-logs/retention",
            headers={"Authorization": "Bearer admin-token"},
        )

        assert resp.status_code == 200
        assert resp.json["code"] == HttpCode.SUCCESS
        assert resp.json["data"]["retention_days"] == 45
        assert resp.json["data"]["code"] == "ROUTING_LOG_RETENTION_DAYS"

    def test_set_retention_should_delegate_to_service_with_admin(self, client, monkeypatch):
        admin_id = _mock_current_admin(monkeypatch, ["routing_log:update"])
        captured = {}

        def _set_retention_days(self, days, user_id):
            captured["days"] = days
            captured["user_id"] = user_id
            return days

        monkeypatch.setattr(
            "internal.service.routing_log_retention_service."
            "RoutingLogRetentionService.set_retention_days",
            _set_retention_days,
        )
        monkeypatch.setattr(
            "internal.service.routing_log_retention_service."
            "RoutingLogRetentionService.describe",
            lambda self: _RETENTION_DESCRIBE | {"retention_days": 60},
        )

        resp = client.post(
            "/admin/routing-logs/retention",
            json={"retention_days": 60},
            headers={"Authorization": "Bearer admin-token"},
        )

        assert resp.status_code == 200
        assert resp.json["code"] == HttpCode.SUCCESS
        assert captured["days"] == 60
        assert captured["user_id"] == admin_id
        assert resp.json["data"]["retention_days"] == 60

    def test_set_retention_should_reject_invalid_days(self, client, monkeypatch):
        _mock_current_admin(monkeypatch, ["routing_log:update"])

        resp = client.post(
            "/admin/routing-logs/retention",
            json={"retention_days": 0},
            headers={"Authorization": "Bearer admin-token"},
        )

        assert resp.json["code"] != HttpCode.SUCCESS

    def test_summary_should_return_simplified_user_view(self, client, monkeypatch):
        account_id = uuid4()
        monkeypatch.setattr(
            "internal.handler.routing_log_handler.current_user",
            SimpleNamespace(id=account_id, is_authenticated=True),
        )
        captured = {}

        def _get_user_summary(self, account_id_arg):
            captured["account_id"] = account_id_arg
            return {
                "recent": [
                    {
                        "id": "log-1",
                        "status": "success",
                        "created_at": 1893456000,
                        "total_credits": 1.5,
                        "progress": "completed",
                        "event_count": 2,
                    }
                ],
                "summary": {
                    "total_count": 1,
                    "success_count": 1,
                    "fallback_count": 0,
                    "total_credits": 1.5,
                },
            }

        monkeypatch.setattr(
            "internal.service.user_routing_summary_service."
            "UserRoutingSummaryService.get_user_summary",
            _get_user_summary,
        )

        resp = client.get("/routing-logs/summary")

        assert resp.status_code == 200
        assert resp.json["code"] == HttpCode.SUCCESS
        assert captured["account_id"] == account_id
        assert resp.json["data"]["summary"]["total_count"] == 1
        assert resp.json["data"]["recent"][0]["progress"] == "completed"
        assert "agent_candidates" not in resp.json["data"]["recent"][0]
