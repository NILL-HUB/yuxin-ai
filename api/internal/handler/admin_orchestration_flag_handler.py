from dataclasses import dataclass
from uuid import UUID

from flask import g, request
from injector import inject

from internal.middleware import admin_login_required, permission_required
from internal.schema.admin_orchestration_flag_schema import (
    OrchestrationFlagResp,
    UpdateOrchestrationFlagReq,
)
from internal.service.orchestration_feature_flag_service import (
    OrchestrationFeatureFlagService,
)
from pkg.response import fail_message, success_json, validate_error_json


@inject
@dataclass
class AdminOrchestrationFlagHandler:
    orchestration_feature_flag_service: OrchestrationFeatureFlagService

    @admin_login_required
    @permission_required("orchestration_flag:read")
    def list(self):
        flags = self.orchestration_feature_flag_service.list_flags()
        return success_json(OrchestrationFlagResp(many=True).dump(flags))

    @admin_login_required
    @permission_required("orchestration_flag:update")
    def update(self, code: str):
        req = UpdateOrchestrationFlagReq(data=request.get_json(silent=True) or {})
        if not req.validate():
            return validate_error_json(req.errors)
        current_admin = getattr(g, "current_admin_user", {}) or {}
        try:
            result = self.orchestration_feature_flag_service.update_flag(
                code=code,
                enabled=bool(req.enabled.data),
                operator_id=UUID(current_admin.get("id")),
            )
        except ValueError as exc:
            return fail_message(str(exc))
        return success_json(OrchestrationFlagResp().dump(result))
