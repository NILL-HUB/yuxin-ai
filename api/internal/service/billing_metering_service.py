from dataclasses import dataclass, field

from internal.entity.billing_metering_entity import BillingEventType, BillingUsageDelta


@dataclass
class BillingUsageAggregator:
    task_id: str
    total_credits: int = 0
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
    ) -> BillingUsageDelta:
        self.total_credits += delta_credits
        return self._record(
            BillingEventType.DELTA.value,
            source_type,
            source_name,
            delta_credits,
            reason,
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
    ) -> BillingUsageDelta:
        event = BillingUsageDelta(
            event_type=event_type,
            task_id=self.task_id,
            source_type=source_type,
            source_name=source_name,
            delta_credits=delta_credits,
            total_credits=self.total_credits,
            reason=reason,
        )
        self.events.append(event)
        return event


class BillingMetering(BillingUsageAggregator):
    pass
