import math
from datetime import datetime
from uuid import uuid4

import pytest

from internal.exception import NotFoundException
from internal.model.showcase_entity import ShowcaseCase
from internal.service.showcase_service import ShowcaseService


class _QueryStub:
    def __init__(self, items=None, count_value=None):
        self._items = list(items or [])
        self._count_value = count_value
        self._offset = None
        self._limit = None
        self.filter_calls = 0
        self.order_calls = 0

    def _apply_expr(self, expr):
        op_name = getattr(getattr(expr, "operator", None), "__name__", "")
        if op_name != "eq":
            return
        col_name = getattr(getattr(expr, "left", None), "key", None)
        if col_name is None:
            return
        right = getattr(expr, "right", None)
        val = getattr(right, "effective_value", None)
        if val is None:
            val = getattr(right, "value", None)
        if val is None:
            return
        self._items = [it for it in self._items if getattr(it, col_name, None) == val]

    def filter(self, *args, **kwargs):
        self.filter_calls += 1
        for expr in args:
            self._apply_expr(expr)
        return self

    def order_by(self, *args, **kwargs):
        self.order_calls += 1
        return self

    def offset(self, n):
        self._offset = n or 0
        return self

    def limit(self, n):
        self._limit = n
        return self

    def count(self):
        if self._count_value is not None:
            return self._count_value
        return len(self._items)

    def all(self):
        items = list(self._items)
        if self._offset:
            items = items[self._offset:]
        if self._limit is not None:
            items = items[:self._limit]
        return items

    def one_or_none(self):
        return self._items[0] if self._items else None


class _SessionStub:
    def __init__(self, query_stub):
        self._query_stub = query_stub
        self.added = []
        self.committed = False
        self.flushed = False

    def query(self, model):
        return self._query_stub

    def add(self, obj):
        self.added.append(obj)
        return obj

    def flush(self):
        self.flushed = True

    def commit(self):
        self.committed = True


def _make_case(status="approved", **kwargs):
    defaults = dict(
        id=uuid4(),
        conversation_id=uuid4(),
        account_id=uuid4(),
        title="title",
        summary="summary",
        query="query",
        answer="answer",
        tags=["ai"],
        rating=5,
        status=status,
        reject_reason="",
        created_at=datetime(2024, 1, 1, 0, 0, 0),
        approved_at=datetime(2024, 1, 2, 0, 0, 0) if status == "approved" else None,
        approved_by=uuid4() if status == "approved" else None,
        updated_at=datetime(2024, 1, 3, 0, 0, 0),
    )
    defaults.update(kwargs)
    return ShowcaseCase(**defaults)


