from datetime import datetime
from uuid import uuid4

from internal.model.account import Account
from internal.model.admin import AdminUser, AuditLog
from internal.service.audit_log_service import AuditLogService


class _QueryStub:
    def __init__(self, rows=None):
        self.rows = [] if rows is None else rows
        self.filters = []
        self.order_by_args = []
        self.offset_value = None
        self.limit_value = None

    def filter(self, *args, **kwargs):
        self.filters.append((args, kwargs))
        return self

    def count(self):
        return len(self.rows)

    def order_by(self, *args):
        self.order_by_args.append(args)
        return self

    def offset(self, value):
        self.offset_value = value
        return self

    def limit(self, value):
        self.limit_value = value
        return self

    def all(self):
        return self.rows


class _SessionStub:
    def __init__(self, query=None, admin_user_rows=None, account_rows=None):
        self.added = []
        self.commits = 0
        self.query_stub = query
        self.admin_user_rows = [] if admin_user_rows is None else admin_user_rows
        self.account_rows = [] if account_rows is None else account_rows

    def add(self, obj):
        self.added.append(obj)

    def commit(self):
        self.commits += 1

    def query(self, *_args, **_kwargs):
        if _args and _args[0] is AdminUser.id:
            return _QueryStub(rows=self.admin_user_rows)
        if _args and _args[0] is Account.id:
            return _QueryStub(rows=self.account_rows)
        return self.query_stub or _QueryStub()


class TestAuditLogService:
    def test_record_should_create_audit_log_with_action_context(self):
        session = _SessionStub()
        admin_user_id = uuid4()
        service = AuditLogService(session=session)

        audit_log = service.record(
            admin_user_id=admin_user_id,
            action="admin_user:disable",
            resource_type="admin_user",
            resource_id="admin-2",
            ip="127.0.0.1",
            user_agent="pytest",
            before_data={"status": "active"},
            after_data={"status": "disabled"},
        )

        assert isinstance(audit_log, AuditLog)
        assert audit_log.admin_user_id == admin_user_id
        assert audit_log.action == "admin_user:disable"
        assert audit_log.resource_type == "admin_user"
        assert audit_log.resource_id == "admin-2"
        assert audit_log.ip == "127.0.0.1"
        assert audit_log.user_agent == "pytest"
        assert audit_log.before_data == {"status": "active"}
        assert audit_log.after_data == {"status": "disabled"}
        assert session.added == [audit_log]
        assert session.commits == 1

    def test_record_should_default_empty_payloads_and_allow_no_commit(self):
        session = _SessionStub()
        service = AuditLogService(session=session)

        audit_log = service.record(
            admin_user_id=None,
            action="role:create",
            resource_type="role",
            commit=False,
        )

        assert audit_log.before_data == {}
        assert audit_log.after_data == {}
        assert audit_log.resource_id == ""
        assert audit_log.ip == ""
        assert audit_log.user_agent == ""
        assert session.added == [audit_log]
        assert session.commits == 0

    def test_record_for_write_should_skip_when_operator_is_missing(self):
        session = _SessionStub()
        service = AuditLogService(session=session)

        result = service.record_for_write(
            admin_user_id=None,
            action="create",
            resource_type="admin_user",
        )

        assert result is None
        assert session.added == []
        assert session.commits == 0

    def test_list_audit_logs_should_apply_admin_and_time_filters(self):
        admin_user_id = uuid4()
        audit_log = AuditLog(
            id=uuid4(),
            admin_user_id=admin_user_id,
            action="create",
            resource_type="admin_user",
            resource_id="admin-1",
            ip="127.0.0.1",
            user_agent="pytest",
            before_data={},
            after_data={"name": "Root"},
        )
        audit_log.created_at = datetime(2030, 1, 1, 0, 0, 0)
        query = _QueryStub(rows=[audit_log])
        admin_user_rows = [(admin_user_id, "root", "Root")]
        session = _SessionStub(query=query, admin_user_rows=admin_user_rows)
        service = AuditLogService(session=session)

        result = service.list_audit_logs(
            action="create",
            resource_type="admin_user",
            admin_user_id=str(admin_user_id),
            start_time=1893456000,
            end_time=1893542400,
            current_page=1,
            page_size=20,
        )

        assert len(query.filters) == 5
        assert query.offset_value == 0
        assert query.limit_value == 20
        assert result["list"][0]["admin_user_id"] == str(admin_user_id)
        assert result["list"][0]["admin_user_name"] == "root"
        assert result["list"][0]["created_at"] == int(audit_log.created_at.timestamp())
        assert result["paginator"] == {
            "total_record": 1,
            "total_page": 1,
            "current_page": 1,
            "page_size": 20,
        }
