from dataclasses import dataclass
from time import perf_counter
from typing import Any, Callable

from internal.entity.runtime_tool_entity import (
    RuntimeToolCallRequest,
    RuntimeToolCallResult,
    RuntimeToolDescriptor,
)
from internal.entity.tool_inventory_entity import RiskLevel
from internal.service.runtime_tool_mount_service import RuntimeToolMountService
from internal.service.tool_invocation_audit_service import ToolInvocationAuditService


ToolExecutor = Callable[[dict[str, Any], RuntimeToolDescriptor], Any]


@dataclass
class ToolInvokerService:
    def invoke(
        self,
        *,
        mounted_tools: list[RuntimeToolDescriptor],
        request: RuntimeToolCallRequest,
        executors: dict[str, ToolExecutor],
        confirmed: bool = True,
    ) -> RuntimeToolCallResult:
        started_at = perf_counter()
        tool = RuntimeToolMountService.get_mounted_tool(
            mounted_tools, request.runtime_name
        )
        if tool is None:
            return self._failure(
                request=request,
                tool=None,
                started_at=started_at,
                error_code="tool_not_mounted",
                error_message="工具未挂载",
            )

        missing_arguments = self._missing_required_arguments(tool, request.arguments)
        if missing_arguments:
            return self._failure(
                request=request,
                tool=tool,
                started_at=started_at,
                error_code="invalid_arguments",
                error_message="缺少必填参数: {}".format(", ".join(missing_arguments)),
            )

        security_error = self._security_error(tool, request, confirmed)
        if security_error:
            return self._failure(
                request=request,
                tool=tool,
                started_at=started_at,
                error_code=security_error["error_code"],
                error_message=security_error["error_message"],
            )

        executor = executors.get(tool.runtime_name)
        if executor is None:
            return self._failure(
                request=request,
                tool=tool,
                started_at=started_at,
                error_code="executor_not_found",
                error_message="工具执行器不存在",
            )

        try:
            output = executor(request.arguments, tool)
        except Exception as exc:
            return self._failure(
                request=request,
                tool=tool,
                started_at=started_at,
                error_code="tool_execution_failed",
                error_message=str(exc),
            )

        latency_ms = self._latency_ms(started_at)
        return RuntimeToolCallResult.success_result(
            output=output,
            latency_ms=latency_ms,
            audit_payload=self._audit_payload(
                request=request,
                tool=tool,
                latency_ms=latency_ms,
                status="success",
                failure_reason="",
            ),
        )

    def _failure(
        self,
        *,
        request: RuntimeToolCallRequest,
        tool: RuntimeToolDescriptor | None,
        started_at: float,
        error_code: str,
        error_message: str,
    ) -> RuntimeToolCallResult:
        latency_ms = self._latency_ms(started_at)
        return RuntimeToolCallResult.failure_result(
            error_code=error_code,
            error_message=error_message,
            latency_ms=latency_ms,
            audit_payload=self._audit_payload(
                request=request,
                tool=tool,
                latency_ms=latency_ms,
                status="failure",
                failure_reason=error_code,
            ),
        )

    @staticmethod
    def _security_error(
        tool: RuntimeToolDescriptor,
        request: RuntimeToolCallRequest,
        confirmed: bool,
    ) -> dict[str, str] | None:
        risk_level = str(tool.metadata.get("risk_level") or "")
        if risk_level == "dangerous":
            return {"error_code": "forbidden", "error_message": "危险工具禁止自动调用"}
        if risk_level in {RiskLevel.HIGH.value, "sensitive"} and not confirmed:
            return {
                "error_code": "confirmation_required",
                "error_message": "高风险工具需要确认后调用",
            }
        if tool.metadata.get("user_scope") == "owner" and tool.metadata.get(
            "owner"
        ) not in {"system", request.account_id}:
            return {
                "error_code": "permission_scope_denied",
                "error_message": "工具权限范围不匹配",
            }
        return None

    @staticmethod
    def _missing_required_arguments(
        tool: RuntimeToolDescriptor, arguments: dict[str, Any]
    ) -> list[str]:
        missing = []
        for item in tool.input_schema:
            if item.get("required") and item.get("name") not in arguments:
                missing.append(str(item.get("name")))
        return missing

    @staticmethod
    def _latency_ms(started_at: float) -> int:
        return max(int((perf_counter() - started_at) * 1000), 0)

    @staticmethod
    def _audit_payload(
        *,
        request: RuntimeToolCallRequest,
        tool: RuntimeToolDescriptor | None,
        latency_ms: int,
        status: str,
        failure_reason: str,
    ) -> dict[str, Any]:
        audit_context = tool.audit_context if tool is not None else {
            "runtime_name": request.runtime_name
        }
        return ToolInvocationAuditService().build_payload(
            audit_context=audit_context,
            account_id=request.account_id,
            agent_id=request.agent_id,
            request_id=request.request_id,
            arguments=request.arguments,
            latency_ms=latency_ms,
            status=status,
            failure_reason=failure_reason,
        )
