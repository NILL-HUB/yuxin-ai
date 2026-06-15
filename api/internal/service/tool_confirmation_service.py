from dataclasses import dataclass
from typing import Callable

from injector import inject

from internal.exception import ForbiddenException, NotFoundException
from internal.model import Account, ToolConfirmation
from pkg.sqlalchemy import SQLAlchemy
from .base_service import BaseService


@inject
@dataclass
class ToolConfirmationService(BaseService):
    db: SQLAlchemy

    def create_confirmation(
        self,
        *,
        account: Account,
        tool_name: str,
        risk_level: str,
        tool_input: dict,
        spent_credits: int = 0,
        reason: str = "",
    ) -> ToolConfirmation:
        return self.create(
            ToolConfirmation,
            owner_account_id=account.id,
            tool_name=tool_name,
            risk_level=risk_level,
            tool_input=tool_input,
            status="pending",
            spent_credits=spent_credits,
            reason=reason,
        )

    def confirm(self, confirmation_id, account: Account) -> ToolConfirmation:
        confirmation = self._get_owned_confirmation(confirmation_id, account)
        confirmation.status = "confirmed"
        return confirmation

    def cancel(self, confirmation_id, account: Account) -> ToolConfirmation:
        confirmation = self._get_owned_confirmation(confirmation_id, account)
        confirmation.status = "cancelled"
        return confirmation

    def _get_owned_confirmation(self, confirmation_id, account: Account) -> ToolConfirmation:
        confirmation = (
            self.db.session.query(ToolConfirmation)
            .filter_by(id=confirmation_id)
            .one_or_none()
        )
        if confirmation is None or confirmation.owner_account_id != account.id:
            raise NotFoundException("工具确认记录不存在")
        return confirmation


class ToolInvoker:
    def __init__(self, executor: Callable[[dict, dict], dict] | None = None):
        self.executor = executor or (lambda tool, tool_input: {"ok": True})

    def invoke(
        self,
        *,
        tool: dict,
        tool_input: dict,
        confirmation: ToolConfirmation | None = None,
    ) -> dict:
        risk_level = tool.get("metadata", {}).get("risk_level", "safe")
        if risk_level in {"medium", "high"} and getattr(confirmation, "status", None) != "confirmed":
            raise ForbiddenException("高风险工具执行前需要用户确认")
        return self.executor(tool, tool_input)
