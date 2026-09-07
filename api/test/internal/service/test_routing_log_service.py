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
        user_query="帮我分析市场",
        task_classification={"complexity": "complex"},
        model_selection={"model_id": "deepseek-chat"},
        agent_pool_hits=[{"pool": "research"}],
        tool_pool_hits=[{"pool": "web"}],
        key_usage={"key_id": "key-1"},
        cost_summary={"total_credits": 3},
        latency_ms=1200,
        fallback_reason="",
        redaction_enabled=True,
    )

    assert created[0][0] is RoutingLog
    assert result.routing_decision == {"intent": "tool_task"}
    assert result.filtered_out_tools[0]["reason"] == "high_risk_requires_confirmation"
    assert result.user_query == "帮我分析市场"
    assert result.task_classification == {"complexity": "complex"}
    assert result.model_selection == {"model_id": "deepseek-chat"}
    assert result.agent_pool_hits == [{"pool": "research"}]
    assert result.tool_pool_hits == [{"pool": "web"}]
    assert result.key_usage == {"key_id": "key-1"}
    assert result.cost_summary == {"total_credits": 3}
    assert result.latency_ms == 1200
    assert result.redaction_enabled is True


def test_create_pending_should_carry_message_id(monkeypatch):
    service = RoutingLogService(db=_fake_db(_SessionStub()))
    created = []
    monkeypatch.setattr(
        service,
        "create",
        lambda model, **kwargs: created.append((model, kwargs))
        or SimpleNamespace(id=uuid4(), **kwargs),
    )

    message_id = uuid4()
    service.create_pending(
        account_id=uuid4(),
        user_query="帮我查询资料",
        invoke_from="web",
        message_id=message_id,
    )

    assert created[0][0] is RoutingLog
    assert created[0][1]["message_id"] == message_id


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
        invoke_from="web",
        user_query="帮我分析市场",
        task_classification={"complexity": "complex"},
        model_selection={"model_id": "deepseek-chat"},
        agent_pool_hits=[{"pool": "research"}],
        tool_pool_hits=[{"pool": "web"}],
        key_usage={"key_id": "key-1"},
        cost_summary={"total_credits": 3},
        latency_ms=1200,
        fallback_reason="quota_exhausted",
        redaction_enabled=True,
        retention_expires_at=None,
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

    result = service.page(
        page=1,
        page_size=20,
        status="success",
        agent_pool="research",
        tool_pool="web",
        model_id="deepseek-chat",
        key_id="key-1",
    )

    assert result["paginator"]["total_record"] == 1
    assert result["list"][0]["routing_decision"]["intent"] == "general_qa"
    assert result["list"][0]["user_query"] == "帮我分析市场"
    assert result["list"][0]["invoke_from"] == "web"
    assert result["list"][0]["task_classification"] == {"complexity": "complex"}
    assert result["list"][0]["model_selection"] == {"model_id": "deepseek-chat"}
    assert result["list"][0]["agent_pool_hits"] == [{"pool": "research"}]
    assert result["list"][0]["tool_pool_hits"] == [{"pool": "web"}]
    assert result["list"][0]["key_usage"] == {"key_id": "key-1"}
    assert result["list"][0]["cost_summary"] == {"total_credits": 3}
    assert result["list"][0]["latency_ms"] == 1200
    assert result["list"][0]["fallback_reason"] == "quota_exhausted"
    assert result["list"][0]["redaction_enabled"] is True


class _ChainQueryStub:
    """支持 filter/group_by/order_by/limit/offset/select_from 链式的查询 stub。"""

    def __init__(self, *, first_result=None, all_result=None, scalar_result=None, count_result=None):
        self._first_result = first_result
        self._all_result = all_result
        self._scalar_result = scalar_result
        self._count_result = count_result

    def filter(self, *_args, **_kwargs):
        return self

    def with_entities(self, *_args, **_kwargs):
        return self

    def group_by(self, *_args, **_kwargs):
        return self

    def order_by(self, *_args, **_kwargs):
        return self

    def offset(self, *_args, **_kwargs):
        return self

    def limit(self, *_args, **_kwargs):
        return self

    def select_from(self, *_args, **_kwargs):
        return self

    def first(self):
        return self._first_result

    def all(self):
        return self._all_result if self._all_result is not None else []

    def scalar(self):
        return self._scalar_result

    def count(self):
        return self._count_result if self._count_result is not None else 0


def _row(**kwargs):
    return SimpleNamespace(**kwargs)


