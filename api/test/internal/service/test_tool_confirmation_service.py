from contextlib import contextmanager
from types import SimpleNamespace
from uuid import uuid4

import pytest

from internal.exception import ForbiddenException, NotFoundException
from internal.service.tool_confirmation_service import (
    ToolConfirmationService,
    ToolInvoker,
)


class _QueryStub:
    def __init__(self, *, one_or_none_result=None):
        self._one_or_none_result = one_or_none_result

    def filter(self, *_args, **_kwargs):
        return self

    def filter_by(self, **_kwargs):
        return self

    def one_or_none(self):
        return self._one_or_none_result


class _SessionStub:
    def __init__(self, queries=None):
        self._queries = list(queries or [])

    def query(self, *_args, **_kwargs):
        if self._queries:
            return self._queries.pop(0)
        return _QueryStub()


@contextmanager
def _auto_commit():
    yield


def _fake_db(session):
    return SimpleNamespace(session=session, auto_commit=lambda: _auto_commit())


def test_create_confirmation_should_start_pending(monkeypatch):
    account_id = uuid4()
    service = ToolConfirmationService(db=_fake_db(_SessionStub()))
    monkeypatch.setattr(service, "create", lambda _model, **kwargs: SimpleNamespace(id=uuid4(), **kwargs))

    result = service.create_confirmation(
        account=SimpleNamespace(id=account_id),
        tool_name="delete_user",
        risk_level="high",
        tool_input={"user_id": "u1"},
        spent_credits=12,
    )

    assert result.owner_account_id == account_id
    assert result.status == "pending"
    assert result.tool_name == "delete_user"
    assert result.spent_credits == 12


def test_confirm_and_cancel_should_only_allow_owner():
    account_id = uuid4()
    confirmation = SimpleNamespace(
        id=uuid4(), owner_account_id=account_id, status="pending"
    )
    service = ToolConfirmationService(
        db=_fake_db(_SessionStub([_QueryStub(one_or_none_result=confirmation)]))
    )

    assert service.confirm(confirmation.id, SimpleNamespace(id=account_id)).status == "confirmed"

    with pytest.raises(NotFoundException):
        service.cancel(confirmation.id, SimpleNamespace(id=uuid4()))


def test_tool_invoker_should_reject_high_risk_without_confirmed_confirmation():
    invoker = ToolInvoker()

    with pytest.raises(ForbiddenException):
        invoker.invoke(
            tool={"name": "delete_user", "metadata": {"risk_level": "high"}},
            tool_input={"user_id": "u1"},
            confirmation=None,
        )


def test_tool_invoker_should_execute_when_confirmation_confirmed():
    executed = []
    invoker = ToolInvoker(
        executor=lambda tool, tool_input: executed.append((tool, tool_input)) or {"ok": True}
    )

    result = invoker.invoke(
        tool={"name": "delete_user", "metadata": {"risk_level": "high"}},
        tool_input={"user_id": "u1"},
        confirmation=SimpleNamespace(status="confirmed"),
    )

    assert result == {"ok": True}
    assert executed[0][0]["name"] == "delete_user"
