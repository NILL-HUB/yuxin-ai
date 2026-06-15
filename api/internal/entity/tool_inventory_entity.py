from enum import Enum
from typing import Any


class ToolSourceType(str, Enum):
    API = "api"
    MCP = "mcp"
    BUILTIN = "builtin"
    KNOWLEDGE = "knowledge"


class RiskLevel(str, Enum):
    SAFE = "safe"
    MEDIUM = "medium"
    HIGH = "high"


DEFAULT_TOOL_METADATA = {
    "tool_pool": "general",
    "tool_tags": [],
    "capabilities": [],
    "risk_level": RiskLevel.MEDIUM.value,
    "permission_scope": "user",
    "cost_level": "medium",
    "health_status": "healthy",
    "success_rate": 0.0,
    "avg_latency": 0,
    "owner": "system",
    "knowledge_scope": "none",
    "tenant_scope": "default",
    "user_scope": "owner",
    "requires_confirmation": False,
    "allowed_agent_pools": [],
    "enabled": True,
}


def normalize_tool_metadata(metadata: dict[str, Any] | None) -> dict[str, Any]:
    normalized = dict(DEFAULT_TOOL_METADATA)
    if isinstance(metadata, dict):
        normalized.update(
            {key: value for key, value in metadata.items() if key in normalized}
        )
    normalized["tool_pool"] = _normalize_string(normalized.get("tool_pool"), "general")
    normalized["tool_tags"] = _normalize_string_list(normalized.get("tool_tags"))
    normalized["capabilities"] = _normalize_string_list(normalized.get("capabilities"))
    normalized["risk_level"] = _normalize_choice(
        normalized.get("risk_level"),
        {item.value for item in RiskLevel},
        RiskLevel.MEDIUM.value,
    )
    normalized["permission_scope"] = _normalize_choice(
        normalized.get("permission_scope"),
        {"system", "tenant", "project", "user", "public"},
        "user",
    )
    normalized["cost_level"] = _normalize_choice(
        normalized.get("cost_level"), {"low", "medium", "high"}, "medium"
    )
    normalized["health_status"] = _normalize_choice(
        normalized.get("health_status"),
        {"healthy", "degraded", "unhealthy"},
        "healthy",
    )
    normalized["success_rate"] = _normalize_float(
        normalized.get("success_rate"), 0.0, minimum=0.0, maximum=1.0
    )
    normalized["avg_latency"] = _normalize_int(
        normalized.get("avg_latency"), 0, minimum=0
    )
    normalized["owner"] = _normalize_string(normalized.get("owner"), "system")
    normalized["knowledge_scope"] = _normalize_string(
        normalized.get("knowledge_scope"), "none"
    )
    normalized["tenant_scope"] = _normalize_string(
        normalized.get("tenant_scope"), "default"
    )
    normalized["user_scope"] = _normalize_choice(
        normalized.get("user_scope"), {"owner", "shared", "public"}, "owner"
    )
    normalized["requires_confirmation"] = _normalize_bool(
        normalized.get("requires_confirmation", False)
    )
    normalized["allowed_agent_pools"] = _normalize_string_list(normalized.get("allowed_agent_pools"))
    normalized["enabled"] = _normalize_bool(normalized.get("enabled", True))
    return normalized


def _normalize_string(value: Any, default: str) -> str:
    if not isinstance(value, str):
        return default
    value = value.strip()
    return value or default


def _normalize_choice(value: Any, choices: set[str], default: str) -> str:
    if not isinstance(value, str):
        return default
    value = value.strip()
    return value if value in choices else default


def _normalize_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on"}
    return bool(value)


def _normalize_float(
    value: Any, default: float, *, minimum: float, maximum: float
) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    return min(max(number, minimum), maximum)


def _normalize_int(value: Any, default: int, *, minimum: int) -> int:
    try:
        number = int(value)
    except (TypeError, ValueError):
        return default
    return max(number, minimum)


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
