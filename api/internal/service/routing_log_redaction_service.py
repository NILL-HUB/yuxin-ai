from copy import deepcopy
from typing import Any

from internal.entity.routing_observability_entity import DEFAULT_SENSITIVE_FIELDS


class RoutingLogRedactionService:
    def redact(
        self,
        payload: Any,
        *,
        redaction_enabled: bool = False,
        sensitive_fields: list[str] | None = None,
    ) -> Any:
        copied = deepcopy(payload)
        if not redaction_enabled:
            return copied
        return self._redact_value(
            copied,
            set(sensitive_fields or DEFAULT_SENSITIVE_FIELDS),
        )

    def _redact_value(self, value: Any, sensitive_fields: set[str]) -> Any:
        if isinstance(value, dict):
            return {
                key: "[REDACTED]"
                if key in sensitive_fields
                else self._redact_value(item, sensitive_fields)
                for key, item in value.items()
            }
        if isinstance(value, list):
            return [self._redact_value(item, sensitive_fields) for item in value]
        return value
