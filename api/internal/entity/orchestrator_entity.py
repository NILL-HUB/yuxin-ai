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

    def to_dict(self) -> dict:
        return asdict(self)
