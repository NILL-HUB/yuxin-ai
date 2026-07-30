from dataclasses import dataclass
from uuid import UUID

from flask import g, request
from injector import inject

from internal.middleware import admin_login_required, permission_required
from internal.schema.admin_user_schema import (
    AdminUserPageResp,
    AdminUserResp,
    CreateAdminUserReq,
    GetAdminUsersReq,
    ResetAdminUserPasswordReq,
    RevokeAdminUserSessionsResp,
    UpdateAdminUserReq,
)
from internal.service.admin_user_service import AdminUserService
from pkg.response import success_json, success_message, validate_error_json


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
class AdminUserHandler:
    admin_user_service: AdminUserService

    @admin_login_required
    @permission_required("admin_user:read")
    def list(self):
        req = GetAdminUsersReq(request.args)
        if not req.validate():
            return validate_error_json(req.errors)
        result = self.admin_user_service.list_admin_users(
            search=req.search.data,
            status=req.status.data,
            current_page=req.current_page.data,
            page_size=req.page_size.data,
        )
        resp = AdminUserPageResp()
        return success_json(resp.dump(result))

    @admin_login_required
    @permission_required("admin_user:create")
    def create(self):
        req = CreateAdminUserReq()
        if not req.validate():
            return validate_error_json(req.errors)
        payload = request.get_json(silent=True) or {}
        operator_id, ip, user_agent = _get_operator_context()
        result = self.admin_user_service.create_admin_user(
            email=req.email.data,
            name=req.name.data,
            password=req.password.data,
            role_ids=payload.get("role_ids", []) or [],
            operator_id=operator_id,
            ip=ip,
            user_agent=user_agent,
        )
        resp = AdminUserResp()
        return success_json(resp.dump(result))

    @admin_login_required
    @permission_required("admin_user:read")
    def get(self, admin_id: UUID):
        resp = AdminUserResp()
        return success_json(resp.dump(self.admin_user_service.get_admin_user(admin_id)))

    @admin_login_required
    @permission_required("admin_user:update")
    def update(self, admin_id: UUID):
        req = UpdateAdminUserReq()
        if not req.validate():
            return validate_error_json(req.errors)
        payload = request.get_json(silent=True) or {}
        operator_id, ip, user_agent = _get_operator_context()
        result = self.admin_user_service.update_admin_user(
            admin_id,
            name=req.name.data,
            email=req.email.data,
            status=req.status.data,
            role_ids=payload.get("role_ids") if "role_ids" in payload else None,
            operator_id=operator_id,
            ip=ip,
            user_agent=user_agent,
        )
        resp = AdminUserResp()
        return success_json(resp.dump(result))

    @admin_login_required
    @permission_required("admin_user:disable")
    def disable(self, admin_id: UUID):
        operator_id, ip, user_agent = _get_operator_context()
        self.admin_user_service.disable_admin_user(
            admin_id,
            operator_id=operator_id,
            ip=ip,
            user_agent=user_agent,
        )
        return success_message("禁用管理员成功")

    @admin_login_required
    @permission_required("admin_user:disable")
    def enable(self, admin_id: UUID):
        operator_id, ip, user_agent = _get_operator_context()
        result = self.admin_user_service.enable_admin_user(
            admin_id,
            operator_id=operator_id,
            ip=ip,
            user_agent=user_agent,
        )
        resp = AdminUserResp()
        return success_json(resp.dump(result))

    @admin_login_required
    @permission_required("admin_user:disable")
    def reset_password(self, admin_id: UUID):
        req = ResetAdminUserPasswordReq()
        if not req.validate():
            return validate_error_json(req.errors)
        operator_id, ip, user_agent = _get_operator_context()
        result = self.admin_user_service.reset_admin_user_password(
            admin_id,
            password=req.password.data,
            operator_id=operator_id,
            ip=ip,
            user_agent=user_agent,
        )
        resp = AdminUserResp()
        return success_json(resp.dump(result))

    @admin_login_required
    @permission_required("admin_user:disable")
    def revoke_sessions(self, admin_id: UUID):
        """撤销管理员所有活跃会话（踢下线）。"""
        operator_id, ip, user_agent = _get_operator_context()
        result = self.admin_user_service.revoke_admin_sessions(
            admin_id,
            operator_id=operator_id,
            ip=ip,
            user_agent=user_agent,
        )
        resp = RevokeAdminUserSessionsResp()
        return success_json(resp.dump(result))
