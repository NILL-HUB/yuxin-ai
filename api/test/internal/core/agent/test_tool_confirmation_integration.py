from contextlib import contextmanager
from types import SimpleNamespace
from uuid import uuid4

from internal.core.agent.entities.tool_policy_entity import ToolPolicy
from internal.core.agent.entities.queue_entity import QueueEvent
from internal.core.agent.agents.function_call_agent import FunctionCallAgent
from internal.extension.database_extension import db


class _QueryStub:
    def __init__(self, *, one_or_none_result=None):
        self._one_or_none_result = one_or_none_result

    def filter(self, *_args, **_kwargs):
        return self

    def filter_by(self, **_kwargs):
        return self

    def one_or_none(self):
        return self._one_or_none_result


class TestToolConfirmationIntegration:
    def test_queue_event_should_include_tool_confirmation_required(self):
        assert QueueEvent.TOOL_CONFIRMATION_REQUIRED.value == "tool_confirmation_required"

    def test_os_file_task_is_high_risk(self):
        policy = ToolPolicy()
        assert policy.is_high_risk_tool("os_file_task") is True
        assert policy.is_high_risk_tool("run_os_task") is True

    def test_os_file_task_confirmation_summary_is_human_readable(self):
        patch_summary = FunctionCallAgent._build_confirmation_summary(
            "os_file_task",
            {"op": "patch", "patch": "*** Begin Patch\n*** End Patch\n"},
        )
        read_summary = FunctionCallAgent._build_confirmation_summary(
            "os_file_task",
            {"op": "read", "path": "C:/tmp/a.txt"},
        )
        assert "V4A 补丁" in patch_summary
        assert "读取文件" in read_summary
        assert "approval_token" not in patch_summary + read_summary

    def test_wait_for_confirmation_returns_redirect_when_correction_sent(self, monkeypatch):
        account_id = uuid4()
        confirmation_id = uuid4()
        confirmation = SimpleNamespace(
            id=confirmation_id,
            owner_account_id=account_id,
            status="pending",
        )

        @contextmanager
        def _fake_auto_commit():
            session = SimpleNamespace(
                query=lambda _model: _QueryStub(one_or_none_result=confirmation)
            )
            yield session

        monkeypatch.setattr(db, "sync_auto_commit", _fake_auto_commit)
        monkeypatch.setattr(
            "internal.core.agent.agents.function_call_agent._consume_redirect",
            lambda _cid: "只清理回收站",
        )
        agent = SimpleNamespace(
            _CONFIRMATION_WAIT_SECONDS=10,
            _CONFIRMATION_POLL_INTERVAL_SECONDS=0.01,
            _update_confirmation_summary=lambda *_a, **_kw: None,
        )

        result = FunctionCallAgent._wait_for_confirmation(
            agent,
            confirmation_id,
            account_id=account_id,
        )

        assert result.startswith("redirect:")
        assert result == "redirect:只清理回收站"

    def test_create_tool_confirmation_should_use_agent_config_user_id(self, monkeypatch):
        captured = {}

        @contextmanager
        def _fake_auto_commit():
            session = SimpleNamespace(add=lambda confirmation: captured.update(confirmation=confirmation))
            yield session

        monkeypatch.setattr(db, "sync_auto_commit", _fake_auto_commit)
        user_id = uuid4()
        agent = SimpleNamespace(agent_config=SimpleNamespace(user_id=user_id))
        state = SimpleNamespace(user_id=None, account_id=None)
        tool_call = {
            "name": "run_os_task",
            "args": {"task": "清理 C 盘垃圾", "mode": "preview"},
            "id": "call-1",
        }

        result = FunctionCallAgent._create_tool_confirmation(
            agent,
            state,
            tool_call,
            ToolPolicy(),
        )

        assert result is not None
        assert captured["confirmation"].owner_account_id == user_id
        assert captured["confirmation"].tool_name == "run_os_task"

    def test_wait_for_confirmation_should_resume_after_user_confirms(self, monkeypatch):
        account_id = uuid4()
        confirmation = SimpleNamespace(
            id=uuid4(),
            owner_account_id=account_id,
            status="confirmed",
        )

        @contextmanager
        def _fake_auto_commit():
            session = SimpleNamespace(
                query=lambda _model: _QueryStub(one_or_none_result=confirmation)
            )
            yield session

        monkeypatch.setattr(db, "sync_auto_commit", _fake_auto_commit)
        agent = SimpleNamespace(
            _CONFIRMATION_WAIT_SECONDS=10,
            _CONFIRMATION_POLL_INTERVAL_SECONDS=0.01,
        )

        result = FunctionCallAgent._wait_for_confirmation(
            agent,
            confirmation.id,
            account_id=account_id,
        )

        assert result == "confirmed"

    def test_wait_for_confirmation_should_timeout_when_user_does_not_respond(self, monkeypatch):
        confirmation = SimpleNamespace(status="pending")

        @contextmanager
        def _fake_auto_commit():
            session = SimpleNamespace(
                query=lambda _model: _QueryStub(one_or_none_result=confirmation)
            )
            yield session

        monkeypatch.setattr(db, "sync_auto_commit", _fake_auto_commit)
        agent = SimpleNamespace(
            _CONFIRMATION_WAIT_SECONDS=10,
            _CONFIRMATION_POLL_INTERVAL_SECONDS=0.01,
        )

        result = FunctionCallAgent._wait_for_confirmation(
            agent,
            uuid4(),
            account_id=uuid4(),
            timeout_seconds=0.02,
            poll_interval=0.01,
        )

        assert result == "timeout"

    def test_wait_for_confirmation_should_expire_scoped_session_before_polling(self, monkeypatch):
        confirmation = SimpleNamespace(status="confirmed")
        expire_calls = []

        class _SessionStub:
            def expire_all(self):
                expire_calls.append(True)

            def query(self, _model):
                return _QueryStub(one_or_none_result=confirmation)

        @contextmanager
        def _fake_auto_commit():
            yield _SessionStub()

        monkeypatch.setattr(db, "sync_auto_commit", _fake_auto_commit)
        agent = SimpleNamespace(
            _CONFIRMATION_WAIT_SECONDS=10,
            _CONFIRMATION_POLL_INTERVAL_SECONDS=0.01,
        )

        result = FunctionCallAgent._wait_for_confirmation(
            agent,
            uuid4(),
            account_id=uuid4(),
        )

        assert result == "confirmed"
        assert expire_calls


    def test_tool_policy_should_identify_dangerous_tools(self):
        policy = ToolPolicy()
        assert policy.is_dangerous_tool("drop_table") is True
        assert policy.is_dangerous_tool("format_disk") is True
        assert policy.is_dangerous_tool("execute_shell") is True
        assert policy.is_dangerous_tool("safe_tool") is False
        assert policy.is_dangerous_tool("") is False
        assert policy.is_dangerous_tool(None) is False

    def test_tool_policy_should_identify_high_risk_tools(self):
        policy = ToolPolicy()
        assert policy.is_high_risk_tool("send_email") is True
        assert policy.is_high_risk_tool("execute_sql") is True
        assert policy.is_high_risk_tool("deploy_application") is True
        assert policy.is_high_risk_tool("delete_resource") is True
        assert policy.is_high_risk_tool("modify_billing") is True
        assert policy.is_high_risk_tool("transfer_funds") is True
        assert policy.is_high_risk_tool("execute_code") is True
        assert policy.is_high_risk_tool("browser_action") is True
        assert policy.is_high_risk_tool("computer_action") is True
        assert policy.is_high_risk_tool("safe_tool") is False
        assert policy.is_high_risk_tool("") is False

    def test_tool_policy_should_not_treat_safe_tool_as_dangerous(self):
        policy = ToolPolicy()
        assert policy.is_dangerous_tool("dataset_retrieval") is False
        assert policy.is_high_risk_tool("dataset_retrieval") is False

    def test_tool_policy_high_risk_and_dangerous_should_be_disjoint(self):
        policy = ToolPolicy()
        for name in policy.high_risk_tool_names:
            assert policy.is_dangerous_tool(name) is False
        for name in policy.dangerous_tool_names:
            assert policy.is_high_risk_tool(name) is False

    def test_risk_level_should_include_sensitive_and_dangerous(self):
        from internal.entity.tool_inventory_entity import RiskLevel
        assert RiskLevel.DANGEROUS.value == "dangerous"
        assert RiskLevel.SENSITIVE.value == "sensitive"
        assert RiskLevel.SAFE.value == "safe"
        assert RiskLevel.LOW.value == "low"
        assert RiskLevel.MEDIUM.value == "medium"
        assert RiskLevel.HIGH.value == "high"

    def test_tool_invoker_security_error_should_reject_dangerous(self):
        from internal.entity.tool_inventory_entity import RiskLevel
        from internal.service.tool_invoker_service import ToolInvokerService

        tool = SimpleNamespace(metadata={"risk_level": RiskLevel.DANGEROUS.value, "user_scope": "system"})
        request = SimpleNamespace(account_id=str(uuid4()), arguments={})
        result = ToolInvokerService._security_error(tool, request, confirmed=False)
        assert result is not None
        assert result["error_code"] == "forbidden"

    def test_tool_invoker_security_error_should_require_confirmation_for_sensitive(self):
        from internal.entity.tool_inventory_entity import RiskLevel
        from internal.service.tool_invoker_service import ToolInvokerService

        tool = SimpleNamespace(metadata={"risk_level": RiskLevel.SENSITIVE.value, "user_scope": "system"})
        request = SimpleNamespace(account_id=str(uuid4()), arguments={})
        result = ToolInvokerService._security_error(tool, request, confirmed=False)
        assert result is not None
        assert result["error_code"] == "confirmation_required"

        result_confirmed = ToolInvokerService._security_error(tool, request, confirmed=True)
        assert result_confirmed is None

    def test_tool_invoker_security_error_should_require_confirmation_for_high(self):
        from internal.entity.tool_inventory_entity import RiskLevel
        from internal.service.tool_invoker_service import ToolInvokerService

        tool = SimpleNamespace(metadata={"risk_level": RiskLevel.HIGH.value, "user_scope": "system"})
        request = SimpleNamespace(account_id=str(uuid4()), arguments={})
        result = ToolInvokerService._security_error(tool, request, confirmed=False)
        assert result is not None
        assert result["error_code"] == "confirmation_required"

    def test_tool_invoker_security_error_should_pass_safe_tool(self):
        from internal.entity.tool_inventory_entity import RiskLevel
        from internal.service.tool_invoker_service import ToolInvokerService

        tool = SimpleNamespace(metadata={"risk_level": RiskLevel.SAFE.value, "user_scope": "system"})
        request = SimpleNamespace(account_id=str(uuid4()), arguments={})
        result = ToolInvokerService._security_error(tool, request, confirmed=False)
        assert result is None
