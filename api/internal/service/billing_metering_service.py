from dataclasses import dataclass, field

from internal.entity.billing_metering_entity import BillingEventType, BillingUsageDelta


@dataclass
class BillingUsageAggregator:
    task_id: str
    total_credits: int = 0
    credits_per_1k_tokens: int = 1
    events: list[BillingUsageDelta] = field(default_factory=list)

    def started(self) -> BillingUsageDelta:
        return self._record(
            BillingEventType.STARTED.value,
            "summary",
            "billing",
            0,
            "billing_started",
        )

    def delta(
        self,
        source_type: str,
        source_name: str,
        delta_credits: int,
        *,
        reason: str = "",
        metadata: dict | None = None,
    ) -> BillingUsageDelta:
        self.total_credits += delta_credits
        return self._record(
            BillingEventType.DELTA.value,
            source_type,
            source_name,
            delta_credits,
            reason,
            metadata or {},
        )

    def model_tokens(
        self,
        source_name: str,
        *,
        input_tokens: int,
        output_tokens: int,
        reason: str,
    ) -> BillingUsageDelta:
        total_tokens = max(input_tokens, 0) + max(output_tokens, 0)
        delta_credits = int(total_tokens * self.credits_per_1k_tokens / 1000)
        return self.delta(
            "model",
            source_name,
            delta_credits,
            reason=reason,
            metadata={"input_tokens": input_tokens, "output_tokens": output_tokens},
        )

    def summary(self) -> BillingUsageDelta:
        return self._record(
            BillingEventType.SUMMARY.value,
            "summary",
            "billing",
            0,
            "billing_summary",
        )

    def cancelled(self, *, reason: str = "user_stop") -> BillingUsageDelta:
        return self._record(
            BillingEventType.CANCELLED.value,
            "summary",
            "billing",
            0,
            reason,
        )

    def final(self) -> BillingUsageDelta:
        return self._record(
            BillingEventType.FINAL.value,
            "summary",
            "billing",
            0,
            "billing_final",
        )

    def _record(
        self,
        event_type: str,
        source_type: str,
        source_name: str,
        delta_credits: int,
        reason: str,
        metadata: dict | None = None,
    ) -> BillingUsageDelta:
        event = BillingUsageDelta(
            event_type=event_type,
            task_id=self.task_id,
            source_type=source_type,
            source_name=source_name,
            delta_credits=delta_credits,
            total_credits=self.total_credits,
            reason=reason,
            metadata=metadata or {},
        )
        self.events.append(event)
        return event


class BillingMetering(BillingUsageAggregator):
    pass
