from dataclasses import dataclass
from uuid import UUID

from flask import g, request
from injector import inject

from internal.middleware import admin_login_required, permission_required
from internal.schema.admin_rbac_schema import CreateRoleReq, PermissionResp, RoleResp, UpdateRoleReq
from internal.service.admin_rbac_service import AdminRbacService
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
class AdminRbacHandler:
    admin_rbac_service: AdminRbacService

    @admin_login_required
    @permission_required("role:read")
    def list_roles(self):
        resp = RoleResp(many=True)
        return success_json(resp.dump(self.admin_rbac_service.list_roles()))

    @admin_login_required
    @permission_required("role:create")
    def create_role(self):
        req = CreateRoleReq()
        if not req.validate():
            return validate_error_json(req.errors)
        payload = request.get_json(silent=True) or {}
        operator_id, ip, user_agent = _get_operator_context()
        result = self.admin_rbac_service.create_role(
            code=req.code.data,
            name=req.name.data,
            description=req.description.data or "",
            permission_ids=payload.get("permission_ids", []) or [],
            operator_id=operator_id,
            ip=ip,
            user_agent=user_agent,
        )
        resp = RoleResp()
        return success_json(resp.dump(result))

    @admin_login_required
    @permission_required("role:read")
    def get_role(self, role_id: UUID):
        resp = RoleResp()
        return success_json(resp.dump(self.admin_rbac_service.get_role(role_id)))

    @admin_login_required
    @permission_required("role:update")
    def update_role(self, role_id: UUID):
        req = UpdateRoleReq()
        if not req.validate():
            return validate_error_json(req.errors)
        payload = request.get_json(silent=True) or {}
        operator_id, ip, user_agent = _get_operator_context()
        result = self.admin_rbac_service.update_role(
            role_id,
            name=req.name.data,
            description=req.description.data,
            permission_ids=payload.get("permission_ids") if "permission_ids" in payload else None,
            operator_id=operator_id,
            ip=ip,
            user_agent=user_agent,
        )
        resp = RoleResp()
        return success_json(resp.dump(result))

    @admin_login_required
    @permission_required("role:delete")
    def delete_role(self, role_id: UUID):
        operator_id, ip, user_agent = _get_operator_context()
        self.admin_rbac_service.delete_role(
            role_id,
            operator_id=operator_id,
            ip=ip,
            user_agent=user_agent,
        )
        return success_message("删除角色成功")

    @admin_login_required
    @permission_required("permission:read")
    def list_permissions(self):
        resp = PermissionResp(many=True)
        return success_json(resp.dump(self.admin_rbac_service.list_permissions()))
