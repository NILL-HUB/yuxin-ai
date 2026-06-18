from dataclasses import dataclass
from uuid import UUID

from flask import request
from flask_login import current_user, login_required
from injector import inject

from internal.schema.tool_confirmation_schema import (
    CreateToolConfirmationReq,
    ListToolConfirmationReq,
    ToolConfirmationListResp,
    ToolConfirmationResp,
)
from internal.service.tool_confirmation_service import ToolConfirmationService
from pkg.response import success_json, validate_error_json


@inject
@dataclass
class ToolConfirmationHandler:
    tool_confirmation_service: ToolConfirmationService

    @login_required
    def list(self):
        req = ListToolConfirmationReq(request.args)
        if not req.validate():
            return validate_error_json(req.errors)
        confirmations = self.tool_confirmation_service.list_confirmations(
            account=current_user,
            status=req.status.data or "",
        )
        return success_json(
            ToolConfirmationListResp().dump(
                {"items": confirmations, "total": len(confirmations)}
            )
        )

    @login_required
    def get(self, confirmation_id: UUID):
        confirmation = self.tool_confirmation_service.get_confirmation(
            confirmation_id,
            current_user,
        )
        return success_json(ToolConfirmationResp().dump(confirmation))

    @login_required
    def create(self):
        req = CreateToolConfirmationReq()
        if not req.validate():
            return validate_error_json(req.errors)
        confirmation = self.tool_confirmation_service.create_confirmation(
            account=current_user,
            tool_name=req.tool_name.data,
            risk_level=req.risk_level.data,
            tool_input=req.tool_input.data,
            spent_credits=req.spent_credits.data,
            reason=req.reason.data,
        )
        return success_json(ToolConfirmationResp().dump(confirmation))

    @login_required
    def confirm(self, confirmation_id: UUID):
        confirmation = self.tool_confirmation_service.confirm(
            confirmation_id,
            current_user,
        )
        return success_json(ToolConfirmationResp().dump(confirmation))

    @login_required
    def cancel(self, confirmation_id: UUID):
        confirmation = self.tool_confirmation_service.cancel(
            confirmation_id,
            current_user,
        )
        return success_json(ToolConfirmationResp().dump(confirmation))
