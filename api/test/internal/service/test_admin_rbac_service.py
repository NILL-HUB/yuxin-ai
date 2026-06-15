from types import SimpleNamespace
from uuid import uuid4

from internal.model.admin import Permission, Role, RolePermission
from internal.service.admin_rbac_service import AdminRbacService


class _QueryStub:
    def __init__(self, *, all_result=None, one_or_none_result=None):
        self._all_result = [] if all_result is None else all_result
        self._one_or_none_result = one_or_none_result
        self.filters = []
        self.deletes = 0

    def filter(self, *args, **kwargs):
        self.filters.append((args, kwargs))
        return self

    def join(self, *args, **kwargs):
        return self

    def all(self):
        return self._all_result

    def one_or_none(self):
        return self._one_or_none_result

    def delete(self):
        self.deletes += 1


class _SessionStub:
    def __init__(self, queries=None):
        self._queries = list(queries or [])
        self.added = []
        self.flushes = 0
        self.commits = 0
        self.deleted = []

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


class TestAdminRbacService:
    def test_default_permission_specs_should_match_rad_phase_one_permissions(self):
        codes = [item["code"] for item in AdminRbacService.DEFAULT_PERMISSIONS]

        assert codes == [
            "admin:access",
            "admin_user:read",
            "admin_user:create",
            "admin_user:update",
            "admin_user:disable",
            "role:read",
            "role:create",
            "role:update",
            "role:delete",
            "permission:read",
            "audit_log:read",
            "app:read",
            "app:update",
            "workflow:read",
            "workflow:update",
            "dataset:read",
            "dataset:update",
            "tool:read",
            "tool:update",
            "mcp:read",
            "mcp:update",
            "skill:read",
            "skill:update",
            "user:read",
            "user:update",
            "user:disable",
            "plan:read",
            "plan:update",
            "redeem_code:read",
            "redeem_code:update",
            "app_assignment:read",
            "app_assignment:update",
            "setting:read",
        ]

    def test_initialize_defaults_should_create_missing_permissions_roles_and_super_admin_bindings(self, monkeypatch):
        session = _SessionStub([
            _QueryStub(all_result=[]),
            _QueryStub(all_result=[]),
            _QueryStub(one_or_none_result=None),
        ])
        service = AdminRbacService(session=session)

        result = service.initialize_defaults()

        created_permissions = [item for item in session.added if isinstance(item, Permission)]
        created_roles = [item for item in session.added if isinstance(item, Role)]
        created_bindings = [item for item in session.added if isinstance(item, RolePermission)]

        assert len(created_permissions) == len(AdminRbacService.DEFAULT_PERMISSIONS)
        assert len(created_roles) == len(AdminRbacService.DEFAULT_ROLES)
        assert len(created_bindings) == len(AdminRbacService.DEFAULT_PERMISSIONS)
        assert result["permissions_created"] == len(AdminRbacService.DEFAULT_PERMISSIONS)
        assert result["roles_created"] == len(AdminRbacService.DEFAULT_ROLES)
        assert result["role_permissions_created"] == len(AdminRbacService.DEFAULT_PERMISSIONS)
        assert session.commits == 1

    def test_initialize_defaults_should_be_idempotent_when_everything_exists(self):
        existing_permissions = [
            Permission(id=uuid4(), code=item["code"], name=item["name"], resource=item["resource"], action=item["action"])
            for item in AdminRbacService.DEFAULT_PERMISSIONS
        ]
        existing_roles = [
            Role(id=uuid4(), code=item["code"], name=item["name"], is_system=True)
            for item in AdminRbacService.DEFAULT_ROLES
        ]
        super_admin = next(role for role in existing_roles if role.code == "super_admin")
        existing_bindings = [
            SimpleNamespace(permission_id=permission.id)
            for permission in existing_permissions
        ]
        session = _SessionStub([
            _QueryStub(all_result=existing_permissions),
            _QueryStub(all_result=existing_roles),
            _QueryStub(one_or_none_result=super_admin),
            _QueryStub(all_result=existing_bindings),
        ])
        service = AdminRbacService(session=session)

        result = service.initialize_defaults()

        assert session.added == []
        assert result == {
            "permissions_created": 0,
            "roles_created": 0,
            "role_permissions_created": 0,
        }
        assert session.commits == 1

    def test_create_role_should_record_audit_log_before_commit(self):
        operator_id = uuid4()
        permission_id = str(uuid4())
        audit_log_service = _AuditLogServiceStub()
        session = _SessionStub([
            _QueryStub(one_or_none_result=None),
            _QueryStub(),
            _QueryStub(all_result=[]),
        ])
        service = AdminRbacService(session=session, audit_log_service=audit_log_service)

        result = service.create_role(
            code="operator_custom",
            name="运营",
            description="运营角色",
            permission_ids=[permission_id],
            operator_id=operator_id,
            ip="127.0.0.1",
            user_agent="pytest",
        )

        assert result["code"] == "operator_custom"
        assert session.commits == 1
        assert audit_log_service.records == [{
            "admin_user_id": operator_id,
            "action": "create",
            "resource_type": "role",
            "resource_id": result["id"],
            "ip": "127.0.0.1",
            "user_agent": "pytest",
            "before_data": None,
            "after_data": {
                "code": "operator_custom",
                "name": "运营",
                "description": "运营角色",
                "permission_ids": [permission_id],
            },
        }]

    def test_update_role_should_record_before_and_after_audit_data(self):
        operator_id = uuid4()
        role_id = uuid4()
        old_permission_id = uuid4()
        new_permission_id = str(uuid4())
        role = Role(id=role_id, code="operator", name="旧名称", description="旧描述", is_system=False)
        audit_log_service = _AuditLogServiceStub()
        session = _SessionStub([
            _QueryStub(one_or_none_result=role),
            _QueryStub(all_result=[(old_permission_id,)]),
            _QueryStub(),
            _QueryStub(all_result=[]),
        ])
        service = AdminRbacService(session=session, audit_log_service=audit_log_service)

        result = service.update_role(
            role_id,
            name="新名称",
            description="新描述",
            permission_ids=[new_permission_id],
            operator_id=operator_id,
            ip="127.0.0.1",
            user_agent="pytest",
        )

        assert result["name"] == "新名称"
        assert session.commits == 1
        assert audit_log_service.records == [{
            "admin_user_id": operator_id,
            "action": "update",
            "resource_type": "role",
            "resource_id": str(role_id),
            "ip": "127.0.0.1",
            "user_agent": "pytest",
            "before_data": {
                "name": "旧名称",
                "description": "旧描述",
                "permission_ids": [str(old_permission_id)],
            },
            "after_data": {
                "name": "新名称",
                "description": "新描述",
                "permission_ids": [new_permission_id],
            },
        }]

    def test_delete_role_should_record_audit_log(self):
        operator_id = uuid4()
        role_id = uuid4()
        role = Role(id=role_id, code="operator", name="运营", description="运营角色", is_system=False)
        audit_log_service = _AuditLogServiceStub()
        session = _SessionStub([
            _QueryStub(one_or_none_result=role),
            _QueryStub(),
        ])
        service = AdminRbacService(session=session, audit_log_service=audit_log_service)

        service.delete_role(
            role_id,
            operator_id=operator_id,
            ip="127.0.0.1",
            user_agent="pytest",
        )

        assert session.deleted == [role]
        assert session.commits == 1
        assert audit_log_service.records == [{
            "admin_user_id": operator_id,
            "action": "delete",
            "resource_type": "role",
            "resource_id": str(role_id),
            "ip": "127.0.0.1",
            "user_agent": "pytest",
            "before_data": {"code": "operator", "name": "运营", "description": "运营角色"},
            "after_data": {},
        }]
