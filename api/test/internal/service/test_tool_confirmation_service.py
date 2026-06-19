from contextlib import contextmanager
from types import SimpleNamespace
from uuid import uuid4

import pytest

from internal.exception import ForbiddenException, NotFoundException
from internal.service.tool_confirmation_service import ToolConfirmationService


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


class _AuditRecorder:
    def __init__(self):
        self.calls = []

    def record(self, **kwargs):
        self.calls.append(kwargs)
        return SimpleNamespace(id=uuid4())


def test_create_confirmation_should_store_extended_fields(monkeypatch):
    account_id = uuid4()
    service = ToolConfirmationService(db=_fake_db(_SessionStub()))
    captured = {}

    def fake_create(_model, **kwargs):
        captured.update(kwargs)
        return SimpleNamespace(id=uuid4(), **kwargs)

    monkeypatch.setattr(service, "create", fake_create)

    result = service.create_confirmation(
        account=SimpleNamespace(id=account_id),
        tool_name="execute_sql",
        risk_level="high",
        tool_input={"sql": "DELETE FROM users"},
        spent_credits=8,
        target_system="mysql",
        target_environment="production",
        execution_summary="删除用户记录",
        impact_scope="生产库用户表",
        rollback_strategy="通过 binlog 回放恢复",
        audit_hint="手动提示",
    )

    assert captured["target_system"] == "mysql"
    assert captured["target_environment"] == "production"
    assert captured["execution_summary"] == "删除用户记录"
    assert captured["impact_scope"] == "生产库用户表"
    assert captured["rollback_strategy"] == "通过 binlog 回放恢复"
    assert captured["audit_hint"] == "手动提示"
    assert result.target_system == "mysql"
    assert result.target_environment == "production"


def test_create_confirmation_should_auto_set_audit_hint_for_high_risk(monkeypatch):
    account_id = uuid4()
    service = ToolConfirmationService(db=_fake_db(_SessionStub()))
    captured = {}

    def fake_create(_model, **kwargs):
        captured.update(kwargs)
        return SimpleNamespace(id=uuid4(), **kwargs)

    monkeypatch.setattr(service, "create", fake_create)

    service.create_confirmation(
        account=SimpleNamespace(id=account_id),
        tool_name="delete_user",
        risk_level="high",
        tool_input={"user_id": "u1"},
    )

    assert (
        captured["audit_hint"]
        == "操作已生效或可能已生效，请检查目标系统状态"
    )


def test_create_confirmation_should_auto_set_audit_hint_for_write_keywords(monkeypatch):
    account_id = uuid4()
    service = ToolConfirmationService(db=_fake_db(_SessionStub()))
    captured = {}

    def fake_create(_model, **kwargs):
        captured.update(kwargs)
        return SimpleNamespace(id=uuid4(), **kwargs)

    monkeypatch.setattr(service, "create", fake_create)

    service.create_confirmation(
        account=SimpleNamespace(id=account_id),
        tool_name="run_job",
        risk_level="medium",
        tool_input={"command": "delete cache entries"},
    )

    assert (
        captured["audit_hint"]
        == "操作已生效或可能已生效，请检查目标系统状态"
    )


def test_create_confirmation_should_keep_empty_audit_hint_for_safe_read(monkeypatch):
    account_id = uuid4()
    service = ToolConfirmationService(db=_fake_db(_SessionStub()))
    captured = {}

    def fake_create(_model, **kwargs):
        captured.update(kwargs)
        return SimpleNamespace(id=uuid4(), **kwargs)

    monkeypatch.setattr(service, "create", fake_create)

    service.create_confirmation(
        account=SimpleNamespace(id=account_id),
        tool_name="search_docs",
        risk_level="medium",
        tool_input={"query": "phase 11 overview"},
    )

    assert captured["audit_hint"] == ""


def test_confirm_should_record_audit_with_approved_decision():
    account_id = uuid4()
    confirmation = SimpleNamespace(
        id=uuid4(),
        owner_account_id=account_id,
        status="pending",
        tool_name="delete_user",
        risk_level="high",
        tool_input={"user_id": "u1"},
    )
    recorder = _AuditRecorder()
    service = ToolConfirmationService(
        db=_fake_db(_SessionStub([_QueryStub(one_or_none_result=confirmation)])),
        tool_invocation_audit_service=recorder,
    )

    result = service.confirm(confirmation.id, SimpleNamespace(id=account_id))

    assert result.status == "confirmed"
    assert len(recorder.calls) == 1
    call = recorder.calls[0]
    assert call["action"] == "confirm"
    assert call["decision"] == "approved"
    assert call["tool_name"] == "delete_user"
    assert call["risk_level"] == "high"
    assert call["account_id"] == str(account_id)
    assert call["input_data"] == {"user_id": "u1"}
    assert call["commit"] is False


def test_cancel_should_record_audit_with_cancelled_decision():
    account_id = uuid4()
    confirmation = SimpleNamespace(
        id=uuid4(),
        owner_account_id=account_id,
        status="pending",
        tool_name="delete_user",
        risk_level="high",
        tool_input={"user_id": "u1"},
    )
    recorder = _AuditRecorder()
    service = ToolConfirmationService(
        db=_fake_db(_SessionStub([_QueryStub(one_or_none_result=confirmation)])),
        tool_invocation_audit_service=recorder,
    )

    result = service.cancel(confirmation.id, SimpleNamespace(id=account_id))

    assert result.status == "cancelled"
    assert len(recorder.calls) == 1
    assert recorder.calls[0]["action"] == "cancel"
    assert recorder.calls[0]["decision"] == "cancelled"
    assert recorder.calls[0]["tool_name"] == "delete_user"
