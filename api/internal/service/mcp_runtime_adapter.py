import re
from dataclasses import dataclass
from typing import Any

from internal.entity.runtime_tool_entity import RuntimeToolDescriptor


@dataclass
class McpRuntimeAdapter:
    def can_handle(self, candidate: dict[str, Any]) -> bool:
        return candidate.get("source_type") == "mcp"

    def to_runtime_tool(
        self, candidate: dict[str, Any], *, mount_reason: str = "dynamic_mcp_tool"
    ) -> RuntimeToolDescriptor | None:
        if not self.can_handle(candidate):
            return None
        runtime_name = "mcp__{}__{}".format(
            _safe_name(candidate.get("provider_id")),
            _safe_name(candidate.get("name")),
        )
        return RuntimeToolDescriptor.from_candidate(
            candidate,
            runtime_name=runtime_name,
            mount_reason=mount_reason,
        )


def _safe_name(value: Any) -> str:
    text = str(value or "").strip().lower()
    text = re.sub(r"[^a-z0-9_]+", "_", text)
    text = re.sub(r"_+", "_", text).strip("_")
    return text or "tool"
