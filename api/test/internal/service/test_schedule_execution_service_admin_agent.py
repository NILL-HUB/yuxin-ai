"""ADMIN-P4 T3：定时任务 admin_agent 执行分支。

覆盖：
1. execute_task 按 task_type='admin_agent_execution' 分流到 _run_admin_agent
2. _run_admin_agent：构造 principal → 预算闸门 → AdminAgentExecutionService.run
3. 异常路径：Agent 不存在 / 已停用 / 缺 board/action
4. _create_run 透传 admin_agent_id
"""
from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import MagicMock
from uuid import uuid4

import pytest

import internal.service.schedule_execution_service as module
from internal.exception import FailException, NotFoundException
from internal.service.schedule_execution_service import ScheduleExecutionService


def _svc():
    db = MagicMock()
    redis = MagicMock()
    redis.set.return_value = True
    svc = ScheduleExecutionService(db=db, redis_client=redis)
    return svc


def _agent(enabled=True, budget_config=None):
    return SimpleNamespace(
        id=uuid4(),
        owner_admin_user_id=uuid4(),
        name="巡检 Agent",
        enabled=enabled,
        budget_config=budget_config or {},
    )


def _task(agent_id, input_params=None):
    return SimpleNamespace(
        id=uuid4(),
        task_type="admin_agent_execution",
        admin_agent_id=agent_id,
        input_params=input_params
        or {"board": "builtin_tool", "action": "list", "payload": {}},
        prompt="",
        name="每日巡检",
        account_id=uuid4(),
        owner_type="admin",
    )


class _FakePrincipal:
    pass


class TestRunAdminAgent:
    def test_builds_principal_and_executes(self, monkeypatch):
        svc = _svc()
        agent = _agent()
        task = _task(agent.id)
        calls = {}

        def fake_query(model):
            return MagicMock(filter=MagicMock(
                return_value=MagicMock(one_or_none=MagicMock(return_value=agent))
            ))

        monkeypatch.setattr(svc.db.session, "query", fake_query)
        monkeypatch.setattr(
            module,
            "_build_admin_agent_principal",
            lambda a: _FakePrincipal(),
        )

        class _FakeExec:
            def run(self, principal, *, board, action, payload):
                calls.update(
                    {"principal": principal, "board": board, "action": action, "payload": payload}
                )
                return {"outcome": "executed", "result": {"ok": True}, "draft_id": None}

        monkeypatch.setattr(module, "_build_admin_agent_execution", lambda: _FakeExec())
        gate = MagicMock()
        monkeypatch.setattr(module, "_build_budget_gate", lambda: gate)

        summary = svc._run_admin_agent(task)

        assert isinstance(_FakePrincipal(), _FakePrincipal)
        assert calls["board"] == "builtin_tool"
        assert calls["action"] == "list"
        assert calls["payload"] == {}
        # 预算闸门必须按 agent 定义校验（消费同一周期额度）
        gate.check_and_record.assert_called_once_with(
            str(agent.id), agent.budget_config
        )
        parsed = json.loads(summary)
        assert parsed["outcome"] == "executed"

    def test_missing_agent_raises_not_found(self, monkeypatch):
        svc = _svc()
        monkeypatch.setattr(
            svc.db.session, "query", lambda model: MagicMock(
                filter=MagicMock(return_value=MagicMock(one_or_none=MagicMock(return_value=None)))
            )
        )
        with pytest.raises(NotFoundException):
            svc._run_admin_agent(_task(uuid4()))

    def test_disabled_agent_raises_not_found(self, monkeypatch):
        svc = _svc()
        agent = _agent(enabled=False)
        monkeypatch.setattr(
            svc.db.session, "query", lambda model: MagicMock(
                filter=MagicMock(return_value=MagicMock(one_or_none=MagicMock(return_value=agent)))
            )
        )
        with pytest.raises(NotFoundException):
            svc._run_admin_agent(_task(agent.id))

    def test_missing_board_or_action_raises(self, monkeypatch):
        svc = _svc()
        agent = _agent()
        monkeypatch.setattr(
            svc.db.session, "query", lambda model: MagicMock(
                filter=MagicMock(return_value=MagicMock(one_or_none=MagicMock(return_value=agent)))
            )
        )
        with pytest.raises(FailException, match="board/action"):
            svc._run_admin_agent(_task(agent.id, input_params={"payload": {}}))

    def test_budget_exceeded_propagates(self, monkeypatch):
        from internal.core.admin_agent_budget import AdminAgentBudgetExceeded

        svc = _svc()
        agent = _agent()
        monkeypatch.setattr(
            svc.db.session, "query", lambda model: MagicMock(
                filter=MagicMock(return_value=MagicMock(one_or_none=MagicMock(return_value=agent)))
            )
        )
        monkeypatch.setattr(module, "_build_admin_agent_principal", lambda a: _FakePrincipal())
        monkeypatch.setattr(module, "_build_admin_agent_execution", lambda: MagicMock())

        def _boom(*a, **k):
            raise AdminAgentBudgetExceeded("预算闸门: daily_executions 周期额度已用完")

        monkeypatch.setattr(module, "_build_budget_gate", lambda: SimpleNamespace(check_and_record=_boom))
        with pytest.raises(AdminAgentBudgetExceeded):
            svc._run_admin_agent(_task(agent.id))


class TestExecuteTaskDispatch:
    def test_admin_agent_task_routes_to_admin_branch(self, monkeypatch):
        svc = _svc()
        agent_id = uuid4()
        task = _task(agent_id)
        monkeypatch.setattr(svc, "_account_under_concurrency_limit", lambda aid: True)
        ran = {}
        monkeypatch.setattr(svc, "_create_run", lambda t: SimpleNamespace(id=uuid4()))
        monkeypatch.setattr(svc, "_finish_run", lambda *a, **k: None)
        monkeypatch.setattr(
            svc,
            "_run_admin_agent",
            lambda t: ran.update({"called": True, "task": t}) or '{"ok": true}',
        )

        run = svc.execute_task(task)

        assert ran.get("called") is True
        assert run is not None

    def test_create_run_passes_admin_agent_id(self, monkeypatch):
        svc = _svc()
        agent_id = uuid4()
        task = _task(agent_id)
        created = {}

        def fake_create(model, **kwargs):
            created.update(kwargs)
            return SimpleNamespace(id=uuid4())

        monkeypatch.setattr(svc, "create", fake_create)
        run = svc._create_run(task)
        assert created["admin_agent_id"] == agent_id
        assert created["owner_type"] == "admin"
        assert run is not None
