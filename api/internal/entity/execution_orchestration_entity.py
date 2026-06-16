from dataclasses import dataclass, field
from typing import Any


RISK_LEVELS = {"safe", "sensitive", "dangerous"}


@dataclass
class TaskPlanItem:
    task_id: str
    title: str
    description: str = ""
    agent_pool: str = "general"
    required_capabilities: list[str] = field(default_factory=list)
    depends_on: list[str] = field(default_factory=list)
    execution_order: int = 0
    risk_level: str = "safe"

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "TaskPlanItem":
        return cls(
            task_id=_text(data.get("task_id")),
            title=_text(data.get("title")),
            description=_text(data.get("description")),
            agent_pool=_text(data.get("agent_pool")) or "general",
            required_capabilities=_unique_text_list(data.get("required_capabilities")),
            depends_on=_unique_text_list(data.get("depends_on")),
            execution_order=_non_negative_int(data.get("execution_order")),
            risk_level=_risk_level(data.get("risk_level")),
        )

    def to_summary(self) -> dict:
        return {
            "task_id": self.task_id,
            "title": self.title,
            "agent_pool": self.agent_pool,
            "execution_order": self.execution_order,
            "risk_level": self.risk_level,
        }


@dataclass
class TaskPlan:
    original_query: str
    items: list[TaskPlanItem] = field(default_factory=list)
    execution_mode: str = "direct_answer"
    reason: str = ""

    def to_summary(self) -> dict:
        return {
            "execution_mode": self.execution_mode,
            "reason": self.reason,
            "task_count": len(self.items),
            "items": [item.to_summary() for item in self.items],
        }


@dataclass
class OrchestratedAgentResult:
    agent_id: str
    task_id: str
    answer: str = ""
    confidence: float = 0
    sources: list[str] = field(default_factory=list)
    tool_calls: list[dict] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    cost: dict = field(default_factory=dict)
    metadata: dict = field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "OrchestratedAgentResult":
        return cls(
            agent_id=_text(data.get("agent_id")),
            task_id=_text(data.get("task_id")),
            answer=_text(data.get("answer")),
            confidence=_confidence(data.get("confidence")),
            sources=_unique_text_list(data.get("sources")),
            tool_calls=(
                data.get("tool_calls")
                if isinstance(data.get("tool_calls"), list)
                else []
            ),
            warnings=_unique_text_list(data.get("warnings")),
            errors=_unique_text_list(data.get("errors")),
            cost=data.get("cost") if isinstance(data.get("cost"), dict) else {},
            metadata=data.get("metadata") if isinstance(data.get("metadata"), dict) else {},
        )

    def to_user_safe_dict(self) -> dict:
        return {
            "answer": self.answer,
            "confidence": self.confidence,
            "sources": self.sources,
            "tool_calls": [_safe_tool_call(item) for item in self.tool_calls],
            "warnings": self.warnings,
            "errors": self.errors,
            "cost": self.cost,
        }


def _text(value: Any) -> str:
    return value.strip() if isinstance(value, str) else ""


def _unique_text_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    result = []
    for item in value:
        text = _text(item)
        if text and text not in result:
            result.append(text)
    return result


def _non_negative_int(value: Any) -> int:
    try:
        return max(int(value), 0)
    except (TypeError, ValueError):
        return 0


def _confidence(value: Any) -> float:
    try:
        return min(max(float(value), 0), 1)
    except (TypeError, ValueError):
        return 0


def _risk_level(value: Any) -> str:
    text = _text(value)
    return text if text in RISK_LEVELS else "safe"


def _safe_tool_call(value: dict) -> dict:
    if not isinstance(value, dict):
        return {}
    return {"name": _text(value.get("name"))}
