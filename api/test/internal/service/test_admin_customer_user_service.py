from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from internal.exception import NotFoundException
from internal.model.account import Account, AccountSession
from internal.service.admin_customer_user_service import AdminCustomerUserService


class _QueryStub:
    def __init__(self, *, one_or_none_result=None, all_result=None, count_result=None, delete_result=0):
        self._one_or_none_result = one_or_none_result
        self._all_result = [] if all_result is None else all_result
        self._count_result = len(self._all_result) if count_result is None else count_result
        self._delete_result = delete_result
        self.filters = []
        self.order_by_args = []
        self.offset_value = None
        self.limit_value = None

    def filter(self, *args, **kwargs):
        self.filters.append((args, kwargs))
        return self

    def order_by(self, *args):
        self.order_by_args.append(args)
        return self

    def offset(self, value):
        self.offset_value = value
        return self

    def limit(self, value):
        self.limit_value = value
        return self

    def count(self):
        return self._count_result

    def one_or_none(self):
        return self._one_or_none_result

    def first(self):
        return self._one_or_none_result

    def all(self):
        return self._all_result

    def delete(self):
        return self._delete_result

    def update(self, _values=None, **kwargs):
        return self._delete_result


class _SessionStub:
    def __init__(self, queries=None):
        self._queries = list(queries or [])
        self.commits = 0
        self.added = []

    def query(self, *_args, **_kwargs):
        if self._queries:
            return self._queries.pop(0)
        return _QueryStub()

    def add(self, obj):
        self.added.append(obj)

    def flush(self):
        pass

    def commit(self):
        self.commits += 1


class _AuditLogServiceStub:
    def __init__(self):
        self.records = []

    def record_for_write(self, **kwargs):
        self.records.append(kwargs)


def _account(**kwargs):
    defaults = {
        "id": uuid4(),
        "email": "user@example.com",
        "name": "User",
        "avatar": "",
        "status": "active",
        "disabled_at": None,
        "disabled_by": None,
        "disabled_reason": "",
        "deleted_at": None,
        "deleted_by": None,
        "deleted_reason": "",
        "last_login_at": datetime(2030, 1, 1, 0, 0, 0),
        "last_login_ip": "127.0.0.1",
        "created_at": datetime(2029, 1, 1, 0, 0, 0),
    }
    defaults.update(kwargs)
    return Account(**defaults)


