from __future__ import annotations

import re

from internal.core.rbac import (
    DEFAULT_ROLES,
    DEFAULT_ROLE_BY_CODE,
    PERMISSION_BY_CODE,
    PERMISSION_CATALOG,
    SUPER_ADMIN_ROLE_CODE,
    all_permission_codes,
)
from internal.exception import FailException, NotFoundException
from internal.extension.database_extension import db
from internal.model.admin import AdminUserRole, Permission, Role, RolePermission
from internal.service.audit_log_service import AuditLogService


_ROLE_CODE_PATTERN = re.compile(r"^[a-z][a-z0-9_]{1,63}$")


class AdminRbacService:
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
        permissions_created = self._ensure_permissions()
        roles_created = self._ensure_roles()
        role_permissions_created = self._ensure_default_role_permissions()
        self.session.commit()
        return {
            "permissions_created": permissions_created,
            "roles_created": roles_created,
            "role_permissions_created": role_permissions_created,
        }

    def _ensure_permissions(self) -> int:
        existing_permissions = self.session.query(Permission).all()
        existing_by_code = {permission.code: permission for permission in existing_permissions}
        created = 0
        for spec in PERMISSION_CATALOG:
            permission = existing_by_code.get(spec.code)
            if permission is None:
                permission = Permission(
                    code=spec.code,
                    name=spec.name,
                    resource=spec.resource,
                    action=spec.action,
                    description=spec.description,
                )
                self.session.add(permission)
                existing_by_code[spec.code] = permission
                created += 1
                continue
            permission.name = spec.name
            permission.resource = spec.resource
            permission.action = spec.action
            permission.description = spec.description
        if created:
            self.session.flush()
        return created

    def _ensure_roles(self) -> int:
        existing_roles = self.session.query(Role).all()
        existing_by_code = {role.code: role for role in existing_roles}
        created = 0
        for spec in DEFAULT_ROLES:
            role = existing_by_code.get(spec.code)
            if role is None:
                role = Role(
                    code=spec.code,
                    name=spec.name,
                    description=spec.description,
                    is_system=True,
                )
                self.session.add(role)
                existing_by_code[spec.code] = role
                created += 1
                continue
            role.name = spec.name
            role.description = spec.description
            role.is_system = True
        if created:
            self.session.flush()
        return created

    def _ensure_default_role_permissions(self) -> int:
        permissions = self.session.query(Permission).all()
        permission_id_by_code = {permission.code: permission.id for permission in permissions}
        created = 0
        for spec in DEFAULT_ROLES:
            role = self.session.query(Role).filter(Role.code == spec.code).one_or_none()
            if role is None:
                continue
            target_codes = (
                all_permission_codes()
                if spec.code == SUPER_ADMIN_ROLE_CODE
                else spec.permission_codes
            )
            target_ids = {permission_id_by_code[code] for code in target_codes if code in permission_id_by_code}
            existing_bindings = (
                self.session.query(RolePermission)
                .filter(RolePermission.role_id == role.id)
                .all()
            )
            existing_ids = {binding.permission_id for binding in existing_bindings}
            for permission_id in sorted(target_ids, key=str):
                if permission_id in existing_ids:
                    continue
                self.session.add(RolePermission(role_id=role.id, permission_id=permission_id))
                created += 1
        if created:
            self.session.flush()
        return created

    def list_roles(self) -> list[dict[str, object]]:
        roles = self.session.query(Role).order_by(Role.created_at.asc()).all()
        return [self._serialize_role(role) for role in roles]

    def get_role(self, role_code: str) -> dict[str, object]:
        role = self.session.query(Role).filter(Role.code == role_code).one_or_none()
        if role is None:
            raise NotFoundException("角色不存在")
        return self._serialize_role(role)

    def create_role(
        self,
        *,
        code: str,
        name: str,
        description: str = "",
        permission_codes: list[str] | None = None,
        operator_id=None,
        ip: str = "",
        user_agent: str = "",
    ) -> dict[str, object]:
        code = (code or "").strip()
        if not _ROLE_CODE_PATTERN.fullmatch(code):
            raise FailException("角色编码格式错误")
        if code in DEFAULT_ROLE_BY_CODE:
            raise FailException("系统角色编码不允许创建自定义角色")
        existing_role = self.session.query(Role).filter(Role.code == code).one_or_none()
        if existing_role is not None:
            raise FailException("角色编码已存在")
        permission_codes = self._normalize_permission_codes(permission_codes or [])
        role = Role(code=code, name=name, description=description, is_system=False)
        self.session.add(role)
        self.session.flush()
        self._replace_role_permissions(role.id, permission_codes)
        serialized = self._serialize_role(role)
        self._emit_audit(
            operator_id=operator_id,
            action="create",
            resource_type="role",
            resource_id=code,
            ip=ip,
            user_agent=user_agent,
            after_data={
                "code": code,
                "name": name,
                "description": description,
                "permission_codes": permission_codes,
            },
        )
        self.session.commit()
        return serialized

    def update_role(
        self,
        role_code: str,
        *,
        name: str | None = None,
        description: str | None = None,
        permission_codes: list[str] | None = None,
        operator_id=None,
        ip: str = "",
        user_agent: str = "",
    ) -> dict[str, object]:
        role = self.session.query(Role).filter(Role.code == role_code).one_or_none()
        if role is None:
            raise NotFoundException("角色不存在")
        if role.is_system:
            raise FailException("系统角色不能修改")
        before_data = {
            "code": role.code,
            "name": role.name,
            "description": role.description,
            "permission_codes": self._get_role_permission_codes(role.id),
        }
        if name is not None:
            role.name = name
        if description is not None:
            role.description = description
        if permission_codes is not None:
            permission_codes = self._normalize_permission_codes(permission_codes)
            self._replace_role_permissions(role.id, permission_codes)
        serialized = self._serialize_role(role)
        after_data = {
            "code": role.code,
            "name": serialized.get("name"),
            "description": serialized.get("description"),
            "permission_codes": (
                permission_codes
                if permission_codes is not None
                else before_data["permission_codes"]
            ),
        }
        self._emit_audit(
            operator_id=operator_id,
            action="update",
            resource_type="role",
            resource_id=role_code,
            ip=ip,
            user_agent=user_agent,
            before_data=before_data,
            after_data=after_data,
        )
        self.session.commit()
        return serialized

    def delete_role(
        self,
        role_code: str,
        *,
        operator_id=None,
        ip: str = "",
        user_agent: str = "",
    ) -> None:
        role = self.session.query(Role).filter(Role.code == role_code).one_or_none()
        if role is None:
            raise NotFoundException("角色不存在")
        if role.is_system:
            raise FailException("系统角色不能删除")
        assigned_count = (
            self.session.query(AdminUserRole)
            .filter(AdminUserRole.role_id == role.id)
            .count()
        )
        if assigned_count:
            raise FailException("角色已分配给管理员，不能删除")
        before_data = {
            "code": role.code,
            "name": role.name,
            "description": role.description,
        }
        self.session.query(RolePermission).filter(RolePermission.role_id == role.id).delete()
        self.session.delete(role)
        self._emit_audit(
            operator_id=operator_id,
            action="delete",
            resource_type="role",
            resource_id=role_code,
            ip=ip,
            user_agent=user_agent,
            before_data=before_data,
            after_data={},
        )
        self.session.commit()

    def list_permissions(self) -> list[dict[str, object]]:
        permissions = self.session.query(Permission).order_by(
            Permission.resource.asc(),
            Permission.action.asc(),
        ).all()
        return [self._serialize_permission(permission) for permission in permissions]

    def _normalize_permission_codes(self, permission_codes: list[str]) -> list[str]:
        normalized = [str(code).strip() for code in permission_codes if str(code).strip()]
        if len(normalized) != len(set(normalized)):
            raise FailException("权限编码不能重复")
        unknown = [code for code in normalized if code not in PERMISSION_BY_CODE]
        if unknown:
            raise FailException(f"权限编码不存在: {', '.join(unknown)}")
        return normalized

    def _replace_role_permissions(self, role_id, permission_codes: list[str]) -> None:
        codes = self._normalize_permission_codes(permission_codes)
        permissions = self.session.query(Permission).filter(Permission.code.in_(codes)).all()
        permission_id_by_code = {permission.code: permission.id for permission in permissions}
        missing = [code for code in codes if code not in permission_id_by_code]
        if missing:
            raise FailException(f"权限编码不存在: {', '.join(missing)}")
        self.session.query(RolePermission).filter(RolePermission.role_id == role_id).delete()
        for code in codes:
            self.session.add(
                RolePermission(role_id=role_id, permission_id=permission_id_by_code[code])
            )

    def _serialize_role(self, role: Role) -> dict[str, object]:
        return {
            "code": role.code,
            "name": role.name,
            "description": role.description,
            "is_system": role.is_system,
            "permissions": self._get_role_permission_codes(role.id),
        }

    def _serialize_permission(self, permission: Permission) -> dict[str, object]:
        return {
            "code": permission.code,
            "name": permission.name,
            "resource": permission.resource,
            "action": permission.action,
            "description": permission.description,
        }

    def _get_role_permission_codes(self, role_id) -> list[str]:
        rows = (
            self.session.query(Permission.code)
            .join(RolePermission, RolePermission.permission_id == Permission.id)
            .filter(RolePermission.role_id == role_id)
            .all()
        )
        return sorted(row[0] for row in rows)
