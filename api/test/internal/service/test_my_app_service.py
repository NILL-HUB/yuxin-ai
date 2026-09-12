from datetime import datetime
from uuid import uuid4

import pytest

from internal.entity.app_entity import AppStatus
from internal.exception import FailException, NotFoundException
from internal.model.app import App
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
        "name": "Forked AI",
        "icon": "🤖",
        "description": "AI app added from store",
        "status": AppStatus.PUBLISHED.value,
        "is_public": False,
        "published_at": datetime(2030, 1, 1, 0, 0, 0),
    }
    defaults.update(kwargs)
    return App(**defaults)


class TestMyAppService:
    def test_list_my_apps_should_return_published_forked_apps(self):
        account_id = uuid4()
        forked = _app(
            name="OCR Reader",
            account_id=account_id,
            status=AppStatus.PUBLISHED.value,
            original_app_id=uuid4(),
        )
        service = MyAppService(session=_SessionStub([_QueryStub(all_result=[forked])]))

        result = service.list_my_apps(account_id)

        assert len(result["list"]) == 1
        item = result["list"][0]
        assert item["id"] == str(forked.id)
        assert item["source"] == "forked"
        assert item["status"] == AppStatus.PUBLISHED.value
        assert item["can_edit"] is False
        assert "assignment_id" not in item

    def test_list_my_apps_should_skip_draft_forked_apps(self):
        """草稿态 fork 副本不具备上架资格，不得出现在“我的应用”。"""
        account_id = uuid4()
        forked = _app(
            name="Draft Fork",
            account_id=account_id,
            status=AppStatus.DRAFT.value,
            original_app_id=uuid4(),
        )
        service = MyAppService(session=_SessionStub([_QueryStub(all_result=[forked])]))

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
        service = MyAppService(session=_SessionStub([_QueryStub(all_result=[forked])]))

        result = service.list_my_apps(account_id)

        assert result == {"list": []}

    def test_get_user_app_should_return_published_forked_app(self):
        account_id = uuid4()
        forked = _app(
            account_id=account_id,
            status=AppStatus.PUBLISHED.value,
            original_app_id=uuid4(),
        )
        service = MyAppService(session=_SessionStub([_QueryStub(one_or_none_result=forked)]))

        result = service.get_user_app(account_id, forked.id)

        assert result.id == forked.id

    def test_get_user_app_should_reject_draft_forked_app(self):
        account_id = uuid4()
        forked = _app(
            account_id=account_id,
            status=AppStatus.DRAFT.value,
            original_app_id=uuid4(),
        )
        service = MyAppService(session=_SessionStub([_QueryStub(one_or_none_result=forked)]))

        with pytest.raises(FailException):
            service.get_user_app(account_id, forked.id)

    def test_get_user_app_should_raise_when_absent(self):
        service = MyAppService(session=_SessionStub([_QueryStub(one_or_none_result=None)]))

        with pytest.raises(NotFoundException):
            service.get_user_app(uuid4(), uuid4())


def test_my_app_resp_schema_should_not_expose_assignment_id():
    """移除管理员分配后，MyAppResp 不应再声明 assignment_id。"""
    from internal.schema.my_app_schema import MyAppResp

    dumped = MyAppResp().dump(
        {
            "id": "app-1",
            "name": "Contract AI",
            "icon": "",
            "description": "desc",
            "created_at": 1893456000,
            "source": "forked",
            "status": "published",
            "can_edit": False,
        }
    )

    assert "assignment_id" not in dumped
    assert dumped["created_at"] == 1893456000
    assert dumped["can_edit"] is False
