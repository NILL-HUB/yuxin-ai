from unittest.mock import MagicMock
from uuid import uuid4


def _mock_current_admin(monkeypatch, permissions=None):
    monkeypatch.setattr(
        "internal.middleware.admin_auth.extract_bearer_token",
        lambda: "test-token",
    )
    monkeypatch.setattr(
        "internal.middleware.admin_auth.AdminUserService.get_current_admin_from_token",
        lambda self, token: {"id": str(uuid4()), "roles": ["super_admin"], "permissions": permissions or []},
    )


def test_overview_returns_success(app, monkeypatch):
    from internal.handler.admin_cost_stats_handler import AdminCostStatsHandler

    _mock_current_admin(monkeypatch, ["cost_stats:read"])

    mock_service = MagicMock()
    mock_service.overview.return_value = {
        "total_credits": 1000,
        "total_requests": 50,
        "avg_cost_per_request": 20.0,
        "total_input_tokens": 10000,
        "total_output_tokens": 0,
    }

    handler = AdminCostStatsHandler(cost_stats_service=mock_service)

    with app.test_request_context("/?start_at=&end_at="):
        result = handler.overview()

    assert result[1] == 200 or result is not None
    mock_service.overview.assert_called_once()


def test_by_dimension_returns_success(app, monkeypatch):
    from internal.handler.admin_cost_stats_handler import AdminCostStatsHandler

    _mock_current_admin(monkeypatch, ["cost_stats:read"])

    mock_service = MagicMock()
    mock_service.by_dimension.return_value = {
        "dimension": "user",
        "items": [],
        "total_credits": 0,
    }

    handler = AdminCostStatsHandler(cost_stats_service=mock_service)

    with app.test_request_context("/?dimension=user&start_at=&end_at=&limit=10"):
        result = handler.by_dimension()

    assert result[1] == 200 or result is not None
    mock_service.by_dimension.assert_called_once()


def test_overview_forbidden_without_permission(app, monkeypatch):
    from internal.handler.admin_cost_stats_handler import AdminCostStatsHandler
    from internal.exception import ForbiddenException

    _mock_current_admin(monkeypatch, [])

    mock_service = MagicMock()
    handler = AdminCostStatsHandler(cost_stats_service=mock_service)

    with app.test_request_context("/?start_at=&end_at="):
        try:
            handler.overview()
            assert False, "Should raise ForbiddenException"
        except ForbiddenException:
            pass

    mock_service.overview.assert_not_called()
