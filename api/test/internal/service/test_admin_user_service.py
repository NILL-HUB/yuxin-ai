import base64
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from test.context import TestApp

from internal.exception import FailException, UnauthorizedException
from internal.model.account import Account, AccountSession
from internal.model.admin import AdminSession, AdminUser, AdminUserRole, Role
from internal.service.admin_user_service import AdminUserService
from pkg.password import compare_password, hash_password


class _QueryStub:
    def __init__(self, *, one_or_none_result=None, all_result=None, count_result=0):
        self._one_or_none_result = one_or_none_result
        self._all_result = [] if all_result is None else all_result
        self._count_result = count_result
        self.filters = []
        self.deletes = 0

    def filter(self, *args, **kwargs):
        self.filters.append((args, kwargs))
        return self

    def join(self, *args, **kwargs):
        return self

    def one_or_none(self):
        return self._one_or_none_result

    def all(self):
        return self._all_result

    def count(self):
        return self._count_result

    def delete(self):
        self.deletes += 1


class _SessionStub:
    def __init__(self, queries=None):
        self._queries = list(queries or [])
        self.added = []
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


class _AuditLogServiceStub:
    def __init__(self):
        self.records = []

    def record_for_write(self, **kwargs):
        self.records.append(kwargs)


def _hashed_password(password: str):
    salt = b"\x01" * 16
    return base64.b64encode(hash_password(password, salt)).decode(), base64.b64encode(salt).decode()


