from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum


DEFAULT_SENSITIVE_FIELDS = [
    "prompt",
    "raw_prompt",
    "api_key",
    "secret",
    "token",
    "headers",
    "arguments",
]


class RoutingEventType(str, Enum):
    ROUTING_STARTED = "routing_started"
    TASK_CLASSIFIED = "task_classified"
    MODEL_SELECTED = "model_selected"
    AGENT_CANDIDATES_FOUND = "agent_candidates_found"
    AGENT_SELECTED = "agent_selected"
    TOOL_CANDIDATES_FOUND = "tool_candidates_found"
    TOOL_SELECTED = "tool_selected"
    TOOL_INVOKED = "tool_invoked"
    AGENT_COMPLETED = "agent_completed"
    SYNTHESIS_STARTED = "synthesis_started"
    SYNTHESIS_COMPLETED = "synthesis_completed"
    FALLBACK_TRIGGERED = "fallback_triggered"
    ROUTING_FAILED = "routing_failed"


ROUTING_EVENT_TYPES = {item.value for item in RoutingEventType}


@dataclass
class RoutingLogRetentionPolicy:
    retention_days: int = 30

    def to_dict(self) -> dict:
        return {"retention_days": self.retention_days}


@dataclass
class RoutingLogRedactionPolicy:
    redaction_enabled: bool = False
    sensitive_fields: list[str] = field(
        default_factory=lambda: list(DEFAULT_SENSITIVE_FIELDS)
    )

    def to_dict(self) -> dict:
        return {
            "redaction_enabled": self.redaction_enabled,
            "sensitive_fields": self.sensitive_fields,
        }


@dataclass
class RoutingLogSearchFilters:
    account_id: str | None = None
    status: str | None = None
    agent_id: str | None = None
    agent_pool: str | None = None
    tool_name: str | None = None
    tool_pool: str | None = None
    model_id: str | None = None
    key_id: str | None = None
    start_at: datetime | None = None
    end_at: datetime | None = None

    def to_dict(self) -> dict:
        return {
            "account_id": self.account_id,
            "status": self.status,
            "agent_id": self.agent_id,
            "agent_pool": self.agent_pool,
            "tool_name": self.tool_name,
            "tool_pool": self.tool_pool,
            "model_id": self.model_id,
            "key_id": self.key_id,
            "start_at": self.start_at.isoformat() if self.start_at else None,
            "end_at": self.end_at.isoformat() if self.end_at else None,
        }


@dataclass
class RoutingLogMetricsSummary:
    total_count: int = 0
    success_count: int = 0
    failure_count: int = 0
    fallback_count: int = 0
    total_credits: float = 0
    avg_latency_ms: float = 0
    agent_pool_hit_rate: float = 0
    tool_pool_hit_rate: float = 0
    agent_hit_rate: float = 0
    tool_success_rate: float = 0

    def to_dict(self) -> dict:
        return {
            "total_count": self.total_count,
            "success_count": self.success_count,
            "failure_count": self.failure_count,
            "fallback_count": self.fallback_count,
            "total_credits": self.total_credits,
            "avg_latency_ms": self.avg_latency_ms,
            "agent_pool_hit_rate": self.agent_pool_hit_rate,
            "tool_pool_hit_rate": self.tool_pool_hit_rate,
            "agent_hit_rate": self.agent_hit_rate,
            "tool_success_rate": self.tool_success_rate,
        }
