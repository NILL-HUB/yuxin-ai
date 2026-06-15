from uuid import uuid4

from internal.entity.billing_metering_entity import BillingEventType, BillingUsageDelta
from internal.service.billing_metering_service import (
    BillingMetering,
    BillingUsageAggregator,
)


def test_usage_delta_should_dump_sse_payload():
    delta = BillingUsageDelta(
        event_type=BillingEventType.DELTA.value,
        task_id=str(uuid4()),
        source_type="model",
        source_name="deepseek-chat",
        delta_credits=3,
        total_credits=8,
        reason="answer_tokens",
    )

    assert delta.to_sse() == {
        "event": "billing_delta",
        "source_type": "model",
        "source_name": "deepseek-chat",
        "delta_credits": 3,
        "total_credits": 8,
        "reason": "answer_tokens",
    }


def test_aggregator_should_emit_started_delta_summary_and_final():
    task_id = str(uuid4())
    aggregator = BillingUsageAggregator(task_id=task_id)

    started = aggregator.started()
    first_delta = aggregator.delta("model", "deepseek-chat", 3, reason="tokens")
    second_delta = aggregator.delta("tool", "search", 2, reason="tool_call")
    summary = aggregator.summary()
    final = aggregator.final()

    assert started.event_type == BillingEventType.STARTED.value
    assert first_delta.total_credits == 3
    assert second_delta.total_credits == 5
    assert summary.to_sse()["total_credits"] == 5
    assert final.to_sse()["event"] == BillingEventType.FINAL.value


def test_aggregator_should_emit_cancelled_with_current_cost_only():
    task_id = str(uuid4())
    aggregator = BillingUsageAggregator(task_id=task_id)
    aggregator.delta("model", "deepseek-chat", 4, reason="tokens")

    cancelled = aggregator.cancelled(reason="user_stop")

    assert cancelled.to_sse() == {
        "event": "billing_cancelled",
        "source_type": "summary",
        "source_name": "billing",
        "delta_credits": 0,
        "total_credits": 4,
        "reason": "user_stop",
    }


def test_metering_should_record_events_and_keep_current_total():
    task_id = str(uuid4())
    metering = BillingMetering(task_id=task_id)

    metering.started()
    metering.delta("model", "deepseek-chat", 2, reason="tokens")
    metering.delta("tool", "search", 5, reason="tool_call")

    assert metering.total_credits == 7
    assert [event.event_type for event in metering.events] == [
        BillingEventType.STARTED.value,
        BillingEventType.DELTA.value,
        BillingEventType.DELTA.value,
    ]