def test_normalize_window_accepts_timestamps_strings_and_datetimes():
    from datetime import UTC, datetime

    service = RoutingLogService(db=None)

    start_dt, end_dt = service._normalize_window(0, "")
    assert start_dt is None
    assert end_dt is None

    start_dt, end_dt = service._normalize_window("1700000000", "bad-value")
    assert end_dt is None
    assert start_dt is not None
    assert start_dt.tzinfo is None
    assert int(start_dt.replace(tzinfo=UTC).timestamp()) == 1700000000

    raw = datetime(2026, 5, 1, tzinfo=UTC)
    start_dt, end_dt = service._normalize_window(raw, None)
    assert start_dt == raw.astimezone(UTC).replace(tzinfo=None)
    assert end_dt is None


def test_normalize_dimension_value_folds_empty_to_unknown():
    service = RoutingLogService(db=None)
    assert service._normalize_dimension_value("") == "unknown"
    assert service._normalize_dimension_value(None) == "unknown"
    assert service._normalize_dimension_value("  ") == "unknown"
    assert service._normalize_dimension_value("success") == "success"


def test_stats_overview_assembles_aggregates_and_status_breakdown():
    session = SimpleNamespace(
        query=lambda *_a, **_k: _ChainQueryStub(first_result=_row(
            total_count=10,
            success_count=8,
            fallback_count=1,
            total_credits=120,
            avg_latency_ms=300.0,
            agent_pool_hit_rate=0.5,
            tool_pool_hit_rate=0.4,
        ))
    )
    # 第二个 query（status_rows）来自 status query .group_by().all()
    calls = []

    def fake_query(*_a, **_k):
        calls.append(len(calls))
        if len(calls) == 1:
            return _ChainQueryStub(first_result=_row(
                total_count=10,
                success_count=8,
                fallback_count=1,
                total_credits=120,
                avg_latency_ms=300.0,
                agent_pool_hit_rate=0.5,
                tool_pool_hit_rate=0.4,
            ))
        return _ChainQueryStub(all_result=[
            _row(status="success", count=8, credits=100),
            _row(status="fallback", count=1, credits=20),
        ])

    service = RoutingLogService(db=SimpleNamespace(session=SimpleNamespace(query=fake_query)))

    result = service.stats_overview(start_at=None, end_at=None)
    assert result["total_count"] == 10
    assert result["success_count"] == 8
    assert result["fallback_count"] == 1
    assert result["success_rate"] == 0.8
    assert result["fallback_rate"] == 0.1
    assert result["total_credits"] == 120
    assert result["by_status"]["success"]["count"] == 8
    assert result["by_status"]["success"]["credits"] == 100
    assert "unknown" not in result["by_status"]


def test_distribution_assembles_items_with_percentage():
    def fake_query(*_a, **_k):
        calls.append(len(calls))
        if len(calls) == 1:
            return _ChainQueryStub(all_result=[
                _row(name="deep_thinking", count=6, credits=60, avg_latency_ms=800.0),
                _row(name="single_agent", count=3, credits=9, avg_latency_ms=100.0),
            ])
        return _ChainQueryStub(first_result=_row(total=10))

    calls = []
    service = RoutingLogService(db=SimpleNamespace(session=SimpleNamespace(query=fake_query)))

    result = service.distribution(dimension="execution_mode", start_at=None, end_at=None)
    assert result["dimension"] == "execution_mode"
    assert result["total_count"] == 10
    assert len(result["items"]) == 2
    assert result["items"][0]["name"] == "deep_thinking"
    assert result["items"][0]["count"] == 6
    assert result["items"][0]["percentage"] == 60.0
    assert result["items"][1]["percentage"] == 30.0


def test_trend_returns_points_with_utc_timestamps():
    from datetime import datetime, UTC

    ts = datetime(2026, 6, 1, tzinfo=UTC).replace(tzinfo=None)
    service = RoutingLogService(db=SimpleNamespace(session=SimpleNamespace(
        query=lambda *_a, **_k: _ChainQueryStub(all_result=[
            _row(ts=ts, request_count=5, success_count=4, fallback_count=1,
                 total_credits=40, avg_latency_ms=250.0),
        ])
    )))

    result = service.trend(granularity="day", start_at=None, end_at=None)
    assert result["granularity"] == "day"
    assert len(result["points"]) == 1
    point = result["points"][0]
    assert point["request_count"] == 5
    assert point["success_count"] == 4
    assert point["fallback_count"] == 1
    assert point["total_credits"] == 40
    assert point["avg_latency_ms"] == 250.0
    assert point["timestamp"] == int(ts.replace(tzinfo=UTC).timestamp())
