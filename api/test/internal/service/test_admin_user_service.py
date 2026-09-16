import base64
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from test.context import TestApp

from internal.core.rbac import all_permission_codes
from internal.exception import FailException, UnauthorizedException
from internal.model.account import Account, AccountSession
from internal.model.admin import AdminSession, AdminUser, AdminUserRole, Role
from internal.service.admin_user_service import AdminUserService
from pkg.password import PBKDF2_ITERATIONS_V1, compare_password, hash_password

# 测试用强密码（满足密码规则且不在弱口令黑名单）
_STRONG_ADMIN_PASSWORD = "Str0ng#Adm1n_2026"


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
    """生成存量 v1 参数（PBKDF2 10k 迭代）的密码哈希，模拟历史存量数据。"""
    salt = b"\x01" * 16
    hashed = hash_password(password, salt, iterations=PBKDF2_ITERATIONS_V1)
    return base64.b64encode(hashed).decode(), base64.b64encode(salt).decode()


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
        monkeypatch.setenv("ADMIN_INITIAL_PASSWORD", _STRONG_ADMIN_PASSWORD)
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
        assert created_users[0].password != _STRONG_ADMIN_PASSWORD
        assert created_users[0].password_salt != ""
        assert created_users[0].password_version == 2
        assert compare_password(
            _STRONG_ADMIN_PASSWORD, created_users[0].password, created_users[0].password_salt
        ) is True
        assert len(created_bindings) == 1
        assert created_bindings[0].admin_user_id == created_users[0].id
        assert created_bindings[0].role_id == super_admin_role.id
        # 完全解耦：初始化超级管理员不再创建/复用用户端账号
        assert len(created_accounts) == 0
        assert session.commits == 1

    def test_initialize_super_admin_should_skip_existing_user(self, monkeypatch):
        monkeypatch.setenv("ADMIN_INITIAL_EMAIL", "root@example.com")
        monkeypatch.setenv("ADMIN_INITIAL_PASSWORD", _STRONG_ADMIN_PASSWORD)
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
        # 当前参数（v2）生成的密码哈希，避免登录时触发旧参数重哈希影响 commits 断言
        salt = b"\x01" * 16
        password = base64.b64encode(hash_password("Root123456", salt)).decode()
        salt_base64 = base64.b64encode(salt).decode()
        admin_user = AdminUser(
            id=admin_user_id,
            username="admin",
            email="",
            name="Root",
            password=password,
            password_salt=salt_base64,
            password_version=2,
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
        assert admin_user_serialized["permissions"] == list(all_permission_codes())
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

        assert "密码错误" in str(exc_info.value)
        assert session.added == []
        assert session.commits == 0

    def test_password_login_should_reject_unknown_account(self, monkeypatch):
        monkeypatch.setenv("JWT_SECRET_KEY", "test-secret-key-with-32-bytes-min-123456")
        session = _SessionStub([_QueryStub(one_or_none_result=None)])
        service = AdminUserService(session=session)

        with pytest.raises(FailException) as exc_info:
            service.password_login("nobody@example.com", "Wrong123456")

        assert "账号不存在" in str(exc_info.value)
        assert "密码错误" not in str(exc_info.value)
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
        assert (
            compare_password(
                "Root123456",
                admin_user.password,
                admin_user.password_salt,
                iterations=PBKDF2_ITERATIONS_V1,
            )
            is True
        )
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
        monkeypatch.setenv("ADMIN_INITIAL_PASSWORD", _STRONG_ADMIN_PASSWORD)
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
        existing_super_admin = AdminUser(id=uuid4(), email="root@example.com", name="Root", status="active")
        session = _SessionStub([
            _QueryStub(one_or_none_result=None),
            _QueryStub(one_or_none_result=existing_super_admin),
        ])
        service = AdminUserService(session=session)

        with pytest.raises(FailException) as exc_info:
            service.create_admin_user(
                email="new@example.com",
                name="New Admin",
                password="Admin123456",
                role_codes=["super_admin"],
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
            service.update_admin_user(super_admin_id, role_codes=[])

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

    def test_delete_admin_user_should_soft_delete_and_revoke_sessions(self):
        """删除=软删除：置 status=deleted + 记录删除轨迹 + 吊销全部会话。"""
        operator_id = uuid4()
        admin_id = uuid4()
        admin_user = AdminUser(id=admin_id, email="x@example.com", name="X", status="active")
        audit_log_service = _AuditLogServiceStub()
        session = _SessionStub([
            _QueryStub(one_or_none_result=admin_user),   # 查目标管理员
            _QueryStub(all_result=[("operator",)]),      # 查其角色（非超管）
            _QueryStub(one_or_none_result=None),         # _get_active_super_admin_user
            _QueryStub(all_result=[]),                   # 查其会话（吊销用）
            _QueryStub(all_result=[]),                   # 序列化角色
        ])
        service = AdminUserService(session=session, audit_log_service=audit_log_service)

        result = service.delete_admin_user(
            admin_id,
            reason="离职",
            operator_id=operator_id,
            ip="127.0.0.1",
            user_agent="pytest",
        )

        assert admin_user.status == "deleted"
        assert admin_user.deleted_reason == "离职"
        assert admin_user.deleted_by == operator_id
        assert admin_user.deleted_at is not None
        assert result["status"] == "deleted"
        assert result["deleted_reason"] == "离职"
        assert session.commits == 1
        assert audit_log_service.records[0]["action"] == "delete"

    def test_delete_admin_user_should_reject_super_admin(self):
        """超级管理员不允许被删除（与禁用/重置密码的保护一致）。"""
        super_admin_id = uuid4()
        admin_user = AdminUser(id=super_admin_id, email="root@example.com", name="Root", status="active")
        session = _SessionStub([
            _QueryStub(one_or_none_result=admin_user),
            _QueryStub(all_result=[("super_admin",)]),
        ])
        service = AdminUserService(session=session)

        with pytest.raises(FailException) as exc_info:
            service.delete_admin_user(super_admin_id)

        assert "超级管理员账号不允许删除" in str(exc_info.value)
        assert admin_user.status == "active"
        assert session.commits == 0

    def test_delete_admin_user_should_reject_self(self):
        """不允许删除自己，避免管理员把自己锁在系统外。"""
        admin_id = uuid4()
        admin_user = AdminUser(id=admin_id, email="me@example.com", name="Me", status="active")
        session = _SessionStub([
            _QueryStub(one_or_none_result=admin_user),
            _QueryStub(all_result=[("operator",)]),
            _QueryStub(one_or_none_result=None),
        ])
        service = AdminUserService(session=session)

        with pytest.raises(FailException) as exc_info:
            service.delete_admin_user(admin_id, operator_id=admin_id)

        assert "不能删除自己的账号" in str(exc_info.value)
        assert admin_user.status == "active"
        assert session.commits == 0

    def test_delete_admin_user_should_reject_already_deleted(self):
        """重复删除必须被拒绝，不能静默成功。"""
        admin_id = uuid4()
        admin_user = AdminUser(id=admin_id, email="x@example.com", name="X", status="deleted")
        session = _SessionStub([_QueryStub(one_or_none_result=admin_user)])
        service = AdminUserService(session=session)

        with pytest.raises(FailException) as exc_info:
            service.delete_admin_user(admin_id)

        assert "已删除" in str(exc_info.value)
        assert session.commits == 0

    def test_create_admin_user_should_record_audit_log_before_commit(self):
        operator_id = uuid4()
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
            role_codes=[],
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
            "after_data": {"email": "new@example.com", "name": "New Admin", "roles": []},
        }]

    def test_update_admin_user_should_record_before_and_after_audit_data(self):
        operator_id = uuid4()
        admin_id = uuid4()
        role_id = uuid4()
        admin_user = AdminUser(id=admin_id, email="admin@example.com", name="Old", status="active")
        audit_log_service = _AuditLogServiceStub()
        session = _SessionStub([
            _QueryStub(one_or_none_result=admin_user),
            _QueryStub(all_result=[("viewer",)]),
            _QueryStub(),
            _QueryStub(all_result=[(str(role_id), "viewer")]),
            _QueryStub(all_result=[]),
        ])
        service = AdminUserService(session=session, audit_log_service=audit_log_service)

        result = service.update_admin_user(
            admin_id,
            name="New",
            status="disabled",
            role_codes=["viewer"],
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
            "after_data": {"name": "New", "email": "admin@example.com", "status": "disabled", "roles": ["viewer"]},
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

    def test_super_admin_permission_resolution_should_be_wildcard(self):
        service = AdminUserService(session=_SessionStub())

        permissions = service._get_permission_codes(["super_admin"])

        assert permissions == list(all_permission_codes())


class TestAgentPermissionPruningWiring:
    """§4.4 权限回收的**接线**测试：确认两个触发点真的调用了清理。

    为什么单独测接线：`AdminAgentService.prune_revoked_permissions` 自身有
    单测（行为正确），但若不接进 `AdminUserService`，功能在运行时**不可达**
    ——即 AGENTS.md 所述"断链"。单测各自全绿也发现不了，必须断言调用发生。

    两个触发点：
    1. `update_admin_user(role_codes=...)` —— 角色变更改变权限集；
    2. `disable_admin_user(...)` —— 直接失效（传空权限集）。
    """

    def _install_fake_agent_service(self, monkeypatch, calls):
        class _FakeAgentService:
            def __init__(self, db=None):
                self._db = db

            def prune_revoked_permissions(self, *, admin_user_id, admin_permissions):
                calls.append((admin_user_id, list(admin_permissions), self._db))
                return 1

        # _prune_admin_agent_permissions 在调用时从该模块导入 AdminAgentService，
        # 故 patch 模块属性即可拦截（验证"接线存在"而无需真库）。
        monkeypatch.setattr(
            "internal.service.admin_agent_service.AdminAgentService",
            _FakeAgentService,
        )

    def test_update_admin_user_role_change_prunes_agent_permissions(self, monkeypatch):
        """角色变更后必须按**新**权限集清理（不是旧权限集）。"""
        calls = []
        self._install_fake_agent_service(monkeypatch, calls)

        admin_id = uuid4()
        role_id = uuid4()
        admin_user = AdminUser(id=admin_id, email="a@example.com", name="A", status="active")
        session = _SessionStub([
            _QueryStub(one_or_none_result=admin_user),          # 查目标管理员
            _QueryStub(all_result=[("viewer",)]),               # before_roles
            _QueryStub(),                                       # 删旧角色
            _QueryStub(all_result=[(str(role_id), "viewer")]),  # _resolve_role_ids
            _QueryStub(all_result=[("viewer",)]),               # _get_role_codes（清理用）
            _QueryStub(all_result=[("app:read",)]),             # _get_permission_codes
            _QueryStub(all_result=[("viewer",)]),               # 序列化角色
            _QueryStub(all_result=[]),                          # _is_admin_online
        ])
        service = AdminUserService(session=session)

        service.update_admin_user(admin_id, role_codes=["viewer"])

        assert len(calls) == 1, "角色变更未触发 Agent 权限清理（断链）"
        pruned_admin_id, pruned_perms, _db = calls[0]
        assert pruned_admin_id == admin_id
        assert pruned_perms == ["app:read"], "清理应基于变更后的新权限集"

    def test_disable_admin_user_prunes_all_agent_permissions(self, monkeypatch):
        """禁用管理员后，其 Agent 的授权应被清空（传空权限集）。"""
        calls = []
        self._install_fake_agent_service(monkeypatch, calls)

        admin_id = uuid4()
        admin_user = AdminUser(id=admin_id, email="d@example.com", name="D", status="active")
        session = _SessionStub([
            _QueryStub(one_or_none_result=admin_user),  # 查目标管理员
            _QueryStub(all_result=[("viewer",)]),       # 角色（非超管）
        ])
        service = AdminUserService(session=session, audit_log_service=_AuditLogServiceStub())

        service.disable_admin_user(admin_id)

        assert len(calls) == 1, "禁用管理员未触发 Agent 权限清理（断链）"
        assert calls[0][0] == admin_id
        assert calls[0][1] == [], "禁用应清空全部已下放权限"

    def test_prune_failure_does_not_break_role_update(self, monkeypatch):
        """清理失败必须被吞掉：角色变更本身已成功，不能因清理失败回滚主流程。"""
        class _ExplodingAgentService:
            def __init__(self, db=None):
                pass

            def prune_revoked_permissions(self, **_kw):
                raise RuntimeError("agent service down")

        monkeypatch.setattr(
            "internal.service.admin_agent_service.AdminAgentService",
            _ExplodingAgentService,
        )

        admin_id = uuid4()
        role_id = uuid4()
        admin_user = AdminUser(id=admin_id, email="b@example.com", name="B", status="active")
        session = _SessionStub([
            _QueryStub(one_or_none_result=admin_user),
            _QueryStub(all_result=[("viewer",)]),
            _QueryStub(),
            _QueryStub(all_result=[(str(role_id), "viewer")]),
            _QueryStub(all_result=[("viewer",)]),
            _QueryStub(all_result=[("app:read",)]),
            _QueryStub(all_result=[("viewer",)]),
            _QueryStub(all_result=[]),
        ])
        service = AdminUserService(session=session)

        # 不应抛出：清理失败被静默吸收
        service.update_admin_user(admin_id, role_codes=["viewer"])
        assert session.commits == 1, "主流程（角色变更）应正常提交"
