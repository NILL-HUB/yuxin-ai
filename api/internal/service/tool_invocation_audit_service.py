from dataclasses import dataclass
from typing import Any

from internal.service.audit_log_service import AuditLogService


SENSITIVE_ARGUMENT_NAMES = {"api_key", "token", "password", "secret", "credential"}


@dataclass
class ToolInvocationAuditService:
    def build_payload(
        self,
        *,
        audit_context: dict[str, Any],
        account_id: str,
        agent_id: str,
        request_id: str,
        arguments: dict[str, Any],
        latency_ms: int,
        status: str,
        failure_reason: str,
    ) -> dict[str, Any]:
        return {
            "tool_id": str(audit_context.get("tool_id") or ""),
            "runtime_name": str(audit_context.get("runtime_name") or ""),
            "source_type": str(audit_context.get("source_type") or ""),
            "provider_id": str(audit_context.get("provider_id") or ""),
            "account_id": account_id,
            "agent_id": agent_id,
            "request_id": request_id,
            "input_summary": self._input_summary(arguments),
            "latency_ms": max(int(latency_ms), 0),
            "status": status,
            "failure_reason": failure_reason,
        }

    def persist(
        self,
        *,
        account_id: str,
        payload: dict[str, Any],
        resource_id: str = "",
        commit: bool = True,
    ) -> Any:
        service = AuditLogService()
        return service.record_for_tool_invocation(
            account_id=account_id,
            action="tool_invocation",
            resource_type="tool",
            resource_id=resource_id or payload.get("tool_id", ""),
            after_data=payload,
            commit=commit,
        )

    @staticmethod
    def _input_summary(arguments: dict[str, Any]) -> dict[str, list[str]]:
        keys = sorted(str(key) for key in arguments.keys())
        redacted_keys = [
            key
            for key in keys
            if any(fragment in key.lower() for fragment in SENSITIVE_ARGUMENT_NAMES)
        ]
        return {"keys": keys, "redacted_keys": redacted_keys}
