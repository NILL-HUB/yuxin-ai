from datetime import datetime
from uuid import uuid4

import pytest

from internal.entity.app_entity import AppStatus
from internal.exception import FailException, NotFoundException
from internal.model.account import Account
from internal.model.app import App, AppAssignment
from internal.service.admin_app_assignment_service import AdminAppAssignmentService


class _QueryStub:
    def __init__(self, *, one_or_none_result=None, all_result=None, first_result=None):
        self._one_or_none_result = one_or_none_result
        self._all_result = [] if all_result is None else all_result
        self._first_result = first_result
        self.filters = []
        self.order_by_args = []

    def filter(self, *args, **kwargs):
        self.filters.append((args, kwargs))
        return self

    def order_by(self, *args):
        self.order_by_args.append(args)
        return self

    def one_or_none(self):
        return self._one_or_none_result

    def first(self):
        return self._first_result

    def all(self):
        return self._all_result


class _SessionStub:
    def __init__(self, queries=None):
        self._queries = list(queries or [])
        self.added = []
        self.commits = 0
        self.flushes = 0

    def query(self, *_args, **_kwargs):
        if self._queries:
            return self._queries.pop(0)
        return _QueryStub()

    def add(self, value):
        self.added.append(value)

    def commit(self):
        self.commits += 1

    def flush(self):
        self.flushes += 1


class _AuditLogServiceStub:
    def __init__(self):
        self.records = []

    def record_for_write(self, **kwargs):
        self.records.append(kwargs)


def _account(**kwargs):
    defaults = {"id": uuid4(), "email": "user@example.com", "name": "User", "status": "active"}
    defaults.update(kwargs)
    return Account(**defaults)


def _app(**kwargs):
    defaults = {
        "id": uuid4(),
        "account_id": uuid4(),
        "name": "AI App",
        "icon": "🤖",
        "description": "Assigned AI app",
        "status": AppStatus.PUBLISHED.value,
        "is_public": False,
        "published_at": datetime(2030, 1, 1, 0, 0, 0),
    }
    defaults.update(kwargs)
    return App(**defaults)


def _assignment(**kwargs):
    defaults = {
        "id": uuid4(),
        "app_id": uuid4(),
        "account_id": uuid4(),
        "assigned_by": uuid4(),
        "status": "active",
        "assigned_at": datetime(2030, 1, 1, 0, 0, 0),
        "revoked_at": None,
    }
    defaults.update(kwargs)
    return AppAssignment(**defaults)


class TestAdminAppAssignmentService:
    def test_assign_apps_should_create_assignment_for_published_app(self):
        operator_id = uuid4()
        account = _account()
        app = _app()
        audit_log_service = _AuditLogServiceStub()
        service = AdminAppAssignmentService(
            session=_SessionStub([
                _QueryStub(one_or_none_result=account),
                _QueryStub(),
                _QueryStub(one_or_none_result=app),
                _QueryStub(one_or_none_result=None),
            ]),
            audit_log_service=audit_log_service,
        )

        result = service.assign_apps(account.id, [app.id], operator_id=operator_id, ip="127.0.0.1", user_agent="pytest")

        assert result["assigned"] == 1
        assert result["reactivated"] == 0
        assert len(service.session.added) == 1
        assignment = service.session.added[0]
        assert isinstance(assignment, AppAssignment)
        assert assignment.app_id == app.id
        assert assignment.account_id == account.id
        assert assignment.assigned_by == operator_id
        assert service.session.commits == 1
        assert audit_log_service.records[0]["resource_type"] == "app_assignment"
        assert audit_log_service.records[0]["action"] == "assign"

    def test_assign_apps_should_reject_draft_app(self):
        account = _account()
        app = _app(status=AppStatus.DRAFT.value)
        service = AdminAppAssignmentService(session=_SessionStub([
            _QueryStub(one_or_none_result=account),
            _QueryStub(),
            _QueryStub(one_or_none_result=app),
        ]))

        with pytest.raises(FailException):
            service.assign_apps(account.id, [app.id])

    def test_assign_apps_should_reactivate_revoked_assignment(self):
        account = _account()
        app = _app()
        assignment = _assignment(app_id=app.id, account_id=account.id, status="revoked", revoked_at=datetime(2030, 1, 1, 0, 0, 0))
        service = AdminAppAssignmentService(session=_SessionStub([
            _QueryStub(one_or_none_result=account),
            _QueryStub(),
            _QueryStub(one_or_none_result=app),
            _QueryStub(one_or_none_result=assignment),
        ]))

        result = service.assign_apps(account.id, [app.id], operator_id=uuid4())

        assert result["assigned"] == 0
        assert result["reactivated"] == 1
        assert assignment.status == "active"
        assert assignment.revoked_at is None
        assert service.session.commits == 1

    def test_assign_apps_should_skip_existing_active_assignment(self):
        account = _account()
        app = _app()
        assignment = _assignment(app_id=app.id, account_id=account.id, status="active")
        service = AdminAppAssignmentService(session=_SessionStub([
            _QueryStub(one_or_none_result=account),
            _QueryStub(),
            _QueryStub(one_or_none_result=app),
            _QueryStub(one_or_none_result=assignment),
        ]))

        result = service.assign_apps(account.id, [app.id])

        assert result["assigned"] == 0
        assert result["skipped"] == 1
        assert service.session.added == []

    def test_revoke_assignment_should_mark_revoked(self):
        account_id = uuid4()
        assignment = _assignment(account_id=account_id, status="active")
        audit_log_service = _AuditLogServiceStub()
        service = AdminAppAssignmentService(
            session=_SessionStub([_QueryStub(one_or_none_result=assignment)]),
            audit_log_service=audit_log_service,
        )

        result = service.revoke_assignment(account_id, assignment.id, operator_id=uuid4(), ip="127.0.0.1", user_agent="pytest")

        assert result["status"] == "revoked"
        assert assignment.status == "revoked"
        assert assignment.revoked_at is not None
        assert service.session.commits == 1
        assert audit_log_service.records[0]["action"] == "revoke"

    def test_revoke_assignment_should_raise_when_missing(self):
        service = AdminAppAssignmentService(session=_SessionStub([_QueryStub(one_or_none_result=None)]))

        with pytest.raises(NotFoundException):
            service.revoke_assignment(uuid4(), uuid4())

    def test_list_assignments_should_include_app_info(self):
        account = _account()
        app = _app(name="Contract AI")
        assignment = _assignment(app_id=app.id, account_id=account.id, status="active")
        assignment.app = app
        service = AdminAppAssignmentService(session=_SessionStub([
            _QueryStub(one_or_none_result=account),
            _QueryStub(),
            _QueryStub(all_result=[assignment]),
        ]))

        result = service.list_assignments(account.id)

        assert result["list"][0]["id"] == str(assignment.id)
        assert result["list"][0]["status"] == "active"
        assert result["list"][0]["app"]["id"] == str(app.id)
        assert result["list"][0]["app"]["name"] == "Contract AI"
