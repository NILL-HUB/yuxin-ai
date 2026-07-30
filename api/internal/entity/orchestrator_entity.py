from dataclasses import dataclass, field
from enum import Enum

from internal.entity.base_entity import SerializableMixin


class ExecutionMode(str, Enum):
    DIRECT_ANSWER = "direct_answer"
    SINGLE_AGENT = "single_agent"
    SINGLE_AGENT_WITH_TOOLS = "single_agent_with_tools"
    MULTI_AGENT = "multi_agent"
    MULTI_AGENT_PARALLEL = "multi_agent_parallel"
    MULTI_AGENT_SEQUENTIAL = "multi_agent_sequential"
    DEEP_THINKING = "deep_thinking"
    REJECT_OR_CONFIRM = "reject_or_confirm"


_MULTI_AGENT_MODES = {
    ExecutionMode.MULTI_AGENT.value,
    ExecutionMode.MULTI_AGENT_PARALLEL.value,
    ExecutionMode.MULTI_AGENT_SEQUENTIAL.value,
}


class RiskLevel(str, Enum):
    SAFE = "safe"
    MEDIUM = "medium"
    HIGH = "high"
    UNKNOWN = "unknown"


@dataclass
class RoutingDecision(SerializableMixin):
    intent: str
    complexity: str
    execution_mode: str
    needs_tools: bool = False
    needs_agent: bool = False
    needs_multi_agent: bool = False
    needs_deep_thinking: bool = False
    recommended_model_tier: str = "1"
    risk_level: str = RiskLevel.SAFE.value
    reason: str = ""
    agent_subset: dict | None = None
    tool_subset: dict | None = None
    cost_policy: dict | None = None
    billing_events: list[dict] = None
    task_plan_summary: dict | None = None
    synthesis_summary: dict | None = None

    def __post_init__(self):
        if self.billing_events is None:
            self.billing_events = []
        if self.execution_mode in _MULTI_AGENT_MODES:
            self.needs_multi_agent = True
        if self.execution_mode == ExecutionMode.DEEP_THINKING.value:
            self.needs_deep_thinking = True
        if self.execution_mode == ExecutionMode.SINGLE_AGENT_WITH_TOOLS.value:
            self.needs_tools = True
            self.needs_agent = True


@dataclass
class RequestContext:
    query: str
    account_id: str = ""
    conversation_id: str = ""
    message_id: str = ""
    image_urls: list[str] = field(default_factory=list)
    enable_deep_thinking: bool = False
    deep_thinking_requested: bool = False
    budget_level: str = "normal"
    balance_credits: float = 1.0
    budget_allowed: bool = True
    routing_log_id: str | None = None

    def to_safe_dict(self) -> dict:
        return {
            "query": self.query,
            "account_id": self.account_id,
            "conversation_id": self.conversation_id,
            "message_id": self.message_id,
            "image_url_count": len(self.image_urls),
            "enable_deep_thinking": self.enable_deep_thinking,
            "deep_thinking_requested": self.deep_thinking_requested,
            "budget_level": self.budget_level,
            "balance_credits": self.balance_credits,
            "budget_allowed": self.budget_allowed,
            "routing_log_id": self.routing_log_id,
        }
