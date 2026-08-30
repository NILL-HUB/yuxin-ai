from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import uuid4

from internal.model.billing import BillingReconciliation, BillingUsageEvent
from internal.service.billing_reconciliation_service import BillingReconciliationService

ACCOUNT_ID = uuid4()


class _QueryStub:
    def __init__(self, *, one_or_none_result=None, all_result=None, first_result=None):
        self._one_or_none_result = one_or_none_result
        self._all_result = all_result
        self._first_result = first_result
        self.filters = []

    def filter(self, *args, **kwargs):
        self.filters.append((args, kwargs))
        return self

    def order_by(self, *args, **kwargs):
        return self

    def with_for_update(self):
        return self

    def one_or_none(self):
        return self._one_or_none_result

    def first(self):
        return self._first_result

    def all(self):
        return self._all_result or []


class _SessionStub:
    def __init__(self, queries=None):
        self._queries = list(queries or [])
        self.added = []

    def query(self, *_args, **_kwargs):
        if self._queries:
            return self._queries.pop(0)
        return _QueryStub()

    def add(self, value):
        self.added.append(value)


def _plan(**kw):
    defaults = {
        "sell_credits": 0,
        "cost_credits": 0,
        "margin_credits": 0,
        "billing_basis": "model_price",
        "cost_input_per_1k": 0.0,
        "cost_output_per_1k": 0.0,
    }
    defaults.update(kw)
    return SimpleNamespace(**defaults)


def _engine(*plans):
    queue = list(plans)

    def plan_usage(model_id, *, input_tokens, output_tokens, cached_input_tokens=0, moment=None):
        if queue:
            return queue.pop(0)
        return _plan(sell_credits=10)

    return SimpleNamespace(plan_usage=plan_usage)


def _credit_stub():
    calls = []

    def adjust_credits(account_id, *, diff_credits, source, source_id, description=""):
        calls.append({
            "account_id": account_id,
            "diff_credits": diff_credits,
            "source": source,
            "source_id": source_id,
            "description": description,
        })
        return {"amount": -diff_credits, "reconciliation": True, "idempotent": False}

    return SimpleNamespace(adjust_credits=adjust_credits), calls


def test_persist_event_adds_usage_event():
    session = _SessionStub()
    svc = BillingReconciliationService(session=session)

    event = svc.persist_event(
        task_id="task-1", model_id="m1", source_type="direct_answer",
        input_tokens=1500, output_tokens=500,
        billing_basis="provider_usage", estimated_credits=8,
    )

    assert isinstance(event, BillingUsageEvent)
    assert event.task_id == "task-1"
    assert event.model_id == "m1"
    assert event.source_type == "direct_answer"
    assert event.input_tokens == 1500
    assert event.output_tokens == 500
    assert event.billing_basis == "provider_usage"
    assert event.estimated_credits == 8
    assert event.is_estimated is False
    assert session.added == [event]


def test_persist_event_clamps_negatives_and_applies_defaults():
    session = _SessionStub()
    svc = BillingReconciliationService(session=session)

    event = svc.persist_event(
        task_id="task-2", model_id=None, source_type="direct_answer",
        input_tokens=-10, output_tokens=0,
        billing_basis="", estimated_credits=-2, is_estimated=True,
    )

    assert event.model_id is None
    assert event.input_tokens == 0
    assert event.output_tokens == 0
    assert event.billing_basis == "provider_usage"
    assert event.estimated_credits == 0
    assert event.is_estimated is True


