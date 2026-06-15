from dataclasses import dataclass
from uuid import UUID

from flask import g, request
from injector import inject

from internal.middleware import admin_login_required, permission_required
from internal.schema.admin_customer_user_schema import (
    AdminCustomerUserPageResp,
    AdminCustomerUserResp,
    DisableAdminCustomerUserReq,
    GetAdminCustomerUsersReq,
    RevokeCustomerUserSessionsResp,
)
from internal.service.admin_customer_user_service import AdminCustomerUserService
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
class AdminCustomerUserHandler:
    admin_customer_user_service: AdminCustomerUserService

    @admin_login_required
    @permission_required("user:read")
    def list(self):
        req = GetAdminCustomerUsersReq(request.args)
        if not req.validate():
            return validate_error_json(req.errors)
        result = self.admin_customer_user_service.list_customer_users(
            keyword=req.keyword.data,
            status=req.status.data,
            current_page=req.current_page.data,
            page_size=req.page_size.data,
        )
        resp = AdminCustomerUserPageResp()
        return success_json(resp.dump(result))

    @admin_login_required
    @permission_required("user:read")
    def get(self, account_id: UUID):
        resp = AdminCustomerUserResp()
        return success_json(resp.dump(self.admin_customer_user_service.get_customer_user(account_id)))

    @admin_login_required
    @permission_required("user:disable")
    def disable(self, account_id: UUID):
        req = DisableAdminCustomerUserReq()
        if not req.validate():
            return validate_error_json(req.errors)
        operator_id, ip, user_agent = _get_operator_context()
        result = self.admin_customer_user_service.disable_customer_user(
            account_id,
            reason=req.reason.data,
            operator_id=operator_id,
            ip=ip,
            user_agent=user_agent,
        )
        resp = AdminCustomerUserResp()
        return success_json(resp.dump(result))

    @admin_login_required
    @permission_required("user:update")
    def enable(self, account_id: UUID):
        operator_id, ip, user_agent = _get_operator_context()
        result = self.admin_customer_user_service.enable_customer_user(
            account_id,
            operator_id=operator_id,
            ip=ip,
            user_agent=user_agent,
        )
        resp = AdminCustomerUserResp()
        return success_json(resp.dump(result))

    @admin_login_required
    @permission_required("user:update")
    def revoke_sessions(self, account_id: UUID):
        operator_id, ip, user_agent = _get_operator_context()
        result = self.admin_customer_user_service.revoke_customer_user_sessions(
            account_id,
            operator_id=operator_id,
            ip=ip,
            user_agent=user_agent,
        )
        resp = RevokeCustomerUserSessionsResp()
        return success_json(resp.dump(result))