class TestAdminUserService:
    def test_initialize_super_admin_should_skip_when_env_is_missing(self, monkeypatch):
        monkeypatch.delenv("ADMIN_INITIAL_EMAIL", raising=False)
        monkeypatch.delenv("ADMIN_INITIAL_PASSWORD", raising=False)
        monkeypatch.delenv("ADMIN_INITIAL_NAME", raising=False)
        session = _SessionStub()
        service = AdminUserService(session=session)

        result = service.initialize_super_admin_from_env()

        assert result == {"created": False, "reason": "missing_env"}
        assert session.added == []
        assert session.commits == 0

    def test_initialize_super_admin_should_create_user_and_bind_super_admin_role(self, monkeypatch):
        monkeypatch.setenv("ADMIN_INITIAL_EMAIL", "")
        monkeypatch.setenv("ADMIN_INITIAL_USERNAME", "admin")
        monkeypatch.setenv("ADMIN_INITIAL_PASSWORD", "Root123456")
        monkeypatch.setenv("ADMIN_INITIAL_NAME", "Root")
        super_admin_role = Role(id=uuid4(), code="super_admin", name="超级管理员", is_system=True)
        session = _SessionStub([
            _QueryStub(one_or_none_result=None),
            _QueryStub(one_or_none_result=super_admin_role),
        ])
        service = AdminUserService(session=session)

        result = service.initialize_super_admin_from_env()

        created_users = [item for item in session.added if isinstance(item, AdminUser)]
        created_bindings = [item for item in session.added if isinstance(item, AdminUserRole)]
        created_accounts = [item for item in session.added if isinstance(item, Account)]
        assert result == {"created": True, "reason": "created"}
        assert len(created_users) == 1
        assert created_users[0].username == "admin"
        assert created_users[0].email == ""
        assert created_users[0].name == "Root"
        assert created_users[0].status == "active"
        assert created_users[0].account_id is None
        assert created_users[0].password != "Root123456"
        assert created_users[0].password_salt != ""
        assert compare_password("Root123456", created_users[0].password, created_users[0].password_salt) is True
        assert len(created_bindings) == 1
        assert created_bindings[0].admin_user_id == created_users[0].id
        assert created_bindings[0].role_id == super_admin_role.id
        # 完全解耦：初始化超级管理员不再创建/复用用户端账号
        assert len(created_accounts) == 0
        assert session.commits == 1

    def test_initialize_super_admin_should_skip_existing_user(self, monkeypatch):
        monkeypatch.setenv("ADMIN_INITIAL_EMAIL", "root@example.com")
        monkeypatch.setenv("ADMIN_INITIAL_PASSWORD", "Root123456")
        existing_user = AdminUser(id=uuid4(), email="root@example.com", name="Root", status="active")
        session = _SessionStub([_QueryStub(one_or_none_result=existing_user)])
        service = AdminUserService(session=session)

        result = service.initialize_super_admin_from_env()

        assert result == {"created": False, "reason": "exists"}
        assert session.added == []
        assert session.commits == 0

    def test_initialize_super_admin_should_reject_invalid_initial_password(self, monkeypatch):
        monkeypatch.setenv("ADMIN_INITIAL_EMAIL", "root@example.com")
        monkeypatch.setenv("ADMIN_INITIAL_PASSWORD", "weak")
        session = _SessionStub([_QueryStub(one_or_none_result=None)])
        service = AdminUserService(session=session)

        result = service.initialize_super_admin_from_env()

        assert result == {"created": False, "reason": "invalid_password"}
        assert session.added == []
        assert session.commits == 0

    def test_password_login_should_issue_admin_token_without_password_fields(self, monkeypatch):
        monkeypatch.setenv("JWT_SECRET_KEY", "test-secret-key-with-32-bytes-min-123456")
        admin_user_id = uuid4()
        password, salt = _hashed_password("Root123456")
        admin_user = AdminUser(
            id=admin_user_id,
            username="admin",
            email="",
            name="Root",
            password=password,
            password_salt=salt,
            status="active",
        )
        session = _SessionStub([
            _QueryStub(one_or_none_result=admin_user),
            _QueryStub(all_result=[("super_admin",)]),
            _QueryStub(all_result=[("admin:access",), ("account:read",)]),
        ])
        service = AdminUserService(session=session)

        app = TestApp(__name__)
        with app.test_request_context("/"):
            result = service.password_login("ADMIN", "Root123456")

        created_sessions = [item for item in session.added if isinstance(item, AdminSession)]
        created_account_sessions = [item for item in session.added if isinstance(item, AccountSession)]
        assert result["access_token"]
        assert result["admin_access_token"] == result["access_token"]
        assert result["expire_at"] > 0
        assert "user_access_token" not in result
        assert "user_expire_at" not in result
        assert "user" not in result
        admin_user_serialized = result["admin_user"]
        assert admin_user_serialized["id"] == str(admin_user_id)
        assert admin_user_serialized["username"] == "admin"
        assert admin_user_serialized["email"] == ""
        assert admin_user_serialized["name"] == "Root"
        assert admin_user_serialized["status"] == "active"
        # 完全解耦：管理员不再绑定用户端账号
        assert admin_user_serialized["account_id"] is None
        assert admin_user_serialized["last_login_at"] > 0
        assert admin_user_serialized["roles"] == ["super_admin"]
        assert admin_user_serialized["permissions"] == ["account:read", "admin:access"]
        assert "password" not in result["admin_user"]
        assert "password_salt" not in result["admin_user"]
        assert len(created_sessions) == 1
        # 完全解耦：管理员登录不再创建用户端会话
        assert len(created_account_sessions) == 0
        assert created_sessions[0].admin_user_id == admin_user_id
        assert session.commits == 1
        payload = service.parse_admin_token(result["access_token"])
        assert payload["sub"] == str(admin_user_id)
        assert payload["realm"] == "admin"
        assert payload["session_id"] == str(created_sessions[0].id)

    def test_password_login_should_reject_wrong_password(self, monkeypatch):
        monkeypatch.setenv("JWT_SECRET_KEY", "test-secret-key-with-32-bytes-min-123456")
        password, salt = _hashed_password("Root123456")
        admin_user = AdminUser(
            id=uuid4(),
            email="root@example.com",
            name="Root",
            password=password,
            password_salt=salt,
            status="active",
        )
        session = _SessionStub([_QueryStub(one_or_none_result=admin_user)])
        service = AdminUserService(session=session)

        with pytest.raises(FailException) as exc_info:
            service.password_login("root@example.com", "Wrong123456")

        assert "账号不存在或者密码错误" in str(exc_info.value)
        assert session.added == []
        assert session.commits == 0

    def test_password_login_should_reject_disabled_admin(self, monkeypatch):
        monkeypatch.setenv("JWT_SECRET_KEY", "test-secret-key-with-32-bytes-min-123456")
        password, salt = _hashed_password("Root123456")
        admin_user = AdminUser(
            id=uuid4(),
            email="root@example.com",
            name="Root",
            password=password,
            password_salt=salt,
            status="disabled",
        )
        session = _SessionStub([_QueryStub(one_or_none_result=admin_user)])
        service = AdminUserService(session=session)

        with pytest.raises(FailException) as exc_info:
            service.password_login("root@example.com", "Root123456")

        assert "管理员账号已被禁用" in str(exc_info.value)
        assert session.added == []
        assert session.commits == 0

    def test_change_own_password_should_verify_current_password_and_update_hash(self):
        admin_user_id = uuid4()
        password, salt = _hashed_password("Root123456")
        admin_user = AdminUser(
            id=admin_user_id,
            username="admin",
            email="",
            name="Root",
            password=password,
            password_salt=salt,
            status="active",
        )
        session = _SessionStub([_QueryStub(one_or_none_result=admin_user)])
        service = AdminUserService(session=session)

        result = service.change_own_password(
            admin_user_id,
            current_password="Root123456",
            new_password="New_123456",
        )

        assert result["username"] == "admin"
        assert compare_password("New_123456", admin_user.password, admin_user.password_salt) is True
        assert session.commits == 1

    def test_change_own_password_should_reject_wrong_current_password(self):
        admin_user_id = uuid4()
        password, salt = _hashed_password("Root123456")
        admin_user = AdminUser(
            id=admin_user_id,
            username="admin",
            email="",
            name="Root",
            password=password,
            password_salt=salt,
            status="active",
        )
        session = _SessionStub([_QueryStub(one_or_none_result=admin_user)])
        service = AdminUserService(session=session)

        with pytest.raises(FailException) as exc_info:
            service.change_own_password(
                admin_user_id,
                current_password="Wrong123456",
                new_password="New_123456",
            )

        assert "当前密码错误" in str(exc_info.value)
        assert compare_password("Root123456", admin_user.password, admin_user.password_salt) is True
        assert session.commits == 0

    def test_parse_admin_token_should_reject_expired_or_non_admin_token(self, monkeypatch):
        monkeypatch.setenv("JWT_SECRET_KEY", "test-secret-key-with-32-bytes-min-123456")
        service = AdminUserService(session=_SessionStub())
        expired_token = service.jwt_service.generate_token({
            "sub": str(uuid4()),
            "realm": "admin",
            "session_id": str(uuid4()),
            "exp": datetime.now(UTC) - timedelta(minutes=1),
        })
        customer_token = service.jwt_service.generate_token({
            "sub": str(uuid4()),
            "realm": "customer",
            "session_id": str(uuid4()),
            "exp": datetime.now(UTC) + timedelta(minutes=1),
        })

        with pytest.raises(UnauthorizedException):
            service.parse_admin_token(expired_token)
        with pytest.raises(UnauthorizedException) as exc_info:
            service.parse_admin_token(customer_token)

        assert "管理员认证失败" in str(exc_info.value)

    def test_initialize_super_admin_should_skip_when_another_super_admin_exists(self, monkeypatch):
        monkeypatch.setenv("ADMIN_INITIAL_EMAIL", "root@example.com")
        monkeypatch.setenv("ADMIN_INITIAL_PASSWORD", "Root123456")
        super_admin_role = Role(id=uuid4(), code="super_admin", name="超级管理员", is_system=True)
        existing_super_admin = AdminUser(id=uuid4(), email="exists@example.com", name="Root", status="active")
        session = _SessionStub([
            _QueryStub(one_or_none_result=None),
            _QueryStub(one_or_none_result=super_admin_role),
            _QueryStub(one_or_none_result=existing_super_admin),
        ])
        service = AdminUserService(session=session)

        result = service.initialize_super_admin_from_env()

        assert result == {"created": False, "reason": "super_admin_exists"}
        assert session.added == []
        assert session.commits == 0

    def test_create_admin_user_should_reject_second_super_admin_role(self):
        super_admin_role_id = uuid4()
        existing_super_admin = AdminUser(id=uuid4(), email="root@example.com", name="Root", status="active")
        session = _SessionStub([
            _QueryStub(one_or_none_result=None),
            _QueryStub(all_result=[(str(super_admin_role_id), "super_admin")]),
            _QueryStub(one_or_none_result=existing_super_admin),
        ])
        service = AdminUserService(session=session)

        with pytest.raises(FailException) as exc_info:
            service.create_admin_user(
                email="new@example.com",
                name="New Admin",
                password="Admin123456",
                role_ids=[str(super_admin_role_id)],
            )

        assert "超级管理员账号已存在" in str(exc_info.value)
        assert session.commits == 0

    def test_update_admin_user_should_reject_removing_only_super_admin_role(self):
        super_admin_id = uuid4()
        admin_user = AdminUser(id=super_admin_id, email="root@example.com", name="Root", status="active")
        session = _SessionStub([
            _QueryStub(one_or_none_result=admin_user),
            _QueryStub(all_result=[("super_admin",)]),
            _QueryStub(all_result=[]),
            _QueryStub(one_or_none_result=None),
        ])
        service = AdminUserService(session=session)

        with pytest.raises(FailException) as exc_info:
            service.update_admin_user(super_admin_id, role_ids=[])

        assert "至少保留一个超级管理员" in str(exc_info.value)
        assert session.commits == 0

    def test_disable_admin_user_should_reject_disabling_super_admin(self):
        super_admin_id = uuid4()
        admin_user = AdminUser(id=super_admin_id, email="root@example.com", name="Root", status="active")
        session = _SessionStub([
            _QueryStub(one_or_none_result=admin_user),
            _QueryStub(all_result=[("super_admin",)]),
        ])
        service = AdminUserService(session=session)

        with pytest.raises(FailException) as exc_info:
            service.disable_admin_user(super_admin_id)

        assert "超级管理员账号不允许禁用" in str(exc_info.value)
        assert admin_user.status == "active"
        assert session.commits == 0

    def test_create_admin_user_should_record_audit_log_before_commit(self):
        operator_id = uuid4()
        role_id = str(uuid4())
        audit_log_service = _AuditLogServiceStub()
        session = _SessionStub([
            _QueryStub(one_or_none_result=None),
            _QueryStub(),
            _QueryStub(all_result=[]),
        ])
        service = AdminUserService(session=session, audit_log_service=audit_log_service)

        result = service.create_admin_user(
            email="NEW@example.com",
            name="New Admin",
            password="Admin123456",
            role_ids=[role_id],
            operator_id=operator_id,
            ip="127.0.0.1",
            user_agent="pytest",
        )

        assert result["email"] == "new@example.com"
        assert session.commits == 1
        assert audit_log_service.records == [{
            "admin_user_id": operator_id,
            "action": "create",
            "resource_type": "admin_user",
            "resource_id": result["id"],
            "ip": "127.0.0.1",
            "user_agent": "pytest",
            "before_data": None,
            "after_data": {"email": "new@example.com", "name": "New Admin", "roles": [role_id]},
        }]

    def test_update_admin_user_should_record_before_and_after_audit_data(self):
        operator_id = uuid4()
        admin_id = uuid4()
        role_id = str(uuid4())
        admin_user = AdminUser(id=admin_id, email="admin@example.com", name="Old", status="active")
        audit_log_service = _AuditLogServiceStub()
        session = _SessionStub([
            _QueryStub(one_or_none_result=admin_user),
            _QueryStub(all_result=[("viewer",)]),
            _QueryStub(),
            _QueryStub(all_result=[]),
        ])
        service = AdminUserService(session=session, audit_log_service=audit_log_service)

        result = service.update_admin_user(
            admin_id,
            name="New",
            status="disabled",
            role_ids=[role_id],
            operator_id=operator_id,
            ip="127.0.0.1",
            user_agent="pytest",
        )

        assert result["name"] == "New"
        assert result["status"] == "disabled"
        assert session.commits == 1
        assert audit_log_service.records == [{
            "admin_user_id": operator_id,
            "action": "update",
            "resource_type": "admin_user",
            "resource_id": str(admin_id),
            "ip": "127.0.0.1",
            "user_agent": "pytest",
            "before_data": {"name": "Old", "email": "admin@example.com", "status": "active", "roles": ["viewer"]},
            "after_data": {"name": "New", "email": "admin@example.com", "status": "disabled", "roles": [role_id]},
        }]

    def test_disable_admin_user_should_record_audit_log(self):
        operator_id = uuid4()
        admin_id = uuid4()
        admin_user = AdminUser(id=admin_id, email="admin@example.com", name="Admin", status="active")
        audit_log_service = _AuditLogServiceStub()
        session = _SessionStub([_QueryStub(one_or_none_result=admin_user)])
        service = AdminUserService(session=session, audit_log_service=audit_log_service)

        service.disable_admin_user(
            admin_id,
            operator_id=operator_id,
            ip="127.0.0.1",
            user_agent="pytest",
        )

        assert admin_user.status == "disabled"
        assert session.commits == 1
        assert audit_log_service.records == [{
            "admin_user_id": operator_id,
            "action": "disable",
            "resource_type": "admin_user",
            "resource_id": str(admin_id),
            "ip": "127.0.0.1",
            "user_agent": "pytest",
            "before_data": {"status": "active"},
            "after_data": {"status": "disabled"},
        }]