def test_settle_recomputes_applies_diff_and_ratio_deviation_alert():
    session = _SessionStub([_QueryStub(one_or_none_result=None)])
    credit_stub, calls = _credit_stub()
    svc = BillingReconciliationService(
        session=session,
        pricing_engine=_engine(_plan(sell_credits=45, cost_credits=0)),
        credit_service=credit_stub,
        alert_ratio=0.30,
        alert_min_abs=10,
        cost_cover_ratio=1.0,
    )

    result = svc.settle(
        task_id="task-1",
        account_id=ACCOUNT_ID,
        events=[
            {"model_id": "m1", "input_tokens": 1000, "output_tokens": 0,
             "estimated_credits": 30, "billing_basis": "provider_usage"},
        ],
    )

    assert result["idempotent"] is False
    assert result["estimated_credits"] == 30
    assert result["actual_credits"] == 45
    assert result["cost_credits"] == 0
    assert result["diff_credits"] == 15
    assert "ratio_deviation" in result["alert_flags"]
    assert calls == [{
        "account_id": ACCOUNT_ID,
        "diff_credits": 15,
        "source": "reconciliation",
        "source_id": "task-1",
        "description": "对账多退少补 task=task-1",
    }]
    assert len(session.added) == 1
    row = session.added[0]
    assert isinstance(row, BillingReconciliation)
    assert row.task_id == "task-1"
    assert row.account_id == ACCOUNT_ID
    assert row.estimated_credits == 30
    assert row.actual_credits == 45
    assert row.diff_credits == 15
    assert row.status == "settled"
    assert row.alert_flags == ["ratio_deviation"]


def test_settle_negative_margin_alert_and_cost_amount():
    session = _SessionStub([_QueryStub(one_or_none_result=None)])
    credit_stub, calls = _credit_stub()
    svc = BillingReconciliationService(
        session=session,
        pricing_engine=_engine(
            _plan(sell_credits=2, cost_credits=5, cost_input_per_1k=2.0, cost_output_per_1k=2.0)
        ),
        credit_service=credit_stub,
        alert_ratio=0.30,
        alert_min_abs=10,
        cost_cover_ratio=1.0,
    )

    result = svc.settle(
        task_id="task-2",
        account_id=ACCOUNT_ID,
        events=[
            {"model_id": "m1", "input_tokens": 1000, "output_tokens": 500,
             "estimated_credits": 5, "billing_basis": "provider_usage"},
        ],
    )

    assert "negative_margin" in result["alert_flags"]
    assert "ratio_deviation" not in result["alert_flags"]
    assert result["actual_credits"] == 2
    assert result["cost_credits"] == 5
    assert result["diff_credits"] == -3
    assert calls == [{
        "account_id": ACCOUNT_ID,
        "diff_credits": -3,
        "source": "reconciliation",
        "source_id": "task-2",
        "description": "对账多退少补 task=task-2",
    }]
    row = session.added[0]
    assert isinstance(row, BillingReconciliation)
    assert float(row.cost_amount) == 3.0


def test_settle_is_idempotent_when_reconciliation_exists():
    existing = BillingReconciliation(
        task_id="task-1", account_id=ACCOUNT_ID,
        estimated_credits=30, actual_credits=45, diff_credits=15,
        cost_credits=0, status="settled", alert_flags=["ratio_deviation"],
    )
    session = _SessionStub([_QueryStub(one_or_none_result=existing)])
    svc = BillingReconciliationService(session=session)

    result = svc.settle(
        task_id="task-1",
        account_id=ACCOUNT_ID,
        events=[{"model_id": "m1", "input_tokens": 1000, "output_tokens": 0,
                 "estimated_credits": 30, "billing_basis": "provider_usage"}],
    )

    assert result["idempotent"] is True
    assert result["status"] == "settled"
    assert result["alert_flags"] == ["ratio_deviation"]
    assert session.added == []


def test_settle_skips_when_no_events():
    session = _SessionStub([_QueryStub(one_or_none_result=None)])
    svc = BillingReconciliationService(session=session)

    result = svc.settle(task_id="task-3", account_id=ACCOUNT_ID, events=[])

    assert result["task_id"] == "task-3"
    assert result.get("skipped") is True
    assert session.added == []


