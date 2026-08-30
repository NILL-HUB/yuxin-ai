from types import SimpleNamespace
from unittest.mock import MagicMock
from uuid import uuid4

from internal.core.billing.pricing_engine import PricingEngine
from internal.entity.billing_metering_entity import BillingEventType, BillingUsageDelta
from internal.service.billing_metering_service import (
    BillingMetering,
    BillingUsageAggregator,
)


def test_usage_delta_should_dump_sse_payload_with_metadata():
    delta = BillingUsageDelta(
        event_type=BillingEventType.DELTA.value,
        task_id=str(uuid4()),
        source_type="model",
        source_name="deepseek-chat",
        delta_credits=3,
        total_credits=8,
        reason="answer_tokens",
        metadata={"input_tokens": 100, "output_tokens": 200},
    )

    assert delta.to_sse() == {
        "event": "billing_delta",
        "source_type": "model",
        "source_name": "deepseek-chat",
        "delta_credits": 3,
        "total_credits": 8,
        "reason": "answer_tokens",
        "metadata": {"input_tokens": 100, "output_tokens": 200},
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
        "total_credits": 4,
        "reason": "user_stop",
        "pending_phases": [],
    }


def test_aggregator_should_emit_cancelled_with_pending_phases():
    task_id = str(uuid4())
    aggregator = BillingUsageAggregator(task_id=task_id)
    aggregator.delta("model", "deepseek-chat", 4, reason="tokens")

    cancelled = aggregator.cancelled(
        reason="user_stop",
        pending_phases=["工具调用", "结果合成"],
    )

    assert cancelled.to_sse() == {
        "event": "billing_cancelled",
        "total_credits": 4,
        "reason": "user_stop",
        "pending_phases": ["工具调用", "结果合成"],
    }


def test_aggregator_should_convert_token_usage_to_credits():
    task_id = str(uuid4())
    aggregator = BillingUsageAggregator(task_id=task_id, credits_per_1k_tokens=2)

    event = aggregator.model_tokens(
        "deepseek-chat",
        model_id="deepseek-chat",
        input_tokens=500,
        output_tokens=1000,
        reason="model_tokens",
    )

    assert event.delta_credits == 3
    assert event.total_credits == 3
    assert event.metadata == {
        "model_id": "deepseek-chat",
        "input_tokens": 500,
        "cached_input_tokens": 0,
        "output_tokens": 1000,
    }


def test_aggregator_model_tokens_records_model_detail():
    aggregator = BillingUsageAggregator(
        task_id="task-1",
        pricing_engine=PricingEngine(
            session=None,
            configs={"credits_per_1k_tokens": 1, "credits_per_yuan": 100},
        ),
    )
    event = aggregator.model_tokens(
        "direct_answer",
        model_id="model-1",
        input_tokens=1500,
        output_tokens=500,
        reason="test",
    )
    assert event.metadata["model_id"] == "model-1"
    assert event.metadata["input_tokens"] == 1500
    assert event.metadata["output_tokens"] == 500


def test_model_tokens_passes_cache_and_moment_into_event_buf():
    from datetime import UTC, datetime

    pricing_engine = MagicMock()
    pricing_engine.plan_usage.return_value = SimpleNamespace(
        sell_credits=9, price_tier="peak"
    )
    aggregator = BillingUsageAggregator(
        task_id="task-1", pricing_engine=pricing_engine
    )
    moment = datetime(2026, 8, 31, 2, 0, tzinfo=UTC)

    event = aggregator.model_tokens(
        "direct_answer",
        model_id="m1",
        input_tokens=1000,
        cached_input_tokens=700,
        output_tokens=300,
        reason="r",
        moment=moment,
    )

    buf = aggregator.usage_event_buf[0]
    assert buf["input_tokens"] == 300
    assert buf["cached_input_tokens"] == 700
    assert buf["output_tokens"] == 300
    assert "price_tier" in buf
    assert buf["price_tier"] == "peak"
    assert buf["moment"] == moment
    assert event.delta_credits == 9
    assert event.metadata == {
        "model_id": "m1",
        "input_tokens": 300,
        "cached_input_tokens": 700,
        "output_tokens": 300,
    }
    pricing_engine.plan_usage.assert_called_once_with(
        "m1",
        input_tokens=1000,
        output_tokens=300,
        cached_input_tokens=700,
        moment=moment,
    )


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


