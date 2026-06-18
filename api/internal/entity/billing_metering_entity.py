from dataclasses import asdict, dataclass, field
from enum import Enum


class BillingEventType(str, Enum):
    STARTED = "billing_started"
    DELTA = "billing_delta"
    SUMMARY = "billing_summary"
    CANCELLED = "billing_cancelled"
    FINAL = "billing_final"


@dataclass
class BillingUsageDelta:
    event_type: str
    task_id: str
    source_type: str
    source_name: str
    delta_credits: int
    total_credits: int
    reason: str = ""
    metadata: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return asdict(self)

    def to_sse(self) -> dict:
        return {
            "event": self.event_type,
            "source_type": self.source_type,
            "source_name": self.source_name,
            "delta_credits": self.delta_credits,
            "total_credits": self.total_credits,
            "reason": self.reason,
            "metadata": self.metadata,
        }


@dataclass
class BillingUsageCancelled:
    event_type: str
    task_id: str
    total_credits: int
    reason: str = "user_stop"
    pending_phases: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)

    def to_sse(self) -> dict:
        return {
            "event": self.event_type,
            "total_credits": self.total_credits,
            "reason": self.reason,
            "pending_phases": self.pending_phases,
        }
