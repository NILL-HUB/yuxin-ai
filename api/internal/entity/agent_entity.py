from copy import deepcopy
from enum import Enum
from typing import Any


class AgentModelTier(str, Enum):
    CHEAP = "cheap"
    BALANCED = "balanced"
    STRONG = "strong"


class AgentCostLevel(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


DEFAULT_AGENT_METADATA = {
    "primary_pool": "general",
    "secondary_pools": [],
    "capabilities": [],
    "task_types": [],
    "model_tier": AgentModelTier.BALANCED.value,
    "cost_level": AgentCostLevel.MEDIUM.value,
    "routing_priority": 0,
    "allowed_tool_categories": [],
}


def normalize_agent_metadata(metadata: dict[str, Any] | None) -> dict[str, Any]:
    normalized = deepcopy(DEFAULT_AGENT_METADATA)
    if not isinstance(metadata, dict):
        return normalized
    normalized.update({key: value for key, value in metadata.items() if key in normalized})
    normalized["primary_pool"] = _normalize_string(normalized.get("primary_pool"), "general")
    normalized["secondary_pools"] = _normalize_string_list(normalized.get("secondary_pools"))
    normalized["capabilities"] = _normalize_string_list(normalized.get("capabilities"))
    normalized["task_types"] = _normalize_string_list(normalized.get("task_types"))
    normalized["model_tier"] = _normalize_choice(
        normalized.get("model_tier"),
        {item.value for item in AgentModelTier},
        AgentModelTier.BALANCED.value,
    )
    normalized["cost_level"] = _normalize_choice(
        normalized.get("cost_level"),
        {item.value for item in AgentCostLevel},
        AgentCostLevel.MEDIUM.value,
    )
    normalized["routing_priority"] = _normalize_priority(normalized.get("routing_priority"))
    normalized["allowed_tool_categories"] = _normalize_string_list(
        normalized.get("allowed_tool_categories")
    )
    return normalized


def _normalize_string(value: Any, default: str) -> str:
    if not isinstance(value, str):
        return default
    value = value.strip()
    return value or default


def _normalize_string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    result = []
    for item in value:
        if not isinstance(item, str):
            continue
        item = item.strip()
        if item and item not in result:
            result.append(item)
    return result


def _normalize_choice(value: Any, choices: set[str], default: str) -> str:
    if not isinstance(value, str):
        return default
    value = value.strip()
    return value if value in choices else default


def _normalize_priority(value: Any) -> int:
    try:
        return max(min(int(value), 1000), 0)
    except Exception:
        return 0