class TestShowcaseService:
    def test_create_case_should_persist_pending_case(self):
        session = _SessionStub(_QueryStub())
        service = ShowcaseService(session=session)

        account_id = uuid4()
        conversation_id = uuid4()
        result = service.create_case(
            account_id=account_id,
            conversation_id=conversation_id,
            title="好案例",
            summary="摘要",
            query="问题",
            answer="回答",
            tags=["ai", "demo"],
            rating=5,
        )

        assert len(session.added) == 1
        case = session.added[0]
        assert case.status == "pending"
        assert case.title == "好案例"
        assert case.tags == ["ai", "demo"]
        assert case.conversation_id == conversation_id
        assert case.account_id == account_id
        assert session.flushed is True
        assert session.committed is True
        assert result["status"] == "pending"
        assert result["title"] == "好案例"
        assert result["tags"] == ["ai", "demo"]
        assert result["rating"] == 5

    def test_create_case_should_default_rating_when_missing(self):
        session = _SessionStub(_QueryStub())
        service = ShowcaseService(session=session)

        result = service.create_case(
            account_id=uuid4(),
            conversation_id=uuid4(),
            title="t",
            summary="s",
            query="q",
            answer="a",
            rating=None,
        )

        assert session.added[0].rating == 5
        assert result["rating"] == 5

    def test_list_public_cases_should_return_only_approved(self):
        approved_a = _make_case(status="approved", title="A")
        approved_b = _make_case(status="approved", title="B")
        pending = _make_case(status="pending", title="P")
        rejected = _make_case(status="rejected", title="R")
        query_stub = _QueryStub(items=[approved_a, pending, approved_b, rejected])
        session = _SessionStub(query_stub)
        service = ShowcaseService(session=session)

        result = service.list_public_cases(page=1, per_page=20)

        assert query_stub.filter_calls >= 1
        assert [c["status"] for c in result["list"]] == ["approved", "approved"]
        assert [c["title"] for c in result["list"]] == ["A", "B"]
        assert result["paginator"]["total_record"] == 2
        assert result["paginator"]["total_page"] == 1
        assert result["paginator"]["current_page"] == 1
        assert result["paginator"]["page_size"] == 20

    def test_list_public_cases_should_apply_pagination(self):
        items = [_make_case(status="approved", title=str(i)) for i in range(5)]
        query_stub = _QueryStub(items=items)
        session = _SessionStub(query_stub)
        service = ShowcaseService(session=session)

        result = service.list_public_cases(page=2, per_page=2)

        assert len(result["list"]) == 2
        assert [c["title"] for c in result["list"]] == ["2", "3"]
        assert result["paginator"]["total_record"] == 5
        assert result["paginator"]["total_page"] == math.ceil(5 / 2)
        assert result["paginator"]["current_page"] == 2
        assert result["paginator"]["page_size"] == 2

    def test_list_public_cases_should_apply_tag_and_keyword_filters(self):
        query_stub = _QueryStub(items=[_make_case(status="approved")])
        session = _SessionStub(query_stub)
        service = ShowcaseService(session=session)

        service.list_public_cases(page=1, per_page=20, tag="ai", keyword="好")

        assert query_stub.filter_calls == 3

    def test_get_case_should_return_approved_case(self):
        case = _make_case(status="approved", title="X")
        session = _SessionStub(_QueryStub(items=[case]))
        service = ShowcaseService(session=session)

        result = service.get_case(case.id)

        assert result["id"] == str(case.id)
        assert result["status"] == "approved"
        assert result["title"] == "X"

    def test_get_case_should_raise_for_non_approved(self):
        case = _make_case(status="pending")
        session = _SessionStub(_QueryStub(items=[case]))
        service = ShowcaseService(session=session)

        with pytest.raises(NotFoundException):
            service.get_case(case.id)

    def test_get_case_should_raise_when_not_found(self):
        session = _SessionStub(_QueryStub(items=[]))
        service = ShowcaseService(session=session)

        with pytest.raises(NotFoundException):
            service.get_case(uuid4())

    def test_admin_list_cases_should_return_all_when_status_all(self):
        approved = _make_case(status="approved")
        pending = _make_case(status="pending")
        rejected = _make_case(status="rejected")
        query_stub = _QueryStub(items=[approved, pending, rejected])
        session = _SessionStub(query_stub)
        service = ShowcaseService(session=session)

        result = service.admin_list_cases(page=1, per_page=20, status="all")

        assert query_stub.filter_calls == 0
        assert len(result["list"]) == 3
        assert result["paginator"]["total_record"] == 3

    def test_admin_list_cases_should_filter_by_status(self):
        approved = _make_case(status="approved")
        pending = _make_case(status="pending")
        rejected = _make_case(status="rejected")
        query_stub = _QueryStub(items=[approved, pending, rejected])
        session = _SessionStub(query_stub)
        service = ShowcaseService(session=session)

        result = service.admin_list_cases(page=1, per_page=20, status="pending")

        assert query_stub.filter_calls == 1
        assert [c["status"] for c in result["list"]] == ["pending"]
        assert result["paginator"]["total_record"] == 1

    def test_approve_case_should_mark_approved(self):
        case = _make_case(status="pending", reject_reason="bad")
        session = _SessionStub(_QueryStub(items=[case]))
        service = ShowcaseService(session=session)
        admin_id = uuid4()

        result = service.approve_case(case.id, admin_id=admin_id)

        assert case.status == "approved"
        assert case.approved_at is not None
        assert case.approved_by == admin_id
        assert case.reject_reason == ""
        assert session.committed is True
        assert result["status"] == "approved"
        assert result["approved_by"] == str(admin_id)

    def test_approve_case_should_raise_when_not_found(self):
        session = _SessionStub(_QueryStub(items=[]))
        service = ShowcaseService(session=session)

        with pytest.raises(NotFoundException):
            service.approve_case(uuid4(), admin_id=uuid4())

    def test_reject_case_should_mark_rejected_with_reason(self):
        case = _make_case(status="pending")
        session = _SessionStub(_QueryStub(items=[case]))
        service = ShowcaseService(session=session)
        admin_id = uuid4()

        result = service.reject_case(case.id, admin_id=admin_id, reason="内容不合适")

        assert case.status == "rejected"
        assert case.reject_reason == "内容不合适"
        assert case.approved_by == admin_id
        assert session.committed is True
        assert result["status"] == "rejected"
        assert result["reject_reason"] == "内容不合适"

    def test_offline_case_should_mark_offline(self):
        case = _make_case(status="approved")
        session = _SessionStub(_QueryStub(items=[case]))
        service = ShowcaseService(session=session)
        admin_id = uuid4()

        result = service.offline_case(case.id, admin_id=admin_id)

        assert case.status == "offline"
        assert session.committed is True
        assert result["status"] == "offline"

    def test_offline_case_should_raise_when_not_found(self):
        session = _SessionStub(_QueryStub(items=[]))
        service = ShowcaseService(session=session)

        with pytest.raises(NotFoundException):
            service.offline_case(uuid4(), admin_id=uuid4())