def test_persist_event_stores_cache_tier_and_moment():
    session = _SessionStub()
    svc = BillingReconciliationService(session=session)
    moment = datetime(2026, 8, 30, 10, 0, tzinfo=UTC)

    event = svc.persist_event(
        task_id="task-cache", model_id="m1", source_type="direct_answer",
        input_tokens=300, cached_input_tokens=700, output_tokens=200,
        billing_basis="provider_usage", estimated_credits=9,
        price_tier="peak", moment=moment,
    )

    assert isinstance(event, BillingUsageEvent)
    assert event.cached_input_tokens == 700
    assert event.price_tier == "peak"
    assert event.moment == moment
    assert event.input_tokens == 300
    assert session.added == [event]


def test_settle_recomputes_with_cache_split_and_moment():
    calls = []

    def plan_usage(model_id, *, input_tokens, output_tokens, cached_input_tokens=0, moment=None):
        calls.append({
            "model_id": model_id,
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "cached_input_tokens": cached_input_tokens,
            "moment": moment,
        })
        return _plan(sell_credits=10, cost_credits=0)

    session = _SessionStub([_QueryStub(one_or_none_result=None)])
    credit_stub, _ = _credit_stub()
    svc = BillingReconciliationService(
        session=session,
        pricing_engine=SimpleNamespace(plan_usage=plan_usage),
        credit_service=credit_stub,
    )
    moment = datetime(2026, 8, 30, 10, 0, tzinfo=UTC)

    svc.settle(
        task_id="task-split",
        account_id=ACCOUNT_ID,
        events=[
            {"model_id": "m1", "input_tokens": 300, "cached_input_tokens": 700,
             "output_tokens": 200, "estimated_credits": 5,
             "billing_basis": "provider_usage", "moment": moment},
            {"model_id": "m2", "input_tokens": 100, "output_tokens": 0,
             "estimated_credits": 1, "billing_basis": "provider_usage"},
        ],
    )

    assert len(calls) == 2
    assert calls[0] == {
        "model_id": "m1",
        "input_tokens": 300,
        "output_tokens": 200,
        "cached_input_tokens": 700,
        "moment": moment,
    }
    # 事件无 moment → None，走引擎默认即时判定
    assert calls[1] == {
        "model_id": "m2",
        "input_tokens": 100,
        "output_tokens": 0,
        "cached_input_tokens": 0,
        "moment": None,
    }


def test_margin_summary_groups_by_tier_and_cache_total():
    events = [
        BillingUsageEvent(
            task_id="t1", model_id="m1", source_type="direct_answer",
            input_tokens=300, cached_input_tokens=700, output_tokens=200,
            billing_basis="provider_usage", estimated_credits=9, cost_credits=4,
            price_tier="peak",
        ),
        BillingUsageEvent(
            task_id="t2", model_id="m2", source_type="direct_answer",
            input_tokens=100, cached_input_tokens=40, output_tokens=50,
            billing_basis="provider_usage", estimated_credits=5, cost_credits=2,
            price_tier="",
        ),
    ]
    session = _SessionStub([_QueryStub(all_result=events)])
    svc = BillingReconciliationService(session=session)

    result = svc.margin_summary()

    assert [b["tier"] for b in result["by_tier"]] == ["peak", "常规"]
    peak = result["by_tier"][0]
    assert peak["calls"] == 1
    assert peak["actual_credits"] == 9
    assert peak["cost_credits"] == 4
    assert peak["margin_credits"] == 5
    regular = result["by_tier"][1]
    assert regular["tier"] == "常规"
    assert regular["calls"] == 1
    assert regular["actual_credits"] == 5
    assert regular["cost_credits"] == 2
    assert regular["margin_credits"] == 3
    assert result["overall"] == {
        "actual_credits": 14,
        "cost_credits": 6,
        "margin_credits": 8,
    }
    assert result["cached_input_tokens_total"] == 740


def test_margin_summary_returns_empty_buckets_without_events():
    session = _SessionStub([_QueryStub(all_result=[])])
    svc = BillingReconciliationService(session=session)

    result = svc.margin_summary()

    assert result["by_tier"] == []
    assert result["overall"] == {"actual_credits": 0, "cost_credits": 0, "margin_credits": 0}
    assert result["cached_input_tokens_total"] == 0