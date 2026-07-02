from dataclasses import dataclass, field
from typing import Any

from .base_entity import SerializableMixin
from internal.entity.tool_inventory_entity import normalize_tool_metadata


@dataclass
class CompositeComponentRef(SerializableMixin):
    tool_id: str
    source_type: str
    ref_path: str
    is_recursive: bool = False


@dataclass
class RuntimeToolDescriptor(SerializableMixin):
    tool_id: str
    runtime_name: str
    name: str
    description: str
    source_type: str
    provider_id: str
    provider_name: str
    input_schema: list[dict[str, Any]] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)
    audit_context: dict[str, Any] = field(default_factory=dict)
    is_composite: bool = False
    composite_kind: str = ""
    composite_components: list = field(default_factory=list)
    composite_root_id: str = ""
    runtime_name_stable: bool = True

    @classmethod
    def from_candidate(
        cls,
        candidate: dict[str, Any],
        *,
        runtime_name: str,
        mount_reason: str,
    ) -> "RuntimeToolDescriptor":
        metadata = normalize_tool_metadata(candidate.get("metadata"))
        tool_id = str(candidate.get("id") or "")
        source_type = str(candidate.get("source_type") or "")
        provider_id = str(candidate.get("provider_id") or "")
        provider_name = str(candidate.get("provider_name") or "")
        normalized_runtime_name = _normalize_text(runtime_name)
        return cls(
            tool_id=tool_id,
            runtime_name=normalized_runtime_name,
            name=str(candidate.get("name") or ""),
            description=str(candidate.get("description") or ""),
            source_type=source_type,
            provider_id=provider_id,
            provider_name=provider_name,
            input_schema=list(candidate.get("inputs") or []),
            metadata=metadata,
            audit_context={
                "tool_id": tool_id,
                "runtime_name": normalized_runtime_name,
                "source_type": source_type,
                "provider_id": provider_id,
                "provider_name": provider_name,
                "tool_pool": metadata["tool_pool"],
                "risk_level": metadata["risk_level"],
                "permission_scope": metadata["permission_scope"],
                "mount_reason": mount_reason,
            },
        )


@dataclass
class RuntimeToolCallRequest:
    runtime_name: str
    arguments: dict[str, Any]
    account_id: str
    agent_id: str
    request_id: str

    def __post_init__(self):
        self.runtime_name = _normalize_text(self.runtime_name)
        self.account_id = _normalize_text(self.account_id)
        self.agent_id = _normalize_text(self.agent_id)
        self.request_id = _normalize_text(self.request_id)
        if not isinstance(self.arguments, dict):
            self.arguments = {}


@dataclass
class RuntimeToolCallResult(SerializableMixin):
    success: bool
    output: Any = None
    error_code: str = ""
    error_message: str = ""
    latency_ms: int = 0
    audit_payload: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def success_result(
        cls, *, output: Any, latency_ms: int, audit_payload: dict[str, Any]
    ) -> "RuntimeToolCallResult":
        return cls(
            success=True,
            output=output,
            latency_ms=max(int(latency_ms), 0),
            audit_payload=dict(audit_payload),
        )

    @classmethod
    def failure_result(
        cls,
        *,
        error_code: str,
        error_message: str,
        latency_ms: int,
        audit_payload: dict[str, Any],
    ) -> "RuntimeToolCallResult":
        return cls(
            success=False,
            error_code=error_code,
            error_message=error_message,
            latency_ms=max(int(latency_ms), 0),
            audit_payload=dict(audit_payload),
        )


def _normalize_text(value: Any) -> str:
    if not isinstance(value, str):
        return ""
    return value.strip()
