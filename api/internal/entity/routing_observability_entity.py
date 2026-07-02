from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum

from .base_entity import SerializableMixin


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
class RoutingLogRetentionPolicy(SerializableMixin):
    retention_days: int = 30


@dataclass
class RoutingLogRedactionPolicy(SerializableMixin):
    redaction_enabled: bool = False
    sensitive_fields: list[str] = field(
        default_factory=lambda: list(DEFAULT_SENSITIVE_FIELDS)
    )


@dataclass
class RoutingLogSearchFilters(SerializableMixin):
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


@dataclass
class RoutingLogMetricsSummary(SerializableMixin):
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
