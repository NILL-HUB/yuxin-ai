"""管理端 Agent 执行层测试（设计 §5.1 / §7.1 / §9）。

核心不变式：
1. supervised 档**不执行**，只产出变更草稿；
2. autonomous 档直接执行；
3. 每次执行都写 actor_type=agent 的审计，且 admin_user_id 是人类责任人；
4. 权限拒绝也要记审计（设计 §7.1 第 1 步"不足 → 拒绝并记审计"）。
"""
from types import SimpleNamespace
from uuid import uuid4

import pytest

from internal.entity.admin_agent_entity import AdminAgentPrincipal, AutomationLevel
from internal.service.admin_agent_execution_service import (
    AdminAgentExecutionService,
    ExecutionOutcome,
)


def _principal(perms=None, policy=None):
    return AdminAgentPrincipal(
        admin_user_id=uuid4(),
        agent_id=uuid4(),
        agent_name="运维 Agent",
        effective_permissions=frozenset(
            perms
            if perms is not None
            else {"builtin_tool:read", "builtin_tool:update"}
        ),
        automation_policy=policy or {},
    )


class _AuditRecorder:
    def __init__(self):
        self.calls = []

    def record(self, **kw):
        self.calls.append(kw)
        return SimpleNamespace(**kw)


class _StubExecutor:
    """不重写被测逻辑的执行器替身（真实逻辑在 BoardToolExecutor 已单测）。"""

    def __init__(self, result=None, deny=False):
        self._result = result or {}
        self._deny = deny
        self.executed = []

    def assert_allowed(self, principal, *, board, action):
        from internal.core.admin_agent_boards import resolve_action

        declared = resolve_action(board, action)
        if self._deny:
            raise PermissionError("Agent 无权限执行该动作")
        return declared

    def requires_draft(self, principal, board):
        return principal.automation_level_for(board) is AutomationLevel.SUPERVISED

    def execute(self, principal, *, board, action, payload):
        self.executed.append((board, action))
        return self._result


class _StubDraft:
    def __init__(self):
        self.created = []
        self.last_kwargs = {}

    def create_draft(self, **kw):
        self.created.append(kw)
        self.last_kwargs = kw
        return SimpleNamespace(id=uuid4())


def _service(executor=None, draft=None, audit=None):
    return AdminAgentExecutionService(
        board_executor=executor or _StubExecutor(),
        draft_service=draft or _StubDraft(),
        audit_log_service=audit or _AuditRecorder(),
    )


class TestReadAction:
    def test_read_action_executes_directly(self):
        svc = _service(executor=_StubExecutor(result={"items": []}))
        result = svc.run(_principal(), board="builtin_tool", action="list", payload={})
        assert result["outcome"] == ExecutionOutcome.EXECUTED.value
        assert result["result"] == {"items": []}
        assert result["draft_id"] is None

    def test_read_action_is_audited_as_agent(self):
        audit = _AuditRecorder()
        principal = _principal()
        _service(executor=_StubExecutor(result={}), audit=audit).run(
            principal, board="builtin_tool", action="list", payload={}
        )
        assert len(audit.calls) == 1
        call = audit.calls[0]
        assert call["actor_type"] == "agent"
        assert call["agent_id"] == principal.agent_id
        # admin_user_id 必须是人类责任人，不是 None、不是 agent_id
        assert call["admin_user_id"] == principal.admin_user_id
        assert call["resource_type"] == "builtin_tool"


