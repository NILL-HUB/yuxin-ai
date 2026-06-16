from dataclasses import asdict, dataclass
from enum import Enum


class ExecutionMode(str, Enum):
    DIRECT_ANSWER = "direct_answer"
    SINGLE_AGENT = "single_agent"
    MULTI_AGENT = "multi_agent"
    REJECT_OR_CONFIRM = "reject_or_confirm"


class RiskLevel(str, Enum):
    SAFE = "safe"
    MEDIUM = "medium"
    HIGH = "high"
    UNKNOWN = "unknown"


@dataclass
class RoutingDecision:
    intent: str
    complexity: str
    execution_mode: str
    needs_tools: bool = False
    needs_agent: bool = False
    needs_multi_agent: bool = False
    recommended_model_tier: str = "cheap"
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

    def to_dict(self) -> dict:
        data = asdict(self)
        data["task_plan_summary"] = self.task_plan_summary
        data["synthesis_summary"] = self.synthesis_summary
        return data
