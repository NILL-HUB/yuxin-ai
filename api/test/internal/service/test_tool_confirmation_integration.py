from contextlib import contextmanager
from types import SimpleNamespace
from uuid import uuid4

from internal.entity.runtime_tool_entity import (
    RuntimeToolCallRequest,
    RuntimeToolDescriptor,
)
from internal.service.tool_confirmation_service import ToolConfirmationService
from internal.service.tool_invocation_audit_service import ToolInvocationAuditService
from internal.service.tool_invoker_service import (
    ToolInvokerService,
    build_non_interruptible_write_audit_hint,
    is_non_interruptible_write,
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


class _AuditRecorder:
    def __init__(self):
        self.calls = []

    def record(self, **kwargs):
        self.calls.append(kwargs)
        return SimpleNamespace(id=uuid4())


def _high_risk_confirmation(account_id):
    return SimpleNamespace(
        id=uuid4(),
        owner_account_id=account_id,
        status="pending",
        tool_name="delete_user",
        risk_level="high",
        tool_input={"user_id": "u1"},
        target_system="crm",
        target_environment="production",
        execution_summary="删除用户",
        impact_scope="用户数据不可恢复",
        rollback_strategy="从备份恢复",
        audit_hint="操作已生效或可能已生效，请检查目标系统状态",
    )


class TestToolConfirmationExtendedFieldsIntegration:
    def test_create_confirmation_should_persist_all_extended_fields(self, monkeypatch):
        account_id = uuid4()
        service = ToolConfirmationService(
            db=_fake_db(_SessionStub()),
            tool_invocation_audit_service=_AuditRecorder(),
        )
        captured = {}

        def fake_create(_model, **kwargs):
            captured.update(kwargs)
            return SimpleNamespace(id=uuid4(), **kwargs)

        monkeypatch.setattr(service, "create", fake_create)

        service.create_confirmation(
            account=SimpleNamespace(id=account_id),
            tool_name="execute_sql",
            risk_level="high",
            tool_input={"sql": "DELETE FROM users WHERE id=1"},
            spent_credits=8,
            target_system="mysql",
            target_environment="production",
            execution_summary="删除用户记录",
            impact_scope="生产库用户表",
            rollback_strategy="通过 binlog 回放恢复",
        )

        assert captured["target_system"] == "mysql"
        assert captured["target_environment"] == "production"
        assert captured["execution_summary"] == "删除用户记录"
        assert captured["impact_scope"] == "生产库用户表"
        assert captured["rollback_strategy"] == "通过 binlog 回放恢复"
        assert (
            captured["audit_hint"]
            == "操作已生效或可能已生效，请检查目标系统状态"
        )


class TestToolConfirmationAuditIntegration:
    def test_confirm_flow_should_write_audit_log_with_account_tool_risk_input_decision(self):
        account_id = uuid4()
        confirmation = _high_risk_confirmation(account_id)
        recorder = _AuditRecorder()
        service = ToolConfirmationService(
            db=_fake_db(_SessionStub([_QueryStub(one_or_none_result=confirmation)])),
            tool_invocation_audit_service=recorder,
        )

        result = service.confirm(confirmation.id, SimpleNamespace(id=account_id))

        assert result.status == "confirmed"
        assert len(recorder.calls) == 1
        call = recorder.calls[0]
        assert call["account_id"] == str(account_id)
        assert call["tool_name"] == "delete_user"
        assert call["risk_level"] == "high"
        assert call["input_data"] == {"user_id": "u1"}
        assert call["action"] == "confirm"
        assert call["decision"] == "approved"
        assert call["commit"] is False

    def test_cancel_flow_should_write_audit_log_with_cancelled_decision(self):
        account_id = uuid4()
        confirmation = _high_risk_confirmation(account_id)
        recorder = _AuditRecorder()
        service = ToolConfirmationService(
            db=_fake_db(_SessionStub([_QueryStub(one_or_none_result=confirmation)])),
            tool_invocation_audit_service=recorder,
        )

        result = service.cancel(confirmation.id, SimpleNamespace(id=account_id))

        assert result.status == "cancelled"
        assert len(recorder.calls) == 1
        call = recorder.calls[0]
        assert call["action"] == "cancel"
        assert call["decision"] == "cancelled"
        assert call["tool_name"] == "delete_user"

    def test_audit_service_record_should_persist_after_data_with_required_fields(self, monkeypatch):
        persisted = []

        def fake_record_for_tool_invocation(self, *, account_id, action, resource_type,
                                            resource_id="", before_data=None,
                                            after_data=None, commit=True):
            persisted.append(
                {
                    "account_id": account_id,
                    "action": action,
                    "resource_type": resource_type,
                    "resource_id": resource_id,
                    "after_data": after_data,
                    "commit": commit,
                }
            )
            return SimpleNamespace(id=uuid4())

        monkeypatch.setattr(
            "internal.service.tool_invocation_audit_service.AuditLogService"
            ".record_for_tool_invocation",
            fake_record_for_tool_invocation,
        )

        ToolInvocationAuditService().record(
            account_id="account-1",
            tool_name="delete_user",
            risk_level="high",
            input_data={"user_id": "u1"},
            action="confirm",
            decision="approved",
            resource_id="conf-1",
            commit=False,
        )

        assert len(persisted) == 1
        record = persisted[0]
        assert record["account_id"] == "account-1"
        assert record["action"] == "confirm"
        assert record["resource_type"] == "tool"
        assert record["resource_id"] == "conf-1"
        assert record["commit"] is False
        after_data = record["after_data"]
        assert after_data["account_id"] == "account-1"
        assert after_data["tool_name"] == "delete_user"
        assert after_data["risk_level"] == "high"
        assert after_data["decision"] == "approved"
        assert after_data["input"] == {"keys": ["user_id"], "redacted_keys": []}


class TestNonInterruptibleWriteAuditHintIntegration:
    def test_is_non_interruptible_write_should_detect_high_risk(self):
        assert is_non_interruptible_write(
            risk_level="high", tool_input={"query": "select 1"}
        ) is True

    def test_is_non_interruptible_write_should_detect_write_keywords(self):
        assert is_non_interruptible_write(
            risk_level="medium", tool_input={"sql": "DELETE FROM orders"}
        ) is True

    def test_is_non_interruptible_write_should_be_false_for_safe_read(self):
        assert is_non_interruptible_write(
            risk_level="safe", tool_input={"query": "search docs"}
        ) is False

    def test_build_audit_hint_should_return_standard_message_for_high_risk(self):
        hint = build_non_interruptible_write_audit_hint(
            risk_level="high", tool_input={"user_id": "u1"}
        )
        assert hint == "操作已生效或可能已生效，请检查目标系统状态"

    def test_build_audit_hint_should_return_empty_for_safe_read(self):
        hint = build_non_interruptible_write_audit_hint(
            risk_level="safe", tool_input={"query": "search docs"}
        )
        assert hint == ""

    def test_tool_invoker_should_attach_audit_hint_for_high_risk_success(self):
        tool = RuntimeToolDescriptor(
            tool_id="provider-1:write_record",
            runtime_name="write_record",
            name="write_record",
            description="write record",
            source_type="mcp",
            provider_id="provider-1",
            provider_name="Records",
            input_schema=[{"name": "sql", "type": "str", "required": True}],
            metadata={
                "risk_level": "high",
                "permission_scope": "public",
                "user_scope": "system",
                "owner": "system",
            },
            audit_context={
                "tool_id": "provider-1:write_record",
                "runtime_name": "write_record",
                "source_type": "mcp",
            },
        )
        request = RuntimeToolCallRequest(
            runtime_name="write_record",
            arguments={"sql": "UPDATE accounts SET balance=0"},
            account_id="account-1",
            agent_id="agent-1",
            request_id="request-1",
        )

        result = ToolInvokerService().invoke(
            mounted_tools=[tool],
            request=request,
            executors={"write_record": lambda arguments, tool: {"ok": True}},
            confirmed=True,
        )

        assert result.success is True
        assert (
            result.audit_payload["audit_hint"]
            == "操作已生效或可能已生效，请检查目标系统状态"
        )

    def test_tool_invoker_should_not_attach_audit_hint_for_safe_tool(self):
        tool = RuntimeToolDescriptor(
            tool_id="provider-1:search_docs",
            runtime_name="search_docs",
            name="search_docs",
            description="search docs",
            source_type="mcp",
            provider_id="provider-1",
            provider_name="Docs",
            input_schema=[{"name": "query", "type": "str", "required": True}],
            metadata={
                "risk_level": "safe",
                "permission_scope": "public",
                "user_scope": "system",
                "owner": "system",
            },
            audit_context={
                "tool_id": "provider-1:search_docs",
                "runtime_name": "search_docs",
                "source_type": "mcp",
            },
        )
        request = RuntimeToolCallRequest(
            runtime_name="search_docs",
            arguments={"query": "phase 11 overview"},
            account_id="account-1",
            agent_id="agent-1",
            request_id="request-1",
        )

        result = ToolInvokerService().invoke(
            mounted_tools=[tool],
            request=request,
            executors={"search_docs": lambda arguments, tool: {"items": []}},
        )

        assert result.success is True
        assert "audit_hint" not in result.audit_payload
