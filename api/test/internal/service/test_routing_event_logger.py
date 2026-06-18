from unittest.mock import MagicMock, Mock
from uuid import uuid4

import pytest

from internal.service.routing_event_logger import RoutingEventLogger


class TestRoutingEventLogger:
    @pytest.fixture
    def logger(self, monkeypatch):
        monkeypatch.setattr(
            "internal.service.routing_event_logger.flag_modified",
            lambda *args, **kwargs: None,
        )
        return RoutingEventLogger(db=MagicMock())

    def test_log_event_appends_event_to_routing_decision(self, logger):
        routing_log_id = uuid4()
        log = Mock()
        log.routing_decision = {"existing": "value"}
        db = MagicMock()
        db.session.query.return_value.filter.return_value.first.return_value = log
        logger.db = db

        result = logger.log_event("routing_started", routing_log_id, {"query": "hi"})

        assert result is not None
        assert result["event_type"] == "routing_started"
        assert result["routing_log_id"] == str(routing_log_id)
        events = log.routing_decision["routing_events"]
        assert len(events) == 1
        assert events[0]["event_type"] == "routing_started"
        assert events[0]["detail"] == {"query": "hi"}
        assert log.routing_decision["existing"] == "value"

    def test_log_event_returns_none_for_unknown_event_type(self, logger):
        db = MagicMock()
        logger.db = db

        result = logger.log_event("unknown_event", uuid4(), {})

        assert result is None
        db.session.query.assert_not_called()

    def test_log_event_returns_none_when_routing_log_missing(self, logger):
        db = MagicMock()
        db.session.query.return_value.filter.return_value.first.return_value = None
        logger.db = db

        result = logger.log_event("routing_started", uuid4(), {})

        assert result is None

    def test_log_event_appends_multiple_events_preserving_order(self, logger):
        routing_log_id = uuid4()
        log = Mock()
        log.routing_decision = {}
        db = MagicMock()
        db.session.query.return_value.filter.return_value.first.return_value = log
        logger.db = db

        logger.log_event("routing_started", routing_log_id, {})
        logger.log_event("task_classified", routing_log_id, {"intent": "x"})

        events = log.routing_decision["routing_events"]
        assert [e["event_type"] for e in events] == [
            "routing_started",
            "task_classified",
        ]

    def test_log_event_noop_when_routing_log_id_is_none(self, logger):
        db = MagicMock()
        logger.db = db

        result = logger.log_event("routing_started", None, {})

        assert result is None
        db.session.query.assert_not_called()

    def test_log_events_batches_multiple_events(self, logger):
        routing_log_id = uuid4()
        log = Mock()
        log.routing_decision = {}
        db = MagicMock()
        db.session.query.return_value.filter.return_value.first.return_value = log
        logger.db = db

        events = [
            {
                "event_type": "routing_started",
                "routing_log_id": routing_log_id,
                "detail": {},
            },
            {
                "event_type": "task_classified",
                "routing_log_id": routing_log_id,
                "detail": {"intent": "x"},
            },
            {
                "event_type": "unknown_event",
                "routing_log_id": routing_log_id,
                "detail": {},
            },
        ]
        appended = logger.log_events(events)

        assert len(appended) == 2
        types = [e["event_type"] for e in log.routing_decision["routing_events"]]
        assert types == ["routing_started", "task_classified"]

    def test_log_events_empty_list_returns_empty(self, logger):
        logger.db = MagicMock()

        assert logger.log_events([]) == []

    def test_log_events_skips_entries_without_routing_log_id(self, logger):
        log = Mock()
        log.routing_decision = {}
        db = MagicMock()
        db.session.query.return_value.filter.return_value.first.return_value = log
        logger.db = db

        appended = logger.log_events(
            [
                {"event_type": "routing_started", "routing_log_id": None, "detail": {}},
                {
                    "event_type": "task_classified",
                    "routing_log_id": uuid4(),
                    "detail": {},
                },
            ]
        )

        assert len(appended) == 1
        assert appended[0]["event_type"] == "task_classified"