class TestSupervisedDraft:
    def test_supervised_write_creates_draft_without_executing(self):
        executor = _StubExecutor(result={"should_not": "run"})
        draft = _StubDraft()
        svc = _service(
            executor=executor,
            draft=draft,
            audit=_AuditRecorder(),
        )
        result = svc.run(
            _principal(policy={"builtin_tool": AutomationLevel.SUPERVISED}),
            board="builtin_tool",
            action="update_enabled",
            payload={"tool_id": "t1", "enabled": False},
        )
        assert result["outcome"] == ExecutionOutcome.DRAFTED.value
        assert result["draft_id"] is not None
        assert executor.executed == [], "supervised 档不得调用板块实现体"
        assert draft.created, "必须产出变更草稿"

    def test_draft_carries_agent_id_for_traceability(self):
        draft = _StubDraft()
        principal = _principal(policy={"builtin_tool": AutomationLevel.SUPERVISED})
        _service(draft=draft).run(
            principal,
            board="builtin_tool",
            action="update_enabled",
            payload={"tool_id": "t1", "enabled": False},
        )
        assert draft.last_kwargs["agent_id"] == principal.agent_id
        assert draft.last_kwargs["policy_type"] == "builtin_tool"
        assert draft.last_kwargs["created_by"] == principal.admin_user_id

    def test_unconfigured_board_defaults_to_supervised(self):
        """未配置 automation_policy 的板块 fail closed 到 supervised（不自动执行）。"""
        executor = _StubExecutor()
        svc = _service(executor=executor)
        result = svc.run(
            _principal(policy={}),
            board="builtin_tool",
            action="update_enabled",
            payload={"tool_id": "t1", "enabled": False},
        )
        assert result["outcome"] == ExecutionOutcome.DRAFTED.value
        assert executor.executed == []

    def test_supervised_draft_is_audited(self):
        audit = _AuditRecorder()
        _service(audit=audit).run(
            _principal(policy={"builtin_tool": AutomationLevel.SUPERVISED}),
            board="builtin_tool",
            action="update_enabled",
            payload={"tool_id": "t1", "enabled": False},
        )
        assert len(audit.calls) == 1
        assert audit.calls[0]["action"].endswith("drafted")
        assert audit.calls[0]["actor_type"] == "agent"


class TestAutonomous:
    def test_autonomous_write_executes_directly(self):
        executor = _StubExecutor(result={"enabled": False})
        draft = _StubDraft()
        svc = _service(executor=executor, draft=draft)
        result = svc.run(
            _principal(policy={"builtin_tool": AutomationLevel.AUTONOMOUS}),
            board="builtin_tool",
            action="update_enabled",
            payload={"tool_id": "t1", "enabled": False},
        )
        assert result["outcome"] == ExecutionOutcome.EXECUTED.value
        assert executor.executed == [("builtin_tool", "update_enabled")]
        assert draft.created == [], "autonomous 档不产草稿"

    def test_read_action_never_drafts_even_in_supervised(self):
        """只读动作不受自动化级别影响（否则 supervised 档连列表都查不了）。"""
        executor = _StubExecutor(result={"items": []})
        draft = _StubDraft()
        svc = _service(executor=executor, draft=draft)
        result = svc.run(
            _principal(policy={"builtin_tool": AutomationLevel.SUPERVISED}),
            board="builtin_tool",
            action="list",
            payload={},
        )
        assert result["outcome"] == ExecutionOutcome.EXECUTED.value
        assert draft.created == []
        assert executor.executed == [("builtin_tool", "list")]


class TestFailureAudited:
    def test_permission_failure_is_audited_and_reraised(self):
        """权限不足必须记审计（设计 §7.1 第 1 步"不足 → 拒绝并记审计"）。"""
        audit = _AuditRecorder()
        svc = _service(executor=_StubExecutor(deny=True), audit=audit)
        with pytest.raises(PermissionError):
            svc.run(
                _principal(),
                board="builtin_tool",
                action="update_enabled",
                payload={"tool_id": "t1", "enabled": False},
            )
        assert len(audit.calls) == 1
        assert audit.calls[0]["actor_type"] == "agent"
        assert "denied" in audit.calls[0]["action"]

    def test_undeclared_action_is_audited_and_reraised(self):
        """未登记 action 也记审计后上抛（fail closed + 可追溯）。"""
        audit = _AuditRecorder()
        svc = _service(audit=audit)
        with pytest.raises(ValueError):
            svc.run(_principal(), board="builtin_tool", action="nope", payload={})
        assert len(audit.calls) == 1
        assert "denied" in audit.calls[0]["action"]

    def test_audit_failure_does_not_break_execution(self):
        """审计写入失败不得阻断主流程（与既有 audit 写入的容错一致）。"""

        class _BrokenAudit:
            def record(self, **kw):
                raise RuntimeError("audit db down")

        svc = _service(executor=_StubExecutor(result={"ok": True}), audit=_BrokenAudit())
        result = svc.run(
            _principal(), board="builtin_tool", action="list", payload={}
        )
        assert result["outcome"] == ExecutionOutcome.EXECUTED.value


class TestExecutionOutcome:
    def test_outcome_values(self):
        assert ExecutionOutcome.EXECUTED.value == "executed"
        assert ExecutionOutcome.DRAFTED.value == "drafted"
