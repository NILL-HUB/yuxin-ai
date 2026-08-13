from dataclasses import dataclass, field
import logging
import os
import threading

from injector import inject

from internal.exception import NotFoundException
from internal.model import Account, ToolConfirmation
from internal.service.tool_invocation_audit_service import ToolInvocationAuditService
from internal.service.tool_invoker_service import build_non_interruptible_write_audit_hint
from pkg.sqlalchemy import SQLAlchemy
from .base_service import BaseService


logger = logging.getLogger(__name__)


@inject
@dataclass
class ToolConfirmationService(BaseService):
    db: SQLAlchemy
    tool_invocation_audit_service: ToolInvocationAuditService = field(
        default_factory=ToolInvocationAuditService
    )

    def create_confirmation(
        self,
        *,
        account: Account,
        tool_name: str,
        risk_level: str,
        tool_input: dict,
        spent_credits: int = 0,
        reason: str = "",
        target_system: str = "",
        target_environment: str = "",
        execution_summary: str = "",
        impact_scope: str = "",
        rollback_strategy: str = "",
        audit_hint: str = "",
    ) -> ToolConfirmation:
        if not audit_hint:
            audit_hint = build_non_interruptible_write_audit_hint(
                risk_level=risk_level, tool_input=tool_input
            )
        return self.create(
            ToolConfirmation,
            owner_account_id=account.id,
            tool_name=tool_name,
            risk_level=risk_level,
            tool_input=tool_input,
            status="pending",
            spent_credits=spent_credits,
            reason=reason,
            target_system=target_system,
            target_environment=target_environment,
            execution_summary=execution_summary,
            impact_scope=impact_scope,
            rollback_strategy=rollback_strategy,
            audit_hint=audit_hint,
        )

    def confirm(self, confirmation_id, account: Account) -> ToolConfirmation:
        confirmation = self._get_owned_confirmation(confirmation_id, account)
        if confirmation.status != "pending":
            return confirmation
        with self.db.auto_commit():
            confirmation.status = "confirmed"
            self._record_audit(
                confirmation, account, action="confirm", decision="approved"
            )
        self._dispatch_lifecycle_event("tool.confirmed", confirmation, account)
        return confirmation

    def cancel(self, confirmation_id, account: Account) -> ToolConfirmation:
        confirmation = self._get_owned_confirmation(confirmation_id, account)
        if confirmation.status != "pending":
            return confirmation
        with self.db.auto_commit():
            confirmation.status = "cancelled"
            self._record_audit(
                confirmation, account, action="cancel", decision="cancelled"
            )
        self._dispatch_lifecycle_event("tool.cancelled", confirmation, account)
        return confirmation

    def _dispatch_lifecycle_event(
        self,
        event_type: str,
        confirmation: ToolConfirmation,
        account: Account,
    ) -> None:
        """推送工具确认生命周期事件到外部端点（HMAC 签名，最佳努力）。"""
        webhook_url = str(os.getenv("OUTBOUND_WEBHOOK_URL") or "").strip()
        webhook_secret = str(os.getenv("OUTBOUND_WEBHOOK_SECRET") or "").strip()
        if not webhook_url or not webhook_secret:
            return
        try:
            from internal.core.agent.adapters.hermes.outbound_webhook import (
                build_event,
                deliver_webhook,
            )

            event = build_event(
                event_type=event_type,
                subject_type="tool_confirmation",
                subject_id=str(confirmation.id),
                payload={
                    "tool_name": confirmation.tool_name,
                    "status": confirmation.status,
                    "risk_level": confirmation.risk_level,
                    "owner_account_id": str(account.id),
                    "execution_summary": str(confirmation.execution_summary or ""),
                },
            )
            threading.Thread(
                target=deliver_webhook,
                args=(webhook_url, webhook_secret, event),
                daemon=True,
            ).start()
        except Exception:
            logger.warning("推送工具确认 webhook 失败，不影响主流程", exc_info=True)

    def _record_audit(self, confirmation, account, *, action: str, decision: str) -> None:
        try:
            self.tool_invocation_audit_service.record(
                account_id=str(account.id),
                tool_name=confirmation.tool_name,
                risk_level=confirmation.risk_level,
                input_data=confirmation.tool_input or {},
                action=action,
                decision=decision,
                resource_id=str(confirmation.id),
                commit=False,
            )
        except Exception:
            logger.warning("记录工具确认审计日志失败", exc_info=True)

    def list_confirmations(
        self,
        account: Account,
        status: str = "",
    ) -> list[ToolConfirmation]:
        query = self.db.session.query(ToolConfirmation).filter_by(
            owner_account_id=account.id
        )
        if status:
            query = query.filter(ToolConfirmation.status == status)
        return query.order_by(ToolConfirmation.created_at.desc()).all()

    def get_confirmation(
        self,
        confirmation_id,
        account: Account,
    ) -> ToolConfirmation:
        return self._get_owned_confirmation(confirmation_id, account)

    def _get_owned_confirmation(self, confirmation_id, account: Account) -> ToolConfirmation:
        confirmation = (
            self.db.session.query(ToolConfirmation)
            .filter_by(id=confirmation_id)
            .one_or_none()
        )
        if confirmation is None or confirmation.owner_account_id != account.id:
            raise NotFoundException("工具确认记录不存在")
        return confirmation
