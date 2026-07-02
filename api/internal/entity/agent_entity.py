from copy import deepcopy
from enum import Enum
from typing import Any


class AgentModelTier(str, Enum):
    CHEAP = "cheap"
    STANDARD = "standard"
    STRONG = "strong"


class AgentCostLevel(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class AgentRiskLevel(str, Enum):
    SAFE = "safe"
    MEDIUM = "medium"
    HIGH = "high"


DEFAULT_AGENT_METADATA = {
    "primary_pool": "general",
    "secondary_pools": [],
    "capabilities": [],
    "task_types": [],
    "input_modalities": ["text"],
    "output_modalities": ["text"],
    "risk_level": AgentRiskLevel.SAFE.value,
    "model_tier": AgentModelTier.STANDARD.value,
    "model_id": "",
    "key_policy": "default",
    "cost_level": AgentCostLevel.MEDIUM.value,
    "routing_priority": 50,
    "allowed_tool_categories": [],
    "quality_score": 0.5,
    "success_rate": 0.0,
    "latency_p95": 0,
    "max_context_tokens": 0,
    "enabled": True,
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
    normalized["input_modalities"] = _normalize_string_list(
        normalized.get("input_modalities"), ["text"]
    )
    normalized["output_modalities"] = _normalize_string_list(
        normalized.get("output_modalities"), ["text"]
    )
    normalized["risk_level"] = _normalize_choice(
        normalized.get("risk_level"),
        {item.value for item in AgentRiskLevel},
        AgentRiskLevel.SAFE.value,
    )
    normalized["model_tier"] = _normalize_choice(
        normalized.get("model_tier"),
        {item.value for item in AgentModelTier},
        AgentModelTier.STANDARD.value,
    )
    normalized["model_id"] = _normalize_string(normalized.get("model_id"), "")
    normalized["key_policy"] = _normalize_string(normalized.get("key_policy"), "default")
    normalized["cost_level"] = _normalize_choice(
        normalized.get("cost_level"),
        {item.value for item in AgentCostLevel},
        AgentCostLevel.MEDIUM.value,
    )
    normalized["routing_priority"] = _normalize_int(
        normalized.get("routing_priority"), 50, minimum=0, maximum=1000
    )
    normalized["allowed_tool_categories"] = _normalize_string_list(
        normalized.get("allowed_tool_categories")
    )
    normalized["quality_score"] = _normalize_float(
        normalized.get("quality_score"), 0.5, minimum=0.0, maximum=1.0
    )
    normalized["success_rate"] = _normalize_float(
        normalized.get("success_rate"), 0.0, minimum=0.0, maximum=1.0
    )
    normalized["latency_p95"] = _normalize_int(
        normalized.get("latency_p95"), 0, minimum=0
    )
    normalized["max_context_tokens"] = _normalize_int(
        normalized.get("max_context_tokens"), 0, minimum=0
    )
    normalized["enabled"] = _normalize_bool(normalized.get("enabled"), True)
    return normalized


def _normalize_string(value: Any, default: str) -> str:
    if not isinstance(value, str):
        return default
    value = value.strip()
    return value or default


def _normalize_string_list(value: Any, default: list[str] | None = None) -> list[str]:
    if not isinstance(value, list):
        return list(default or [])
    result = []
    for item in value:
        if not isinstance(item, str):
            continue
        item = item.strip()
        if item and item not in result:
            result.append(item)
    return result or list(default or [])


def _normalize_choice(value: Any, choices: set[str], default: str) -> str:
    if not isinstance(value, str):
        return default
    value = value.strip()
    return value if value in choices else default


def _normalize_int(
    value: Any,
    default: int,
    *,
    minimum: int | None = None,
    maximum: int | None = None,
) -> int:
    try:
        result = int(value)
    except Exception:
        result = default
    if minimum is not None:
        result = max(result, minimum)
    if maximum is not None:
        result = min(result, maximum)
    return result


def _normalize_float(
    value: Any,
    default: float,
    *,
    minimum: float | None = None,
    maximum: float | None = None,
) -> float:
    try:
        result = float(value)
    except Exception:
        result = default
    if minimum is not None:
        result = max(result, minimum)
    if maximum is not None:
        result = min(result, maximum)
    return result


def _normalize_bool(value: Any, default: bool) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        value = value.strip().lower()
        if value in {"true", "1", "yes", "on"}:
            return True
        if value in {"false", "0", "no", "off"}:
            return False
    return default
