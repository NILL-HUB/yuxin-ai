from contextlib import contextmanager
from types import SimpleNamespace
from uuid import uuid4

import pytest

from internal.model.routing_quality import RoutingQualityFeedbackModel
from internal.service.routing_quality_feedback_service import (
    RoutingQualityFeedbackService,
)


class _QueryStub:
    def __init__(self, *, first_result=None, all_result=None):
        self._first_result = first_result
        self._all_result = [] if all_result is None else all_result

    def filter(self, *_args, **_kwargs):
        return self

    def order_by(self, *_args, **_kwargs):
        return self

    def limit(self, *_args, **_kwargs):
        return self

    def offset(self, *_args, **_kwargs):
        return self

    def first(self):
        return self._first_result

    def all(self):
        return self._all_result


class _SessionStub:
    def __init__(self, queries=None):
        self._queries = list(queries or [])

    def query(self, *_args, **_kwargs):
        if self._queries:
            return self._queries.pop(0)
        return _QueryStub()


@contextmanager
def _auto_commit():
    yield


def _fake_db(session):
    return SimpleNamespace(session=session, auto_commit=lambda: _auto_commit())


def _feedback(**kwargs):
    defaults = {
        "id": uuid4(),
        "routing_log_id": uuid4(),
        "source": "admin",
        "rating": 4,
        "dimension_scores": {"accuracy": 5},
        "comment": "useful",
        "meta": {"ticket_id": "T-1"},
        "created_by": uuid4(),
        "created_at": None,
    }
    defaults.update(kwargs)
    return SimpleNamespace(**defaults)


def test_create_feedback_should_validate_rating():
    service = RoutingQualityFeedbackService(db=_fake_db(_SessionStub()))

    with pytest.raises(ValueError):
        service.create_feedback(
            routing_log_id=uuid4(),
            source="admin",
            rating=6,
            dimension_scores={},
            comment="bad rating",
            metadata={},
            created_by=uuid4(),
        )


def test_create_feedback_should_reject_missing_routing_log():
    service = RoutingQualityFeedbackService(
        db=_fake_db(_SessionStub([_QueryStub()]))
    )

    with pytest.raises(ValueError):
        service.create_feedback(
            routing_log_id=uuid4(),
            source="admin",
            rating=4,
            dimension_scores={},
            comment="missing log",
            metadata={},
            created_by=uuid4(),
        )


def test_create_feedback_should_create_and_serialize(monkeypatch):
    routing_log_id = uuid4()
    created_by = uuid4()
    service = RoutingQualityFeedbackService(
        db=_fake_db(_SessionStub([_QueryStub(first_result=SimpleNamespace())]))
    )
    captured = {}

    def _create(model, **kwargs):
        captured.update({"model": model, **kwargs})
        return _feedback(**kwargs)

    monkeypatch.setattr(service, "create", _create)

    result = service.create_feedback(
        routing_log_id=routing_log_id,
        source="admin",
        rating=4,
        dimension_scores={"accuracy": 5},
        comment="useful",
        metadata={"ticket_id": "T-1"},
        created_by=created_by,
    )

    assert captured["model"] is RoutingQualityFeedbackModel
    assert result["routing_log_id"] == str(routing_log_id)
    assert result["metadata"] == {"ticket_id": "T-1"}


def test_list_feedback_should_filter_and_paginate():
    feedback = _feedback()
    service = RoutingQualityFeedbackService(
        db=_fake_db(_SessionStub([_QueryStub(all_result=[feedback])]))
    )

    result = service.list_feedback(
        routing_log_id=feedback.routing_log_id,
        source="admin",
        page=1,
        page_size=20,
    )

    assert result[0]["id"] == str(feedback.id)
    assert "key_usage" not in result[0]
    assert "internal_cost_breakdown" not in result[0]
