from contextlib import contextmanager
from types import SimpleNamespace
from uuid import uuid4

from internal.model import RoutingLog
from internal.service.routing_log_service import RoutingLogService


class _QueryStub:
    def __init__(self, *, all_result=None, count_result=0):
        self._all_result = [] if all_result is None else all_result
        self._count_result = count_result

    def filter(self, *_args, **_kwargs):
        return self

    def order_by(self, *_args, **_kwargs):
        return self

    def offset(self, *_args, **_kwargs):
        return self

    def limit(self, *_args, **_kwargs):
        return self

    def count(self):
        return self._count_result

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


def test_record_should_persist_routing_decision_candidates_filters_and_billing(monkeypatch):
    service = RoutingLogService(db=_fake_db(_SessionStub()))
    created = []
    monkeypatch.setattr(service, "create", lambda model, **kwargs: created.append((model, kwargs)) or SimpleNamespace(**kwargs))

    result = service.record(
        account_id=uuid4(),
        message_id=uuid4(),
        routing_decision={"intent": "tool_task"},
        agent_candidates=[{"name": "Agent"}],
        filtered_out_agents=[{"name": "Draft", "reason": "app_not_published"}],
        tool_candidates=[{"name": "search"}],
        filtered_out_tools=[{"name": "delete", "reason": "high_risk_requires_confirmation"}],
        knowledge_hits=[{"name": "系统知识"}],
        billing_events=[{"event": "billing_delta", "total_credits": 3}],
        status="success",
    )

    assert created[0][0] is RoutingLog
    assert result.routing_decision == {"intent": "tool_task"}
    assert result.filtered_out_tools[0]["reason"] == "high_risk_requires_confirmation"


def test_page_should_return_serialized_logs_with_filters():
    log = SimpleNamespace(
        id=uuid4(),
        account_id=uuid4(),
        message_id=uuid4(),
        routing_decision={"intent": "general_qa"},
        agent_candidates=[],
        filtered_out_agents=[],
        tool_candidates=[],
        filtered_out_tools=[],
        knowledge_hits=[],
        billing_events=[],
        status="success",
        created_at=None,
    )
    service = RoutingLogService(
        db=_fake_db(
            _SessionStub([
                _QueryStub(count_result=1),
                _QueryStub(all_result=[log]),
            ])
        )
    )

    result = service.page(page=1, page_size=20, status="success")

    assert result["paginator"]["total_record"] == 1
    assert result["list"][0]["routing_decision"]["intent"] == "general_qa"
