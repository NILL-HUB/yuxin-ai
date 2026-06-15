from dataclasses import dataclass
from uuid import UUID

from flask import g, request
from injector import inject

from internal.middleware import admin_login_required, permission_required
from internal.schema.admin_billing_plan_schema import (
    AdminPlanPageResp,
    AdminPlanResp,
    GetAdminPlansReq,
    SetAdminPlanStatusReq,
    UpsertAdminPlanReq,
)
from internal.service.admin_billing_plan_service import AdminBillingPlanService
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
class AdminBillingPlanHandler:
    admin_billing_plan_service: AdminBillingPlanService

    @admin_login_required
    @permission_required("plan:read")
    def list(self):
        req = GetAdminPlansReq(request.args)
        if not req.validate():
            return validate_error_json(req.errors)
        result = self.admin_billing_plan_service.list_plans(
            keyword=req.keyword.data,
            status=req.status.data,
            current_page=req.current_page.data,
            page_size=req.page_size.data,
        )
        resp = AdminPlanPageResp()
        return success_json(resp.dump(result))

    @admin_login_required
    @permission_required("plan:read")
    def get(self, plan_id: UUID):
        resp = AdminPlanResp()
        return success_json(resp.dump(self.admin_billing_plan_service.get_plan(plan_id)))

    @admin_login_required
    @permission_required("plan:update")
    def create(self):
        payload = request.get_json(silent=True) or {}
        operator_id, ip, user_agent = _get_operator_context()
        result = self.admin_billing_plan_service.create_plan(payload, operator_id=operator_id, ip=ip, user_agent=user_agent)
        resp = AdminPlanResp()
        return success_json(resp.dump(result))

    @admin_login_required
    @permission_required("plan:update")
    def update(self, plan_id: UUID):
        payload = request.get_json(silent=True) or {}
        operator_id, ip, user_agent = _get_operator_context()
        result = self.admin_billing_plan_service.update_plan(plan_id, payload, operator_id=operator_id, ip=ip, user_agent=user_agent)
        resp = AdminPlanResp()
        return success_json(resp.dump(result))

    @admin_login_required
    @permission_required("plan:update")
    def set_status(self, plan_id: UUID):
        req = SetAdminPlanStatusReq()
        if not req.validate():
            return validate_error_json(req.errors)
        operator_id, ip, user_agent = _get_operator_context()
        result = self.admin_billing_plan_service.set_plan_status(
            plan_id,
            req.status.data,
            operator_id=operator_id,
            ip=ip,
            user_agent=user_agent,
        )
        resp = AdminPlanResp()
        return success_json(resp.dump(result))
