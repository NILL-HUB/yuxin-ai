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
    "cost_level": "medium",
    "requires_confirmation": False,
    "allowed_agent_pools": [],
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
    normalized["cost_level"] = _normalize_string(normalized.get("cost_level"), "medium")
    normalized["requires_confirmation"] = bool(normalized.get("requires_confirmation", False))
    normalized["allowed_agent_pools"] = _normalize_string_list(normalized.get("allowed_agent_pools"))
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
