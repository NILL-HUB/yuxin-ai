from datetime import UTC, datetime
from unittest.mock import MagicMock, Mock
from uuid import uuid4

import pytest

from internal.service.user_routing_summary_service import UserRoutingSummaryService


class TestUserRoutingSummaryService:
    @pytest.fixture
    def service(self):
        return UserRoutingSummaryService(db=MagicMock())

    @staticmethod
    def _build_log(status="success", cost=1.5, events=None, decision=None):
        log = Mock()
        log.id = uuid4()
        log.status = status
        log.cost_summary = {"total_credits": cost}
        if decision is None:
            decision = {"routing_events": events or []}
        log.routing_decision = decision
        log.created_at = datetime(2026, 1, 1, 0, 0, 0, tzinfo=UTC)
        return log

    def _set_logs(self, service, logs):
        service.db.session.query.return_value.filter.return_value.order_by.return_value.limit.return_value.all.return_value = logs

    def test_get_user_summary_returns_simplified_items(self, service):
        log = self._build_log(
            status="success",
            cost=2.5,
            events=[
                {"event_type": "routing_started"},
                {"event_type": "synthesis_completed"},
            ],
        )
        self._set_logs(service, [log])

        result = service.get_user_summary(uuid4())

        assert result["summary"]["total_count"] == 1
        assert result["summary"]["total_credits"] == 2.5
        item = result["recent"][0]
        assert item["status"] == "success"
        assert item["total_credits"] == 2.5
        assert item["progress"] == "completed"
        assert item["event_count"] == 2

    def test_get_user_summary_does_not_leak_internal_fields(self, service):
        log = Mock()
        log.id = uuid4()
        log.status = "fallback"
        log.cost_summary = {"total_credits": 0}
        log.routing_decision = {
            "agent_candidates": [{"agent_id": "secret"}],
            "tool_candidates": [{"name": "secret"}],
            "model_selection": {"model_id": "secret"},
            "routing_events": [],
        }
        log.created_at = datetime(2026, 1, 1, 0, 0, 0, tzinfo=UTC)
        self._set_logs(service, [log])

        result = service.get_user_summary(uuid4())

        item = result["recent"][0]
        assert "agent_candidates" not in item
        assert "tool_candidates" not in item
        assert "model_selection" not in item
        assert "filtered_out_agents" not in item
        assert "key_usage" not in item

    def test_get_user_summary_aggregates_credits_and_status(self, service):
        log1 = self._build_log(status="success", cost=1.0)
        log2 = self._build_log(status="fallback", cost=2.0)
        self._set_logs(service, [log1, log2])

        result = service.get_user_summary(uuid4())

        assert result["summary"]["total_count"] == 2
        assert result["summary"]["success_count"] == 1
        assert result["summary"]["fallback_count"] == 1
        assert result["summary"]["total_credits"] == 3.0

    def test_get_user_summary_empty(self, service):
        self._set_logs(service, [])

        result = service.get_user_summary(uuid4())

        assert result["recent"] == []
        assert result["summary"]["total_count"] == 0
        assert result["summary"]["total_credits"] == 0

    def test_get_user_summary_progress_in_progress(self, service):
        log = self._build_log(
            status="running",
            cost=0,
            events=[{"event_type": "agent_selected"}],
        )
        self._set_logs(service, [log])

        result = service.get_user_summary(uuid4())

        assert result["recent"][0]["progress"] == "in_progress"

    def test_get_user_summary_clamps_limit(self, service):
        self._set_logs(service, [])
        service.get_user_summary(uuid4(), limit=99999)
        service.db.session.query.return_value.filter.return_value.order_by.return_value.limit.assert_called_with(100)
