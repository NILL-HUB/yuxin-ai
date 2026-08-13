from dataclasses import dataclass
import logging
from time import perf_counter
from typing import Any, Callable

from internal.entity.runtime_tool_entity import (
    RuntimeToolCallRequest,
    RuntimeToolCallResult,
    RuntimeToolDescriptor,
)
from internal.entity.tool_inventory_entity import RiskLevel
from internal.core.context_compression.compressor import DEFAULT_MAX_TOOL_RESULT_CHARS
from internal.security.prompt_injection_detector import PromptInjectionDetector
from internal.service.runtime_tool_mount_service import RuntimeToolMountService
from internal.service.tool_invocation_audit_service import ToolInvocationAuditService


logger = logging.getLogger(__name__)

ToolExecutor = Callable[[dict[str, Any], RuntimeToolDescriptor], Any]


@dataclass
class ToolInvokerService:
    event_logger: Any = None

    def invoke(
        self,
        *,
        mounted_tools: list[RuntimeToolDescriptor],
        request: RuntimeToolCallRequest,
        executors: dict[str, ToolExecutor],
        confirmed: bool = True,
        routing_log_id=None,
    ) -> RuntimeToolCallResult:
        started_at = perf_counter()
        tool = RuntimeToolMountService.get_mounted_tool(
            mounted_tools, request.runtime_name
        )
        result: RuntimeToolCallResult | None = None
        if tool is None:
            result = self._failure(
                request=request,
                tool=None,
                started_at=started_at,
                error_code="tool_not_mounted",
                error_message="工具未挂载",
            )
            self._emit_tool_invoked(routing_log_id, request, tool, "failure", "tool_not_mounted")
            return result

        missing_arguments = self._missing_required_arguments(tool, request.arguments)
        if missing_arguments:
            result = self._failure(
                request=request,
                tool=tool,
                started_at=started_at,
                error_code="invalid_arguments",
                error_message="缺少必填参数: {}".format(", ".join(missing_arguments)),
            )
            self._emit_tool_invoked(routing_log_id, request, tool, "failure", "invalid_arguments")
            return result

        security_error = self._security_error(tool, request, confirmed)
        if security_error:
            result = self._failure(
                request=request,
                tool=tool,
                started_at=started_at,
                error_code=security_error["error_code"],
                error_message=security_error["error_message"],
            )
            self._emit_tool_invoked(routing_log_id, request, tool, "failure", security_error["error_code"])
            return result

        executor = executors.get(tool.runtime_name)
        if executor is None:
            result = self._failure(
                request=request,
                tool=tool,
                started_at=started_at,
                error_code="executor_not_found",
                error_message="工具执行器不存在",
            )
            self._emit_tool_invoked(routing_log_id, request, tool, "failure", "executor_not_found")
            return result

        try:
            output = executor(request.arguments, tool)
            output = _truncate_tool_output(output)
        except Exception as exc:
            result = self._failure(
                request=request,
                tool=tool,
                started_at=started_at,
                error_code="tool_execution_failed",
                error_message=str(exc),
            )
            self._emit_tool_invoked(routing_log_id, request, tool, "failure", "tool_execution_failed")
            return result

        latency_ms = self._latency_ms(started_at)
        audit_payload = self._audit_payload(
            request=request,
            tool=tool,
            latency_ms=latency_ms,
            status="success",
            failure_reason="",
        )
        audit_hint = build_non_interruptible_write_audit_hint(
            risk_level=str(tool.metadata.get("risk_level") or ""),
            tool_input=request.arguments,
        )
        if audit_hint:
            audit_payload = {**audit_payload, "audit_hint": audit_hint}
        self._persist_audit(request, tool, audit_payload)
        result = RuntimeToolCallResult.success_result(
            output=output,
            latency_ms=latency_ms,
            audit_payload=audit_payload,
        )
        self._emit_tool_invoked(routing_log_id, request, tool, "success", "")
        return result

    def _emit_tool_invoked(self, routing_log_id, request, tool, status, error_code) -> None:
        if self.event_logger is None or routing_log_id is None:
            return
        try:
            self.event_logger.log_event("tool_invoked", routing_log_id, {
                "runtime_name": request.runtime_name,
                "tool_id": str(tool.tool_id) if tool else "",
                "status": status,
                "error_code": error_code,
            })
        except Exception:
            logger.warning("记录 tool_invoked 审计事件失败", exc_info=True)

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
        audit_payload = self._audit_payload(
            request=request,
            tool=tool,
            latency_ms=latency_ms,
            status="failure",
            failure_reason=error_code,
        )
        self._persist_audit(request, tool, audit_payload)
        return RuntimeToolCallResult.failure_result(
            error_code=error_code,
            error_message=error_message,
            latency_ms=latency_ms,
            audit_payload=audit_payload,
        )

    @staticmethod
    def _persist_audit(
        request: RuntimeToolCallRequest,
        tool: RuntimeToolDescriptor | None,
        audit_payload: dict[str, Any],
    ) -> None:
        try:
            ToolInvocationAuditService().persist(
                account_id=str(request.account_id or ""),
                payload=audit_payload,
                resource_id=str(tool.tool_id) if tool else "",
                commit=False,
            )
        except Exception:
            logger.warning("持久化工具调用审计记录失败", exc_info=True)

    @staticmethod
    def _security_error(
        tool: RuntimeToolDescriptor,
        request: RuntimeToolCallRequest,
        confirmed: bool,
    ) -> dict[str, str] | None:
        injection_text = _flatten_tool_input(request.arguments)
        if injection_text:
            injection_result = PromptInjectionDetector.analyze(injection_text)
            if injection_result["severity"] == "high":
                return {
                    "error_code": "prompt_injection_detected",
                    "error_message": "检测到潜在的安全注入风险，请求已被拦截",
                }

        risk_level = str(tool.metadata.get("risk_level") or "")
        if risk_level == RiskLevel.DANGEROUS.value:
            return {"error_code": "forbidden", "error_message": "危险工具禁止自动调用"}
        if risk_level in {RiskLevel.HIGH.value, RiskLevel.SENSITIVE.value} and not confirmed:
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


