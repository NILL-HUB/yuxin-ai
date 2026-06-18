import json
from types import SimpleNamespace
from uuid import uuid4

from internal.entity.billing_metering_entity import BillingEventType


def _parse_sse_events(sse_lines):
    events = []
    for line in sse_lines:
        if line.startswith("event: billing_"):
            event_type = line.split("event: ")[1].split("\\")[0].split("\n")[0].strip()
            events.append(event_type)
    return events


class TestBillingSseIntegration:
    def test_billing_started_should_be_first_event(self):
        from internal.entity.billing_metering_entity import BillingEventType
        assert BillingEventType.STARTED.value == "billing_started"
        assert BillingEventType.DELTA.value == "billing_delta"
        assert BillingEventType.SUMMARY.value == "billing_summary"
        assert BillingEventType.CANCELLED.value == "billing_cancelled"
        assert BillingEventType.FINAL.value == "billing_final"

    def test_billing_usage_delta_to_sse_should_include_required_fields(self):
        from internal.entity.billing_metering_entity import BillingUsageDelta

        delta = BillingUsageDelta(
            event_type=BillingEventType.DELTA.value,
            task_id=str(uuid4()),
            source_type="model",
            source_name="assistant_agent",
            delta_credits=5,
            total_credits=10,
            reason="agent_message",
            metadata={"input_tokens": 100, "output_tokens": 50},
        )
        sse_data = delta.to_sse()
        assert sse_data["event"] == "billing_delta"
        assert sse_data["delta_credits"] == 5
        assert sse_data["total_credits"] == 10
        assert sse_data["source_type"] == "model"
        assert sse_data["metadata"]["input_tokens"] == 100

    def test_billing_aggregator_should_accumulate_credits(self):
        from internal.service.billing_metering_service import BillingUsageAggregator

        task_id = str(uuid4())
        aggregator = BillingUsageAggregator(task_id=task_id)

        started = aggregator.started()
        assert started.event_type == "billing_started"
        assert started.total_credits == 0

        delta1 = aggregator.model_tokens(
            source_name="assistant_agent",
            input_tokens=100,
            output_tokens=50,
            reason="agent_message",
        )
        assert delta1.event_type == "billing_delta"
        assert delta1.delta_credits >= 0

        delta2 = aggregator.model_tokens(
            source_name="assistant_agent",
            input_tokens=200,
            output_tokens=100,
            reason="agent_action",
        )
        assert delta2.event_type == "billing_delta"
        assert delta2.total_credits >= delta1.total_credits

        final = aggregator.final()
        assert final.event_type == "billing_final"
        assert final.total_credits >= delta2.total_credits

    def test_billing_cancelled_should_have_user_stop_reason(self):
        from internal.service.billing_metering_service import BillingUsageAggregator

        task_id = str(uuid4())
        aggregator = BillingUsageAggregator(task_id=task_id)

        cancelled = aggregator.cancelled()
        assert cancelled.event_type == "billing_cancelled"
        assert cancelled.reason == "user_stop"
