from dataclasses import dataclass
from uuid import UUID

from flask import g, request
from injector import inject

from internal.middleware import admin_login_required, permission_required
from internal.schema.admin_app_assignment_schema import AssignAppsResp, AppAssignmentListResp, AppAssignmentResp
from internal.service.admin_app_assignment_service import AdminAppAssignmentService
from pkg.response import success_json, validate_error_json


def _get_operator_context() -> tuple:
    current_admin = getattr(g, "current_admin_user", None) or {}
    operator_id = current_admin.get("id") if isinstance(current_admin, dict) else getattr(current_admin, "id", None)
    return (
        operator_id,
        request.headers.get("X-Forwarded-For", request.remote_addr or ""),
        request.headers.get("User-Agent", ""),
    )


@inject
@dataclass
class AdminAppAssignmentHandler:
    admin_app_assignment_service: AdminAppAssignmentService

    @admin_login_required
    @permission_required("app_assignment:read")
    def list_assignments(self, account_id: UUID):
        resp = AppAssignmentListResp()
        return success_json(resp.dump(self.admin_app_assignment_service.list_assignments(account_id)))

    @admin_login_required
    @permission_required("app_assignment:update")
    def assign_apps(self, account_id: UUID):
        payload = request.get_json(silent=True) or {}
        app_ids = payload.get("app_ids") or []
        if not isinstance(app_ids, list) or not app_ids:
            return validate_error_json({"app_ids": ["应用 ID 列表不能为空"]})
        try:
            app_ids = [UUID(app_id) for app_id in app_ids]
        except (TypeError, ValueError):
            return validate_error_json({"app_ids": ["应用 ID 格式错误"]})
        operator_id, ip, user_agent = _get_operator_context()
        resp = AssignAppsResp()
        return success_json(
            resp.dump(
                self.admin_app_assignment_service.assign_apps(
                    account_id,
                    app_ids,
                    operator_id=operator_id,
                    ip=ip,
                    user_agent=user_agent,
                )
            )
        )

    @admin_login_required
    @permission_required("app_assignment:update")
    def revoke_assignment(self, account_id: UUID, assignment_id: UUID):
        operator_id, ip, user_agent = _get_operator_context()
        resp = AppAssignmentResp()
        return success_json(
            resp.dump(
                self.admin_app_assignment_service.revoke_assignment(
                    account_id,
                    assignment_id,
                    operator_id=operator_id,
                    ip=ip,
                    user_agent=user_agent,
                )
            )
        )