NON_INTERRUPTIBLE_WRITE_KEYWORDS = (
    "write",
    "delete",
    "create",
    "update",
    "remove",
    "drop",
    "insert",
    "modify",
)

NON_INTERRUPTIBLE_WRITE_AUDIT_HINT = "操作已生效或可能已生效，请检查目标系统状态"


def build_non_interruptible_write_audit_hint(
    *, risk_level: str, tool_input: dict[str, Any] | None
) -> str:
    if is_non_interruptible_write(risk_level=risk_level, tool_input=tool_input):
        return NON_INTERRUPTIBLE_WRITE_AUDIT_HINT
    return ""


def is_non_interruptible_write(
    *, risk_level: str, tool_input: dict[str, Any] | None
) -> bool:
    if str(risk_level or "").lower() == RiskLevel.HIGH.value:
        return True
    text = _flatten_tool_input(tool_input or {})
    if not text:
        return False
    lowered = text.lower()
    return any(keyword in lowered for keyword in NON_INTERRUPTIBLE_WRITE_KEYWORDS)


def _flatten_tool_input(tool_input: Any) -> str:
    parts: list[str] = []
    stack: list[Any] = [tool_input]
    while stack:
        value = stack.pop()
        if isinstance(value, dict):
            stack.extend(value.values())
        elif isinstance(value, (list, tuple, set)):
            stack.extend(value)
        elif value is None:
            continue
        else:
            parts.append(str(value))
    return " ".join(parts)


def _truncate_tool_output(output: Any) -> Any:
    """工具输出主动裁剪：字符串超阈值时保留头尾并标记截断。"""
    if not isinstance(output, str) or len(output) <= DEFAULT_MAX_TOOL_RESULT_CHARS:
        return output
    head_size = int(DEFAULT_MAX_TOOL_RESULT_CHARS * 0.7)
    tail_size = DEFAULT_MAX_TOOL_RESULT_CHARS - head_size
    marker = f"\n...[工具结果过长，已截断，原长度 {len(output)} 字符]...\n"
    return output[:head_size] + marker + output[-tail_size:]
