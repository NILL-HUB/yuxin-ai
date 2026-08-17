from types import SimpleNamespace
from uuid import uuid4

import pytest

from internal.core.rbac import (
    DEFAULT_ROLES,
    PERMISSION_CATALOG,
    SUPER_ADMIN_ROLE_CODE,
    all_permission_codes,
)
from internal.exception import FailException
from internal.model.admin import Permission, Role, RolePermission
from internal.service.admin_rbac_service import AdminRbacService


class _QueryStub:
    def __init__(self, *, all_result=None, one_or_none_result=None, count_result=0):
        self._all_result = [] if all_result is None else all_result
        self._one_or_none_result = one_or_none_result
        self._count_result = count_result
        self.deletes = 0

    def filter(self, *args, **kwargs):
        return self

    def join(self, *args, **kwargs):
        return self

    def all(self):
        return self._all_result

    def one_or_none(self):
        return self._one_or_none_result

    def count(self):
        return self._count_result

    def delete(self):
        self.deletes += 1


class _SessionStub:
    def __init__(self, queries=None):
        self._queries = list(queries or [])
        self.added = []
        self.deleted = []
        self.flushes = 0
        self.commits = 0

    def query(self, *_args, **_kwargs):
        if self._queries:
            return self._queries.pop(0)
        return _QueryStub()

    def add(self, obj):
        self.added.append(obj)

    def flush(self):
        self.flushes += 1
        for obj in self.added:
            if getattr(obj, "id", None) is None:
                obj.id = uuid4()

    def commit(self):
        self.commits += 1

    def delete(self, obj):
        self.deleted.append(obj)


class _AuditLogServiceStub:
    def __init__(self):
        self.records = []

    def record_for_write(self, **kwargs):
        self.records.append(kwargs)


def _catalog_permissions():
    return [
        Permission(
            id=uuid4(),
            code=spec.code,
            name=spec.name,
            resource=spec.resource,
            action=spec.action,
            description=spec.description,
        )
        for spec in PERMISSION_CATALOG
    ]


def _catalog_roles():
    return [
        Role(id=uuid4(), code=spec.code, name=spec.name, description=spec.description, is_system=True)
        for spec in DEFAULT_ROLES
    ]


