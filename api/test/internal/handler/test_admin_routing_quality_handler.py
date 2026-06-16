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


class TestAdminRoutingQualityApi:
    def test_create_feedback_should_require_permission(self, client, monkeypatch):
        admin_id = _mock_current_admin(monkeypatch, ["routing_quality:feedback"])
        routing_log_id = uuid4()
        captured = {}

        def _create_feedback(self, **kwargs):
            captured.update(kwargs)
            return {
                "id": str(uuid4()),
                "routing_log_id": str(kwargs["routing_log_id"]),
                "source": "admin",
                "rating": kwargs["rating"],
                "dimension_scores": kwargs["dimension_scores"],
                "comment": kwargs["comment"],
                "metadata": kwargs["metadata"],
                "created_by": str(kwargs["created_by"]),
                "created_at": None,
            }

        monkeypatch.setattr(
            "internal.service.routing_quality_feedback_service."
            "RoutingQualityFeedbackService.create_feedback",
            _create_feedback,
        )

        resp = client.post(
            "/admin/routing-quality/feedback",
            json={
                "routing_log_id": str(routing_log_id),
                "rating": 4,
                "dimension_scores": {"accuracy": 5},
                "comment": "useful",
                "metadata": {"ticket_id": "T-1"},
            },
            headers={"Authorization": "Bearer admin-token"},
        )

        assert resp.status_code == 200
        assert resp.json["code"] == HttpCode.SUCCESS
        assert captured["routing_log_id"] == routing_log_id
        assert captured["source"] == "admin"
        assert captured["created_by"] == admin_id

    def test_list_feedback_should_require_read_permission(self, client, monkeypatch):
        _mock_current_admin(monkeypatch, ["routing_quality:read"])

        monkeypatch.setattr(
            "internal.service.routing_quality_feedback_service."
            "RoutingQualityFeedbackService.list_feedback",
            lambda self, **kwargs: [{"id": "feedback-1", "rating": 5}],
        )

        resp = client.get(
            "/admin/routing-quality/feedback",
            headers={"Authorization": "Bearer admin-token"},
        )

        assert resp.status_code == 200
        assert resp.json["data"][0]["id"] == "feedback-1"

    def test_metrics_should_require_read_permission(self, client, monkeypatch):
        _mock_current_admin(monkeypatch, ["routing_quality:read"])

        monkeypatch.setattr(
            "internal.service.routing_quality_metrics_service."
            "RoutingQualityMetricsService.build_metrics",
            lambda self: {"total_count": 0, "feedback_count": 0},
        )

        resp = client.get(
            "/admin/routing-quality/metrics",
            headers={"Authorization": "Bearer admin-token"},
        )

        assert resp.status_code == 200
        assert resp.json["data"]["total_count"] == 0

    def test_suggestions_should_require_read_permission(self, client, monkeypatch):
        _mock_current_admin(monkeypatch, ["routing_quality:read"])

        monkeypatch.setattr(
            "internal.service.routing_quality_metrics_service."
            "RoutingQualityMetricsService.build_metrics",
            lambda self: {"total_count": 0, "feedback_count": 0},
        )
        monkeypatch.setattr(
            "internal.service.routing_optimization_suggestion_service."
            "RoutingOptimizationSuggestionService.generate_suggestions",
            lambda self, metrics: [{"suggestion_type": "collect_more_feedback"}],
        )

        resp = client.get(
            "/admin/routing-quality/suggestions",
            headers={"Authorization": "Bearer admin-token"},
        )

        assert resp.status_code == 200
        assert resp.json["data"][0]["suggestion_type"] == "collect_more_feedback"
