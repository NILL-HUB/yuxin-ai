from types import SimpleNamespace

import pytest
from sqlalchemy.dialects import postgresql

from internal.exception import ForbiddenException, ValidateErrorException
from internal.model import RecycleBin
from internal.service import recycle_bin_service
from internal.service.recycle_bin_service import RecycleBinService


class _Query:
    def __init__(self, items=None):
        self.filters = []
        self.items = items or []

    def filter(self, *args):
        self.filters.extend(args)
        return self

    def order_by(self, *_args):
        return self

    def offset(self, _offset):
        return self

    def limit(self, _limit):
        return self

    def count(self):
        return len(self.items)

    def all(self):
        return self.items


class _Session:
    def __init__(self, items=None):
        self.query_result = _Query(items)

    def query(self, *_args):
        return self.query_result


def test_list_user_items_only_exposes_user_visible_resource_types(monkeypatch):
    session = _Session()
    monkeypatch.setattr(
        recycle_bin_service,
        "db",
        SimpleNamespace(session=session),
    )

    RecycleBinService().list_user_items(account_id="acc-1")

    base_filters = session.query_result.filters[:3]
    assert len(base_filters) == 3
    type_expr = base_filters[2].compile(
        dialect=postgresql.dialect(),
        compile_kwargs={"literal_binds": True},
    )
    assert "recycle_bin.resource_type IN" in str(type_expr)
    for resource_type in RecycleBinService.USER_VISIBLE_RESOURCE_TYPES:
        assert resource_type in str(type_expr)
    assert "app" not in str(type_expr)


def test_delete_resource_rejects_user_source_for_admin_only_type(monkeypatch):
    monkeypatch.setattr(
        recycle_bin_service,
        "snapshot_resource",
        lambda *_args, **_kwargs: {},
    )

    with pytest.raises(ValidateErrorException):
        RecycleBinService().delete_resource(
            resource_type="app",
            resource_id="app-1",
            deleted_by="acc-1",
            deleted_by_type="user",
        )

    with pytest.raises(ValidateErrorException):
        RecycleBinService().delete_resource(
            resource_type="workflow",
            resource_id="wf-1",
            deleted_by="acc-1",
            deleted_by_type="agent",
        )


def test_check_user_owned_rejects_admin_only_resource_type():
    service = RecycleBinService()
    item = SimpleNamespace(
        id=1,
        resource_type="app",
        deleted_by_type="user",
        deleted_by="acc-1",
    )

    with pytest.raises(ForbiddenException):
        service._check_user_owned(item, "acc-1")


def test_check_user_owned_rejects_other_account_and_admin_source():
    service = RecycleBinService()
    user_item = SimpleNamespace(
        id=2,
        resource_type="memory",
        deleted_by_type="user",
        deleted_by="acc-1",
    )
    with pytest.raises(ForbiddenException):
        service._check_user_owned(user_item, "acc-2")

    admin_item = SimpleNamespace(
        id=3,
        resource_type="knowledge_base",
        deleted_by_type="admin",
        deleted_by="admin-1",
    )
    with pytest.raises(ForbiddenException):
        service._check_user_owned(admin_item, "admin-1")


def test_check_user_owned_allows_own_user_visible_item():
    service = RecycleBinService()
    item = SimpleNamespace(
        id=4,
        resource_type="knowledge_document",
        deleted_by_type="agent",
        deleted_by="acc-1",
    )

    service._check_user_owned(item, "acc-1")