class TestAdminRbacService:
    def test_permission_codes_are_readable_stable_and_unique(self):
        codes = [permission.code for permission in PERMISSION_CATALOG]

        assert len(codes) == len(set(codes))
        for code in codes:
            assert ":" in code
            assert code != str(uuid4())

    def test_initialize_defaults_should_create_missing_permissions_roles_and_grants(self):
        permissions = _catalog_permissions()
        roles = _catalog_roles()
        queries = [
            _QueryStub(all_result=[]),
            _QueryStub(all_result=[]),
            _QueryStub(all_result=permissions),
        ]
        for role in roles:
            queries.append(_QueryStub(one_or_none_result=role))
            queries.append(_QueryStub(all_result=[]))
        session = _SessionStub(queries)
        service = AdminRbacService(session=session)

        result = service.initialize_defaults()

        assert result["permissions_created"] == len(PERMISSION_CATALOG)
        assert result["roles_created"] == len(DEFAULT_ROLES)
        assert result["role_permissions_created"] > 0
        assert session.commits == 1

    def test_initialize_defaults_should_be_idempotent(self):
        permissions = _catalog_permissions()
        roles = _catalog_roles()
        permission_id_by_code = {permission.code: permission.id for permission in permissions}
        role_id_by_code = {role.code: role.id for role in roles}
        bindings = []
        for role in roles:
            codes = (
                list(all_permission_codes())
                if role.code == SUPER_ADMIN_ROLE_CODE
                else list(next(spec.permission_codes for spec in DEFAULT_ROLES if spec.code == role.code))
            )
            bindings.extend(
                SimpleNamespace(
                    role_id=role.id,
                    permission_id=permission_id_by_code[code],
                )
                for code in codes
            )
        queries = [
            _QueryStub(all_result=permissions),
            _QueryStub(all_result=roles),
            _QueryStub(all_result=permissions),
        ]
        for role in roles:
            queries.append(_QueryStub(one_or_none_result=role))
            queries.append(
                _QueryStub(
                    all_result=[
                        binding
                        for binding in bindings
                        if binding.role_id == role.id
                    ]
                )
            )
        session = _SessionStub(queries)
        service = AdminRbacService(session=session)

        result = service.initialize_defaults()

        assert result == {
            "permissions_created": 0,
            "roles_created": 0,
            "role_permissions_created": 0,
        }
        assert session.added == []
        assert session.commits == 1

    def test_create_role_should_accept_permission_codes_and_record_audit(self):
        operator_id = uuid4()
        permission = Permission(
            id=uuid4(),
            code="app:read",
            name="查看应用",
            resource="app",
            action="read",
        )
        session = _SessionStub([
            _QueryStub(one_or_none_result=None),
            _QueryStub(all_result=[permission]),
            _QueryStub(),
            _QueryStub(all_result=[("app:read",)]),
        ])
        audit_log_service = _AuditLogServiceStub()
        service = AdminRbacService(session=session, audit_log_service=audit_log_service)

        result = service.create_role(
            code="content_manager",
            name="内容管理员",
            description="内容运营",
            permission_codes=["app:read"],
            operator_id=operator_id,
            ip="127.0.0.1",
            user_agent="pytest",
        )

        assert result["code"] == "content_manager"
        assert result["permissions"] == ["app:read"]
        assert session.commits == 1
        assert audit_log_service.records == [{
            "admin_user_id": operator_id,
            "action": "create",
            "resource_type": "role",
            "resource_id": "content_manager",
            "ip": "127.0.0.1",
            "user_agent": "pytest",
            "before_data": None,
            "after_data": {
                "code": "content_manager",
                "name": "内容管理员",
                "description": "内容运营",
                "permission_codes": ["app:read"],
            },
        }]

    def test_create_role_should_reject_unknown_permission_code(self):
        session = _SessionStub([_QueryStub(one_or_none_result=None)])
        service = AdminRbacService(session=session)

        with pytest.raises(FailException) as exc_info:
            service.create_role(
                code="bad_role",
                name="坏角色",
                permission_codes=["not:exist"],
            )

        assert "权限编码不存在" in str(exc_info.value)

    def test_update_role_should_use_codes_in_audit(self):
        operator_id = uuid4()
        role_id = uuid4()
        role = Role(id=role_id, code="content_manager", name="旧名称", description="旧描述", is_system=False)
        new_permission = Permission(
            id=uuid4(),
            code="app:update",
            name="更新应用",
            resource="app",
            action="update",
        )
        session = _SessionStub([
            _QueryStub(one_or_none_result=role),
            _QueryStub(all_result=[("app:read",)]),
            _QueryStub(all_result=[new_permission]),
            _QueryStub(),
            _QueryStub(all_result=[("app:update",)]),
        ])
        audit_log_service = _AuditLogServiceStub()
        service = AdminRbacService(session=session, audit_log_service=audit_log_service)

        result = service.update_role(
            "content_manager",
            name="新名称",
            permission_codes=["app:update"],
            operator_id=operator_id,
            ip="127.0.0.1",
            user_agent="pytest",
        )

        assert result["name"] == "新名称"
        assert audit_log_service.records == [{
            "admin_user_id": operator_id,
            "action": "update",
            "resource_type": "role",
            "resource_id": "content_manager",
            "ip": "127.0.0.1",
            "user_agent": "pytest",
            "before_data": {
                "code": "content_manager",
                "name": "旧名称",
                "description": "旧描述",
                "permission_codes": ["app:read"],
            },
            "after_data": {
                "code": "content_manager",
                "name": "新名称",
                "description": "旧描述",
                "permission_codes": ["app:update"],
            },
        }]

    def test_system_role_cannot_be_updated_or_deleted(self):
        system_role = Role(id=uuid4(), code="super_admin", name="超级管理员", is_system=True)
        session = _SessionStub([_QueryStub(one_or_none_result=system_role)])
        service = AdminRbacService(session=session)

        with pytest.raises(FailException) as exc_info:
            service.update_role("super_admin", name="x")
        assert "系统角色不能修改" in str(exc_info.value)

        session2 = _SessionStub([_QueryStub(one_or_none_result=system_role)])
        service2 = AdminRbacService(session=session2)
        with pytest.raises(FailException) as exc_info:
            service2.delete_role("super_admin")
        assert "系统角色不能删除" in str(exc_info.value)

    def test_delete_role_should_reject_when_role_is_assigned(self):
        role = Role(id=uuid4(), code="content_manager", name="内容管理员", is_system=False)
        session = _SessionStub([
            _QueryStub(one_or_none_result=role),
            _QueryStub(count_result=1),
        ])
        service = AdminRbacService(session=session)

        with pytest.raises(FailException) as exc_info:
            service.delete_role("content_manager")

        assert "角色已分配给管理员" in str(exc_info.value)

    def test_delete_role_should_record_audit(self):
        operator_id = uuid4()
        role = Role(id=uuid4(), code="content_manager", name="内容管理员", description="desc", is_system=False)
        session = _SessionStub([
            _QueryStub(one_or_none_result=role),
            _QueryStub(count_result=0),
            _QueryStub(),
        ])
        audit_log_service = _AuditLogServiceStub()
        service = AdminRbacService(session=session, audit_log_service=audit_log_service)

        service.delete_role(
            "content_manager",
            operator_id=operator_id,
            ip="127.0.0.1",
            user_agent="pytest",
        )

        assert session.deleted == [role]
        assert audit_log_service.records == [{
            "admin_user_id": operator_id,
            "action": "delete",
            "resource_type": "role",
            "resource_id": "content_manager",
            "ip": "127.0.0.1",
            "user_agent": "pytest",
            "before_data": {
                "code": "content_manager",
                "name": "内容管理员",
                "description": "desc",
            },
            "after_data": {},
        }]
