from datetime import datetime
from types import SimpleNamespace
from unittest.mock import MagicMock

from internal.service.cost_stats_service import CostStatsService


def _make_service():
    service = CostStatsService.__new__(CostStatsService)
    service.db = SimpleNamespace(session=SimpleNamespace(query=MagicMock()))
    return service


def _mock_query_result(rows):
    q = MagicMock()
    q.select_from.return_value = q
    q.filter.return_value = q
    q.group_by.return_value = q
    q.order_by.return_value = q
    q.limit.return_value = q
    q.first.return_value = rows[0] if rows else None
    q.all.return_value = rows
    return q


def test_overview_returns_aggregated_credits():
    service = _make_service()
    row = SimpleNamespace(
        total_credits=500,
        total_requests=10,
    )
    service.db.session.query.return_value = _mock_query_result([row])
    service.db.session.query.return_value.filter.return_value = service.db.session.query.return_value

    result = service.overview()

    assert result["total_credits"] == 500
    assert result["total_requests"] == 10
    assert result["avg_cost_per_request"] == 50.0
    assert result["total_input_tokens"] == 0
    assert result["total_output_tokens"] == 0


def test_overview_zero_requests_returns_zero_avg():
    service = _make_service()
    row = SimpleNamespace(total_credits=0, total_requests=0)
    service.db.session.query.return_value = _mock_query_result([row])
    service.db.session.query.return_value.filter.return_value = service.db.session.query.return_value

    result = service.overview()

    assert result["avg_cost_per_request"] == 0.0


def test_by_dimension_returns_sorted_items():
    service = _make_service()
    rows = [
        SimpleNamespace(name="user-a", total_credits=300, request_count=5),
        SimpleNamespace(name="user-b", total_credits=200, request_count=3),
    ]
    service.db.session.query.return_value = _mock_query_result(rows)
    service.db.session.query.return_value.filter.return_value = service.db.session.query.return_value
    service.db.session.query.return_value.group_by.return_value = service.db.session.query.return_value
    service.db.session.query.return_value.order_by.return_value = service.db.session.query.return_value
    service.db.session.query.return_value.limit.return_value = service.db.session.query.return_value

    result = service.by_dimension(dimension="user")

    assert result["dimension"] == "user"
    assert len(result["items"]) == 2
    assert result["items"][0]["name"] == "user-a"
    assert result["items"][0]["percentage"] == 60.0
    assert result["total_credits"] == 500


def test_timeseries_returns_points():
    service = _make_service()
    rows = [
        SimpleNamespace(
            ts=datetime(2026, 7, 1, 0, 0, 0),
            total_credits=100,
            request_count=2,
        ),
    ]
    service.db.session.query.return_value = _mock_query_result(rows)
    service.db.session.query.return_value.filter.return_value = service.db.session.query.return_value
    service.db.session.query.return_value.group_by.return_value = service.db.session.query.return_value
    service.db.session.query.return_value.order_by.return_value = service.db.session.query.return_value

    result = service.timeseries(granularity="day")

    assert result["granularity"] == "day"
    assert len(result["points"]) == 1
    assert result["points"][0]["total_credits"] == 100
    assert result["points"][0]["request_count"] == 2
