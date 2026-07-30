from dataclasses import dataclass, field
from typing import Any

from .base_entity import SerializableMixin


MODEL_HEALTH_STATUSES = {"healthy", "degraded", "unknown"}
KEY_STATUSES = {"active", "inactive", "circuit_open"}


@dataclass
class ModelPoolItem(SerializableMixin):
    provider: str
    model: str
    tier: str = "2"
    capabilities: list[str] = field(default_factory=list)
    price_per_1k_input_tokens: float = 0
    price_per_1k_output_tokens: float = 0
    context_window: int = 0
    health_status: str = "unknown"
    rate_limit_per_minute: int = 0
    enabled: bool = True

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ModelPoolItem":
        tier = data.get("tier") or "2"
        return cls(
            provider=_text(data.get("provider")),
            model=_text(data.get("model")),
            tier=tier,
            capabilities=_unique_text_list(data.get("capabilities")),
            price_per_1k_input_tokens=_non_negative_float(
                data.get("price_per_1k_input_tokens")
            ),
            price_per_1k_output_tokens=_non_negative_float(
                data.get("price_per_1k_output_tokens")
            ),
            context_window=_non_negative_int(data.get("context_window")),
            health_status=_one_of(
                data.get("health_status"), MODEL_HEALTH_STATUSES, "unknown"
            ),
            rate_limit_per_minute=_non_negative_int(data.get("rate_limit_per_minute")),
            enabled=_bool(data.get("enabled"), True),
        )


@dataclass
class ModelKeyItem:
    provider: str
    key_id: str
    secret: str = ""
    tenant_scope: str = ""
    status: str = "inactive"
    quota_credits: float = 0
    used_credits: float = 0
    failure_count: int = 0

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ModelKeyItem":
        quota_credits = _non_negative_float(data.get("quota_credits"))
        used_credits = min(_non_negative_float(data.get("used_credits")), quota_credits)
        return cls(
            provider=_text(data.get("provider")),
            key_id=_text(data.get("key_id")),
            secret="",
            tenant_scope=_text(data.get("tenant_scope")),
            status=_one_of(data.get("status"), KEY_STATUSES, "inactive"),
            quota_credits=quota_credits,
            used_credits=used_credits,
            failure_count=_non_negative_int(data.get("failure_count")),
        )

    @property
    def remaining_credits(self) -> float:
        return max(self.quota_credits - self.used_credits, 0)

    def to_safe_dict(self) -> dict[str, Any]:
        return {
            "provider": self.provider,
            "key_id": self.key_id,
            "tenant_scope": self.tenant_scope,
            "status": self.status,
            "quota_credits": self.quota_credits,
            "used_credits": self.used_credits,
            "remaining_credits": self.remaining_credits,
            "failure_count": self.failure_count,
        }


def _text(value: Any) -> str:
    return value.strip() if isinstance(value, str) else ""


def _one_of(value: Any, allowed: set[str], default: str) -> str:
    text = _text(value)
    return text if text in allowed else default


def _unique_text_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    result = []
    for item in value:
        text = _text(item)
        if text and text not in result:
            result.append(text)
    return result


def _non_negative_float(value: Any) -> float:
    try:
        return max(float(value), 0)
    except (TypeError, ValueError):
        return 0


def _non_negative_int(value: Any) -> int:
    try:
        return max(int(value), 0)
    except (TypeError, ValueError):
        return 0


def _bool(value: Any, default: bool) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"true", "1", "yes", "on"}
    return default
