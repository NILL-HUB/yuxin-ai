import logging
from dataclasses import dataclass, field
from typing import Any

from internal.entity.billing_metering_entity import (
    BillingEventType,
    BillingUsageCancelled,
    BillingUsageDelta,
)

logger = logging.getLogger(__name__)


@dataclass
class BillingUsageAggregator:
    task_id: str
    total_credits: int = 0
    credits_per_1k_tokens: int = 1
    events: list[BillingUsageDelta | BillingUsageCancelled] = field(default_factory=list)
    # 可选注入：注入后 final() 会实际调用 CreditService 扣费
    credit_service: Any = None
    account_id: Any = None
    feature_key: str = "assistant_agent"
    # 累计原始 token 数，用于 final() 调用 consume_for_feature(token_count=...)
    total_tokens: int = 0

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
        # 累计 model 来源的原始 token，供 final() 实际扣费使用
        if source_type == "model" and metadata:
            self.total_tokens += int(metadata.get("input_tokens", 0) or 0) + int(
                metadata.get("output_tokens", 0) or 0
            )
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

    def cancelled(
        self,
        *,
        reason: str = "user_stop",
        pending_phases: list[str] | None = None,
    ) -> BillingUsageCancelled:
        event = BillingUsageCancelled(
            event_type=BillingEventType.CANCELLED.value,
            task_id=self.task_id,
            total_credits=self.total_credits,
            reason=reason,
            pending_phases=list(pending_phases or []),
        )
        self.events.append(event)
        return event

    def final(self) -> BillingUsageDelta:
        event = self._record(
            BillingEventType.FINAL.value,
            "summary",
            "billing",
            0,
            "billing_final",
        )
        # 实际扣费：如果注入了 credit_service 和 account_id，则调用 CreditService
        # consume_for_feature 签名为 (account_id, feature_key, *, token_count)，
        # 因此使用累计的 total_tokens 而非 total_credits
        if (
            self.credit_service is not None
            and self.account_id is not None
            and self.total_tokens > 0
        ):
            try:
                self.credit_service.consume_for_feature(
                    account_id=self.account_id,
                    feature_key=self.feature_key,
                    token_count=self.total_tokens,
                )
            except Exception:
                logger.warning(
                    "BillingUsageAggregator 扣费失败 task_id=%s", self.task_id, exc_info=True
                )
        return event

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