class TestAdminCustomerUserService:
    def test_list_customer_users_should_support_pagination_and_filters(self):
        account = _account(email="USER@example.com", name="User One")
        query = _QueryStub(all_result=[account], count_result=1)
        service = AdminCustomerUserService(session=_SessionStub([query]))

        result = service.list_customer_users(keyword="user", status="active", current_page=2, page_size=10)

        assert query.offset_value == 10
        assert query.limit_value == 10
        assert len(query.filters) == 2
        assert result["list"] == [{
            "id": str(account.id),
            "email": "USER@example.com",
            "name": "User One",
            "avatar": "",
            "status": "active",
            "disabled_at": None,
            "disabled_by": None,
            "disabled_reason": "",
            "deleted_at": None,
            "deleted_by": None,
            "deleted_reason": "",
            "last_login_at": 1893456000,
            "last_login_ip": "127.0.0.1",
            "created_at": 1861920000,
            "is_online": False,
            "superior_id": None,
            "superior_name": "",
            "superior_email": "",
        }]
        assert result["paginator"] == {
            "total_record": 1,
            "total_page": 1,
            "current_page": 2,
            "page_size": 10,
        }

    def test_get_customer_user_should_return_detail_with_sessions(self):
        account_id = uuid4()
        session_id = uuid4()
        account = _account(id=account_id)
        account_session = AccountSession(
            id=session_id,
            account_id=account_id,
            user_agent="Chrome",
            last_login_ip="127.0.0.1",
            last_active_at=datetime(2030, 1, 2, 0, 0, 0),
            expires_at=datetime(2030, 1, 3, 0, 0, 0),
            revoked_at=None,
            created_at=datetime(2030, 1, 1, 0, 0, 0),
        )
        service = AdminCustomerUserService(session=_SessionStub([
            _QueryStub(one_or_none_result=account),
            _QueryStub(),
            _QueryStub(),
            _QueryStub(),
            _QueryStub(all_result=[account_session]),
        ]))

        result = service.get_customer_user(account_id)

        assert result["id"] == str(account_id)
        assert result["sessions"] == [{
            "id": str(session_id),
            "status": "active",
            "user_agent": "Chrome",
            "ip": "127.0.0.1",
            "created_at": 1893456000,
            "last_active_at": 1893542400,
            "expires_at": 1893628800,
            "revoked_at": None,
        }]

    def test_disable_customer_user_should_update_status_revoke_sessions_and_record_audit(self):
        operator_id = uuid4()
        account_id = uuid4()
        session_id = uuid4()
        now = datetime.now(UTC).replace(tzinfo=None)
        account = _account(id=account_id, status="active")
        account_session = AccountSession(
            id=session_id,
            account_id=account_id,
            expires_at=now + timedelta(days=1),
            revoked_at=None,
        )
        audit_log_service = _AuditLogServiceStub()
        session = _SessionStub([
            _QueryStub(one_or_none_result=account),
            _QueryStub(),
            _QueryStub(all_result=[account_session]),
            _QueryStub(),
        ])
        service = AdminCustomerUserService(session=session, audit_log_service=audit_log_service)

        result = service.disable_customer_user(
            account_id,
            reason="risk",
            operator_id=operator_id,
            ip="127.0.0.1",
            user_agent="pytest",
        )

        assert result["status"] == "disabled"
        assert account.status == "disabled"
        assert account.disabled_by == operator_id
        assert account.disabled_reason == "risk"
        assert account.disabled_at is not None
        assert account_session.revoked_at is not None
        assert session.commits == 1
        assert audit_log_service.records == [{
            "admin_user_id": operator_id,
            "action": "disable",
            "resource_type": "customer_user",
            "resource_id": str(account_id),
            "ip": "127.0.0.1",
            "user_agent": "pytest",
            "before_data": {"status": "active", "disabled_reason": ""},
            "after_data": {"status": "disabled", "disabled_reason": "risk", "revoked_sessions": 1},
        }]

    def test_enable_customer_user_should_update_status_and_record_audit(self):
        operator_id = uuid4()
        account_id = uuid4()
        disabled_by = uuid4()
        account = _account(
            id=account_id,
            status="disabled",
            disabled_at=datetime(2030, 1, 1, 0, 0, 0),
            disabled_by=disabled_by,
            disabled_reason="risk",
        )
        audit_log_service = _AuditLogServiceStub()
        session = _SessionStub([_QueryStub(one_or_none_result=account)])
        service = AdminCustomerUserService(session=session, audit_log_service=audit_log_service)

        result = service.enable_customer_user(
            account_id,
            operator_id=operator_id,
            ip="127.0.0.1",
            user_agent="pytest",
        )

        assert result["status"] == "active"
        assert account.status == "active"
        assert account.disabled_at is None
        assert account.disabled_by is None
        assert account.disabled_reason == ""
        assert session.commits == 1
        assert audit_log_service.records == [{
            "admin_user_id": operator_id,
            "action": "enable",
            "resource_type": "customer_user",
            "resource_id": str(account_id),
            "ip": "127.0.0.1",
            "user_agent": "pytest",
            "before_data": {"status": "disabled", "disabled_reason": "risk"},
            "after_data": {"status": "active", "disabled_reason": ""},
        }]

    def test_revoke_customer_user_sessions_should_revoke_active_sessions_and_record_audit(self):
        operator_id = uuid4()
        account_id = uuid4()
        now = datetime.now(UTC).replace(tzinfo=None)
        account = _account(id=account_id)
        active_session = AccountSession(id=uuid4(), account_id=account_id, expires_at=now + timedelta(days=1), revoked_at=None)
        revoked_session = AccountSession(id=uuid4(), account_id=account_id, expires_at=now + timedelta(days=1), revoked_at=now)
        audit_log_service = _AuditLogServiceStub()
        session = _SessionStub([
            _QueryStub(one_or_none_result=account),
            _QueryStub(),
            _QueryStub(all_result=[active_session, revoked_session]),
        ])
        service = AdminCustomerUserService(session=session, audit_log_service=audit_log_service)

        result = service.revoke_customer_user_sessions(
            account_id,
            operator_id=operator_id,
            ip="127.0.0.1",
            user_agent="pytest",
        )

        assert result == {"revoked_sessions": 1}
        assert active_session.revoked_at is not None
        assert revoked_session.revoked_at == now
        assert session.commits == 1
        assert audit_log_service.records == [{
            "admin_user_id": operator_id,
            "action": "revoke_sessions",
            "resource_type": "customer_user",
            "resource_id": str(account_id),
            "ip": "127.0.0.1",
            "user_agent": "pytest",
            "before_data": {"active_sessions": 1},
            "after_data": {"revoked_sessions": 1},
        }]

    def test_get_customer_user_should_raise_not_found_when_missing(self):
        service = AdminCustomerUserService(session=_SessionStub([_QueryStub(one_or_none_result=None)]))

        with pytest.raises(NotFoundException):
            service.get_customer_user(uuid4())

    def test_create_customer_user_should_create_account_and_record_audit(self):
        operator_id = uuid4()
        audit_log_service = _AuditLogServiceStub()
        # email 查重返回 None、username 查重返回 None
        session = _SessionStub([
            _QueryStub(one_or_none_result=None),  # email exists?
            _QueryStub(one_or_none_result=None),  # username exists?
        ])
        service = AdminCustomerUserService(session=session, audit_log_service=audit_log_service)

        result = service.create_customer_user(
            email="NEW@Example.com",
            name="新用户",
            password="Passw0rd!",
            username="newuser",
            operator_id=operator_id,
            ip="127.0.0.1",
            user_agent="pytest",
        )

        assert result["email"] == "new@example.com"
        assert result["status"] == "active"
        assert len(session.added) == 1
        created = session.added[0]
        assert created.name == "新用户"
        assert created.username == "newuser"
        # 密码已哈希（非明文）
        assert created.password and created.password != "Passw0rd!"
        assert created.password_salt is not None
        assert session.commits == 1
        assert audit_log_service.records[0]["action"] == "create"
        assert audit_log_service.records[0]["after_data"]["email"] == "new@example.com"

    def test_create_customer_user_should_reject_duplicate_email(self):
        from internal.exception import FailException

        existing = _account(email="dup@example.com")
        session = _SessionStub([
            _QueryStub(one_or_none_result=existing),  # email exists → 冲突
        ])
        service = AdminCustomerUserService(session=session, audit_log_service=_AuditLogServiceStub())

        with pytest.raises(FailException):
            service.create_customer_user(email="dup@example.com", name="重复", operator_id=uuid4())

    def test_update_customer_user_should_update_fields_and_audit(self):
        operator_id = uuid4()
        account_id = uuid4()
        account = _account(id=account_id, name="旧名", email="old@example.com", status="active")
        audit_log_service = _AuditLogServiceStub()
        session = _SessionStub([
            _QueryStub(one_or_none_result=account),   # _get_account_or_raise: account
            _QueryStub(one_or_none_result=None),      # _ensure_not_admin_bound
            _QueryStub(one_or_none_result=None),      # email exists? (new email 无冲突)
        ])
        service = AdminCustomerUserService(session=session, audit_log_service=audit_log_service)

        result = service.update_customer_user(
            account_id,
            name="新名",
            email="new@example.com",
            operator_id=operator_id,
            ip="127.0.0.1",
            user_agent="pytest",
        )

        assert result["name"] == "新名"
        assert account.name == "新名"
        assert account.email == "new@example.com"
        assert session.commits == 1
        assert audit_log_service.records[0]["action"] == "update"

    def test_delete_customer_user_should_mark_deleted_revoke_and_cleanup_memory(self):
        operator_id = uuid4()
        account_id = uuid4()
        account = _account(id=account_id, status="active", email="del@example.com", name="待删")
        audit_log_service = _AuditLogServiceStub()
        # 查询序列：
        # 1 _get_account_or_raise: account
        # 2 _ensure_not_admin_bound
        # 3 _revoke_active_sessions: list sessions（all_result=[] → 0 撤销）
        # 4 _cleanup_user_runtime_data PG user_memory delete → delete_result=3
        # 5 _cleanup_user_runtime_data PG schedule_task update → delete_result=2
        session = _SessionStub([
            _QueryStub(one_or_none_result=account),
            _QueryStub(one_or_none_result=None),
            _QueryStub(all_result=[]),
            _QueryStub(delete_result=3),
            _QueryStub(delete_result=2),
        ])
        service = AdminCustomerUserService(session=session, audit_log_service=audit_log_service)

        result = service.delete_customer_user(
            account_id,
            reason="用户要求注销",
            operator_id=operator_id,
            ip="127.0.0.1",
            user_agent="pytest",
        )

        assert result["status"] == "deleted"
        assert account.status == "deleted"
        assert account.deleted_at is not None
        assert account.deleted_by == operator_id
        assert account.deleted_reason == "用户要求注销"
        assert session.commits == 1
        assert audit_log_service.records[0]["action"] == "delete"
        assert audit_log_service.records[0]["after_data"]["status"] == "deleted"
        assert audit_log_service.records[0]["after_data"]["deleted_reason"] == "用户要求注销"
        assert audit_log_service.records[0]["after_data"]["cleanup"]["pg_rows"] == 3
        assert audit_log_service.records[0]["after_data"]["cleanup"]["schedule_tasks_disabled"] == 2

    def test_delete_customer_user_should_reject_when_already_deleted(self):
        from internal.exception import FailException

        account = _account(status="deleted")
        session = _SessionStub([_QueryStub(one_or_none_result=account)])
        service = AdminCustomerUserService(session=session, audit_log_service=_AuditLogServiceStub())

        with pytest.raises(FailException):
            service.delete_customer_user(account.id, operator_id=uuid4())

    def test_disable_deleted_user_should_reject(self):
        from internal.exception import FailException

        account = _account(status="deleted")
        session = _SessionStub([_QueryStub(one_or_none_result=account)])
        service = AdminCustomerUserService(session=session, audit_log_service=_AuditLogServiceStub())

        with pytest.raises(FailException):
            service.disable_customer_user(account.id, operator_id=uuid4())
