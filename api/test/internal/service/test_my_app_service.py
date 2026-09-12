from datetime import datetime
from uuid import uuid4

import pytest

from internal.entity.app_entity import AppStatus
from internal.exception import FailException, NotFoundException
from internal.model.app import App, AppAssignment
from internal.service.my_app_service import MyAppService


class _QueryStub:
    def __init__(self, *, one_or_none_result=None, all_result=None):
        self._one_or_none_result = one_or_none_result
        self._all_result = [] if all_result is None else all_result
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

    def all(self):
        return self._all_result


class _SessionStub:
    def __init__(self, queries=None):
        self._queries = list(queries or [])

    def query(self, *_args, **_kwargs):
        if self._queries:
            return self._queries.pop(0)
        return _QueryStub()


def _app(**kwargs):
    defaults = {
        "id": uuid4(),
        "account_id": uuid4(),
        "name": "Assigned AI",
        "icon": "🤖",
        "description": "AI app assigned to customer",
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


class TestMyAppService:
    def test_list_my_apps_should_return_active_published_assignments(self):
        account_id = uuid4()
        app = _app(name="Contract AI")
        assignment = _assignment(app_id=app.id, account_id=account_id, status="active")
        assignment.app = app
        service = MyAppService(session=_SessionStub([_QueryStub(all_result=[assignment])]))

        result = service.list_my_apps(account_id)

        assert result["list"][0]["id"] == str(app.id)
        assert result["list"][0]["assignment_id"] == str(assignment.id)
        assert result["list"][0]["name"] == "Contract AI"
        assert result["list"][0]["assigned_at"] == 1893456000

    def test_list_my_apps_should_skip_unpublished_apps(self):
        account_id = uuid4()
        app = _app(status=AppStatus.DRAFT.value)
        assignment = _assignment(app_id=app.id, account_id=account_id, status="active")
        assignment.app = app
        service = MyAppService(session=_SessionStub([_QueryStub(all_result=[assignment])]))

        result = service.list_my_apps(account_id)

        assert result == {"list": []}

    def test_list_my_apps_should_expose_published_forked_apps(self):
        """商店添加（fork）且已发布的副本对用户可见，且不可编辑。"""
        account_id = uuid4()
        forked = _app(
            name="OCR Reader",
            account_id=account_id,
            status=AppStatus.PUBLISHED.value,
            original_app_id=uuid4(),
        )
        service = MyAppService(session=_SessionStub([_QueryStub(all_result=[]), _QueryStub(all_result=[forked])]))

        result = service.list_my_apps(account_id)

        assert len(result["list"]) == 1
        item = result["list"][0]
        assert item["source"] == "forked"
        assert item["status"] == AppStatus.PUBLISHED.value
        assert item["can_edit"] is False

    def test_list_my_apps_should_skip_draft_forked_apps(self):
        """草稿态 fork 副本不具备上架资格，不得出现在“我的应用”。"""
        account_id = uuid4()
        forked = _app(
            name="Draft Fork",
            account_id=account_id,
            status=AppStatus.DRAFT.value,
            original_app_id=uuid4(),
        )
        session = _SessionStub([_QueryStub(all_result=[]), _QueryStub(all_result=[forked])])
        service = MyAppService(session=session)

        result = service.list_my_apps(account_id)

        assert result == {"list": []}

    def test_list_my_apps_should_skip_offline_forked_apps(self):
        """下架态 fork 副本同样不得出现。"""
        account_id = uuid4()
        forked = _app(
            name="Offline Fork",
            account_id=account_id,
            status="offline",
            original_app_id=uuid4(),
        )
        service = MyAppService(session=_SessionStub([_QueryStub(all_result=[]), _QueryStub(all_result=[forked])]))

        result = service.list_my_apps(account_id)

        assert result == {"list": []}

    def test_list_my_apps_should_filter_forked_query_by_published_status(self):
        """fork 查询应在 DB 层按 published 过滤（而非取回后再筛）。"""
        account_id = uuid4()
        forked_query = _QueryStub(all_result=[])
        session = _SessionStub([_QueryStub(all_result=[]), forked_query])
        service = MyAppService(session=session)

        service.list_my_apps(account_id)

        filter_args = forked_query.filters[0][0]
        assert any(
            getattr(expr, "right", None) is not None
            and getattr(getattr(expr, "right", None), "value", None) == AppStatus.PUBLISHED.value
            for expr in filter_args
        ), "fork 查询必须包含 status == published 过滤条件"

    def test_get_assigned_app_should_return_app_for_active_assignment(self):
        account_id = uuid4()
        app = _app()
        assignment = _assignment(app_id=app.id, account_id=account_id, status="active")
        assignment.app = app
        service = MyAppService(session=_SessionStub([_QueryStub(one_or_none_result=assignment)]))

        result = service.get_assigned_app(account_id, app.id)

        assert result.id == app.id

    def test_get_assigned_app_should_raise_when_not_assigned(self):
        service = MyAppService(session=_SessionStub([_QueryStub(one_or_none_result=None)]))

        with pytest.raises(NotFoundException):
            service.get_assigned_app(uuid4(), uuid4())

    def test_get_assigned_app_should_reject_unpublished_app(self):
        account_id = uuid4()
        app = _app(status=AppStatus.DRAFT.value)
        assignment = _assignment(app_id=app.id, account_id=account_id, status="active")
        assignment.app = app
        service = MyAppService(session=_SessionStub([_QueryStub(one_or_none_result=assignment)]))

        with pytest.raises(FailException):
            service.get_assigned_app(account_id, app.id)


def test_my_app_resp_schema_should_expose_can_edit():
    """MyAppResp 必须声明 can_edit，否则 marshmallow dump 会丢弃 service 已返回的该字段。"""
    from internal.schema.my_app_schema import MyAppResp

    dumped = MyAppResp().dump(
        {
            "id": "app-1",
            "assignment_id": "asg-1",
            "name": "Contract AI",
            "icon": "",
            "description": "desc",
            "assigned_at": 1893456000,
            "source": "assigned",
            "status": "published",
            "can_edit": False,
        }
    )

    assert "can_edit" in dumped
    assert dumped["can_edit"] is False
