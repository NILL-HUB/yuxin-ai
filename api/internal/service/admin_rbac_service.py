from __future__ import annotations

from uuid import UUID

from internal.exception import FailException, NotFoundException
from internal.extension.database_extension import db
from internal.model.admin import Permission, Role, RolePermission
from internal.service.audit_log_service import AuditLogService


class AdminRbacService:
    DEFAULT_PERMISSIONS = [
        {"code": "admin:access", "name": "访问管理后台", "resource": "admin", "action": "access", "description": "允许访问管理后台"},
        {"code": "admin_user:read", "name": "查看管理员", "resource": "admin_user", "action": "read", "description": "查看管理员账号"},
        {"code": "admin_user:create", "name": "创建管理员", "resource": "admin_user", "action": "create", "description": "创建管理员账号"},
        {"code": "admin_user:update", "name": "更新管理员", "resource": "admin_user", "action": "update", "description": "更新管理员账号"},
        {"code": "admin_user:disable", "name": "禁用管理员", "resource": "admin_user", "action": "disable", "description": "禁用管理员账号"},
        {"code": "role:read", "name": "查看角色", "resource": "role", "action": "read", "description": "查看角色"},
        {"code": "role:create", "name": "创建角色", "resource": "role", "action": "create", "description": "创建角色"},
        {"code": "role:update", "name": "更新角色", "resource": "role", "action": "update", "description": "更新角色"},
        {"code": "role:delete", "name": "删除角色", "resource": "role", "action": "delete", "description": "删除角色"},
        {"code": "permission:read", "name": "查看权限", "resource": "permission", "action": "read", "description": "查看权限点"},
        {"code": "audit_log:read", "name": "查看审计日志", "resource": "audit_log", "action": "read", "description": "查看审计日志"},
        {"code": "app:read", "name": "查看应用", "resource": "app", "action": "read", "description": "查看应用"},
        {"code": "app:update", "name": "更新应用", "resource": "app", "action": "update", "description": "更新应用"},
        {"code": "workflow:read", "name": "查看工作流", "resource": "workflow", "action": "read", "description": "查看工作流"},
        {"code": "workflow:update", "name": "更新工作流", "resource": "workflow", "action": "update", "description": "更新工作流"},
        {"code": "dataset:read", "name": "查看知识库", "resource": "dataset", "action": "read", "description": "查看知识库"},
        {"code": "dataset:update", "name": "更新知识库", "resource": "dataset", "action": "update", "description": "更新知识库"},
        {"code": "tool:read", "name": "查看工具", "resource": "tool", "action": "read", "description": "查看工具"},
        {"code": "tool:update", "name": "更新工具", "resource": "tool", "action": "update", "description": "更新工具"},
        {"code": "mcp:read", "name": "查看 MCP", "resource": "mcp", "action": "read", "description": "查看 MCP"},
        {"code": "mcp:update", "name": "更新 MCP", "resource": "mcp", "action": "update", "description": "更新 MCP"},
        {"code": "skill:read", "name": "查看技能", "resource": "skill", "action": "read", "description": "查看技能"},
        {"code": "skill:update", "name": "更新技能", "resource": "skill", "action": "update", "description": "更新技能"},
        {"code": "user:read", "name": "查看用户", "resource": "user", "action": "read", "description": "查看用户"},
        {"code": "user:update", "name": "更新用户", "resource": "user", "action": "update", "description": "更新用户状态和会话"},
        {"code": "user:disable", "name": "禁用用户", "resource": "user", "action": "disable", "description": "禁用用户账号"},
        {"code": "plan:read", "name": "查看套餐", "resource": "plan", "action": "read", "description": "查看套餐和权益配置"},
        {"code": "plan:update", "name": "管理套餐", "resource": "plan", "action": "update", "description": "创建、更新和启停套餐"},
        {"code": "redeem_code:read", "name": "查看卡密", "resource": "redeem_code", "action": "read", "description": "查看卡密批次和卡密状态"},
        {"code": "redeem_code:update", "name": "管理卡密", "resource": "redeem_code", "action": "update", "description": "生成和禁用卡密"},
        {"code": "app_assignment:read", "name": "查看应用分配", "resource": "app_assignment", "action": "read", "description": "查看用户已分配应用"},
        {"code": "app_assignment:update", "name": "管理应用分配", "resource": "app_assignment", "action": "update", "description": "分配和撤销用户应用"},
        {"code": "setting:read", "name": "查看设置", "resource": "setting", "action": "read", "description": "查看设置"},
        {"code": "orchestration_flag:read", "name": "查看调度开关", "resource": "orchestration_flag", "action": "read", "description": "查看调度平台发布开关"},
        {"code": "orchestration_flag:update", "name": "管理调度开关", "resource": "orchestration_flag", "action": "update", "description": "启停调度平台发布开关"},
        {"code": "orchestration_release:read", "name": "查看调度上线验收", "resource": "orchestration_release", "action": "read", "description": "查看调度平台上线验收报告"},
        {"code": "routing_quality:read", "name": "查看路由质量", "resource": "routing_quality", "action": "read", "description": "查看路由质量指标与调优建议"},
        {"code": "routing_quality:feedback", "name": "提交路由反馈", "resource": "routing_quality", "action": "feedback", "description": "提交路由质量反馈"},
        {"code": "routing_quality:accept", "name": "采纳调优建议", "resource": "routing_quality", "action": "accept", "description": "采纳半自动调优建议"},
        {"code": "routing_quality:dismiss", "name": "驳回调优建议", "resource": "routing_quality", "action": "dismiss", "description": "驳回不适用调优建议并记录原因"},
        {"code": "routing_quality:apply", "name": "应用策略变更", "resource": "routing_quality", "action": "apply", "description": "应用策略变更草稿到路由策略"},
        {"code": "routing_quality:rollback", "name": "回滚策略变更", "resource": "routing_quality", "action": "rollback", "description": "回滚已应用的策略变更"},
        {"code": "system_knowledge:read", "name": "查看系统知识库", "resource": "system_knowledge", "action": "read", "description": "查看系统级知识库"},
        {"code": "system_knowledge:write", "name": "管理系统知识库", "resource": "system_knowledge", "action": "write", "description": "创建、编辑、删除系统级知识库"},
    ]

    DEFAULT_ROLES = [
        {"code": "super_admin", "name": "超级管理员", "description": "拥有全部权限"},
        {"code": "operator", "name": "运营管理员", "description": "管理用户、应用、内容和基础运营"},
        {"code": "finance", "name": "财务管理员", "description": "管理订单、支付、退款和收入数据，第一阶段先预留"},
        {"code": "support", "name": "客服人员", "description": "查询用户和基础资料，第一阶段先预留"},
        {"code": "auditor", "name": "审核人员", "description": "审核 Agent、工作流、插件等，第一阶段先预留"},
        {"code": "viewer", "name": "只读观察员", "description": "只读查看后台数据"},
    ]

    def __init__(self, session=None, audit_log_service=None):
        self.session = session or db.session
        self.audit_log_service = audit_log_service or AuditLogService(session=self.session)

    def _emit_audit(
        self,
        *,
        operator_id,
        action: str,
        resource_type: str,
        resource_id: str = "",
        ip: str = "",
        user_agent: str = "",
        before_data: dict | None = None,
        after_data: dict | None = None,
    ) -> None:
        if not operator_id:
            return
        self.audit_log_service.record_for_write(
            admin_user_id=operator_id,
            action=action,
            resource_type=resource_type,
            resource_id=resource_id,
            ip=ip,
            user_agent=user_agent,
            before_data=before_data,
            after_data=after_data,
        )

    def initialize_defaults(self) -> dict[str, int]:
        self._permissions_by_code = {}
        self._roles_by_code = {}
        permissions_created = self._ensure_permissions()
        roles_created = self._ensure_roles()
        role_permissions_created = self._ensure_super_admin_permissions()
        self.session.commit()
        return {
            "permissions_created": permissions_created,
            "roles_created": roles_created,
            "role_permissions_created": role_permissions_created,
        }

    def _ensure_permissions(self) -> int:
        existing_permissions = self.session.query(Permission).all()
        self._permissions_by_code = {permission.code: permission for permission in existing_permissions}
        created = 0
        for item in self.DEFAULT_PERMISSIONS:
            if item["code"] in self._permissions_by_code:
                continue
            permission = Permission(**item)
            self.session.add(permission)
            self._permissions_by_code[item["code"]] = permission
            created += 1
        if created:
            self.session.flush()
        return created

    def _ensure_roles(self) -> int:
        existing_roles = self.session.query(Role).all()
        self._roles_by_code = {role.code: role for role in existing_roles}
        created = 0
        for item in self.DEFAULT_ROLES:
            if item["code"] in self._roles_by_code:
                continue
            role = Role(is_system=True, **item)
            self.session.add(role)
            self._roles_by_code[item["code"]] = role
            created += 1
        if created:
            self.session.flush()
        return created

    def _ensure_super_admin_permissions(self) -> int:
        super_admin = self.session.query(Role).filter(Role.code == "super_admin").one_or_none()
        if super_admin is None:
            super_admin = self._roles_by_code.get("super_admin")
        if super_admin is None:
            super_admin = Role(code="super_admin", name="超级管理员", description="拥有全部权限", is_system=True)
            self.session.add(super_admin)
            self.session.flush()
        permissions = list(self._permissions_by_code.values())
        existing_bindings = self.session.query(RolePermission).filter(RolePermission.role_id == super_admin.id).all()
        existing_permission_ids = {binding.permission_id for binding in existing_bindings}
        created = 0
        for permission in permissions:
            if permission.id in existing_permission_ids:
                continue
            self.session.add(RolePermission(role_id=super_admin.id, permission_id=permission.id))
            created += 1
        if created:
            self.session.flush()
        return created

    def list_roles(self) -> list[dict[str, object]]:
        roles = self.session.query(Role).order_by(Role.created_at.asc()).all()
        return [self._serialize_role(role) for role in roles]

    def get_role(self, role_id: UUID) -> dict[str, object]:
        role = self.session.query(Role).filter(Role.id == role_id).one_or_none()
        if role is None:
            raise NotFoundException("角色不存在")
        return self._serialize_role(role)

    def create_role(
        self,
        *,
        code: str,
        name: str,
        description: str = "",
        permission_ids: list[str] | None = None,
        operator_id=None,
        ip: str = "",
        user_agent: str = "",
    ) -> dict[str, object]:
        existing_role = self.session.query(Role).filter(Role.code == code).one_or_none()
        if existing_role is not None:
            raise FailException("角色编码已存在")
        role = Role(code=code, name=name, description=description, is_system=False)
        self.session.add(role)
        self.session.flush()
        self._replace_role_permissions(role.id, permission_ids or [])
        serialized = self._serialize_role(role)
        self._emit_audit(
            operator_id=operator_id,
            action="create",
            resource_type="role",
            resource_id=str(role.id),
            ip=ip,
            user_agent=user_agent,
            after_data={"code": code, "name": name, "description": description, "permission_ids": [str(pid) for pid in permission_ids or []]},
        )
        self.session.commit()
        return serialized

    def update_role(
        self,
        role_id: UUID,
        *,
        name: str | None = None,
        description: str | None = None,
        permission_ids: list[str] | None = None,
        operator_id=None,
        ip: str = "",
        user_agent: str = "",
    ) -> dict[str, object]:
        role = self.session.query(Role).filter(Role.id == role_id).one_or_none()
        if role is None:
            raise NotFoundException("角色不存在")
        before_data = {
            "name": role.name,
            "description": role.description,
            "permission_ids": self._get_role_permission_ids(role.id),
        }
        if name is not None:
            role.name = name
        if description is not None:
            role.description = description
        if permission_ids is not None:
            self._replace_role_permissions(role.id, permission_ids)
        serialized = self._serialize_role(role)
        self._emit_audit(
            operator_id=operator_id,
            action="update",
            resource_type="role",
            resource_id=str(role.id),
            ip=ip,
            user_agent=user_agent,
            before_data=before_data,
            after_data={
                "name": serialized.get("name"),
                "description": serialized.get("description"),
                "permission_ids": [str(pid) for pid in permission_ids] if permission_ids is not None else before_data["permission_ids"],
            },
        )
        self.session.commit()
        return serialized

    def delete_role(
        self,
        role_id: UUID,
        *,
        operator_id=None,
        ip: str = "",
        user_agent: str = "",
    ) -> None:
        role = self.session.query(Role).filter(Role.id == role_id).one_or_none()
        if role is None:
            raise NotFoundException("角色不存在")
        if role.is_system:
            raise FailException("系统角色不能删除")
        before_data = {
            "code": role.code,
            "name": role.name,
            "description": role.description,
        }
        self.session.query(RolePermission).filter(RolePermission.role_id == role_id).delete()
        self.session.delete(role)
        self._emit_audit(
            operator_id=operator_id,
            action="delete",
            resource_type="role",
            resource_id=str(role.id),
            ip=ip,
            user_agent=user_agent,
            before_data=before_data,
            after_data={},
        )
        self.session.commit()

    def list_permissions(self) -> list[dict[str, object]]:
        permissions = self.session.query(Permission).order_by(Permission.resource.asc(), Permission.action.asc()).all()
        return [self._serialize_permission(permission) for permission in permissions]

    def _replace_role_permissions(self, role_id, permission_ids: list[str]) -> None:
        self.session.query(RolePermission).filter(RolePermission.role_id == role_id).delete()
        for permission_id in permission_ids:
            self.session.add(RolePermission(role_id=role_id, permission_id=permission_id))

    def _serialize_role(self, role: Role) -> dict[str, object]:
        return {
            "id": str(role.id),
            "code": role.code,
            "name": role.name,
            "description": role.description,
            "is_system": role.is_system,
            "permissions": self._get_role_permission_codes(role.id),
        }

    def _serialize_permission(self, permission: Permission) -> dict[str, object]:
        return {
            "id": str(permission.id),
            "code": permission.code,
            "name": permission.name,
            "resource": permission.resource,
            "action": permission.action,
        }

    def _get_role_permission_codes(self, role_id) -> list[str]:
        rows = (
            self.session.query(Permission.code)
            .join(RolePermission, RolePermission.permission_id == Permission.id)
            .filter(RolePermission.role_id == role_id)
            .all()
        )
        return sorted(row[0] for row in rows)

    def _get_role_permission_ids(self, role_id) -> list[str]:
        rows = (
            self.session.query(RolePermission.permission_id)
            .filter(RolePermission.role_id == role_id)
            .all()
        )
        return [str(row[0]) for row in rows]