def test_final_with_reply_service_persists_events_and_settles():
    aggregator = BillingUsageAggregator(task_id="task-1")
    aggregator.account_id = "account-1"
    aggregator.model_tokens(
        "direct_answer",
        model_id="m1",
        input_tokens=1500,
        output_tokens=500,
        reason="r",
    )

    persisted = []
    settled = []
    aggregator.final(
        reconciliation_service=SimpleNamespace(
            persist_event=lambda **kw: persisted.append(kw),
            settle=lambda **kw: settled.append(kw),
        )
    )

    assert aggregator.usage_event_buf
    assert len(persisted) == 1
    assert persisted[0]["model_id"] == "m1"
    assert persisted[0]["source_type"] == "direct_answer"
    assert persisted[0]["input_tokens"] == 1500
    assert persisted[0]["output_tokens"] == 500
    assert persisted[0]["estimated_credits"] == 2
    assert persisted[0]["billing_basis"] == "provider_usage"
    assert persisted[0]["is_estimated"] is False
    assert settled[0]["task_id"] == "task-1"
    assert settled[0]["account_id"] == "account-1"


def test_final_without_reply_service_keeps_legacy_behavior():
    aggregator = BillingUsageAggregator(task_id="task-1")
    aggregator.account_id = "account-1"
    aggregator.model_tokens(
        "direct_answer",
        model_id="m1",
        input_tokens=100,
        output_tokens=50,
        reason="r",
    )

    final = aggregator.final()

    assert final.event_type == BillingEventType.FINAL.value
    assert aggregator.usage_event_buf


def test_final_should_pass_feature_key_and_token_count_to_consume():
    credit_service = MagicMock()
    aggregator = BillingUsageAggregator(
        task_id="task-1", credit_service=credit_service, feature_key="direct_answer"
    )
    aggregator.account_id = "account-1"
    aggregator.model_tokens(
        "direct_answer",
        model_id="m1",
        input_tokens=500,
        output_tokens=500,
        reason="r",
    )
    aggregator.model_tokens(
        "direct_answer",
        model_id="m1",
        input_tokens=250,
        output_tokens=250,
        reason="r",
    )

    aggregator.final()

    assert aggregator.total_tokens == 1500
    credit_service.consume_for_feature.assert_called_once_with(
        account_id="account-1",
        feature_key="direct_answer",
        token_count=1500,
    )


def test_final_should_commit_when_real_session_present():
    session = MagicMock()
    credit_service = SimpleNamespace(session=session)
    aggregator = BillingUsageAggregator(
        task_id="task-1", credit_service=credit_service
    )
    aggregator.account_id = "account-1"
    aggregator.model_tokens(
        "direct_answer", model_id="m1", input_tokens=1000, output_tokens=0, reason="r",
    )

    aggregator.final()

    session.commit.assert_called_once()


def test_final_should_skip_commit_when_disabled():
    session = MagicMock()
    credit_service = SimpleNamespace(session=session)
    aggregator = BillingUsageAggregator(
        task_id="task-1", credit_service=credit_service, _should_commit=False
    )
    aggregator.account_id = "account-1"
    aggregator.model_tokens(
        "direct_answer", model_id="m1", input_tokens=1000, output_tokens=0, reason="r",
    )

    aggregator.final()

    session.commit.assert_not_called()


def test_final_should_not_commit_without_real_session():
    # fake reconciliation_service（无 session 属性）不应触发 commit
    aggregator = BillingUsageAggregator(task_id="task-1")
    aggregator.account_id = "account-1"
    aggregator.model_tokens(
        "direct_answer", model_id="m1", input_tokens=100, output_tokens=50, reason="r",
    )

    aggregator.final(
        reconciliation_service=SimpleNamespace(
            persist_event=lambda **kw: None,
            settle=lambda **kw: None,
        )
    )
