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


class TestRunAdminAgentChat:
    def test_dispatches_admin_agent_chat_to_chat_chain(self, monkeypatch):
        """L2：task_type=admin_agent_chat 时调用 AdminAgentChatService.chat 并取答案。

        重要：本方法**不得**再调 `check_and_record`——`AdminAgentChatService.chat`
        内部 L113 已调用它做周期额度预检与 executions 计数，重复调用会让
        executions 翻倍（与已修复的 token 记账断链同类缺陷）。
        """
        svc = _svc()
        agent = _agent()
        task = _task(agent.id)
        task.task_type = "admin_agent_chat"
        task.input_params = {}
        task.prompt = "每天盘点工具并汇报"

        def fake_query(model):
            return MagicMock(filter=MagicMock(
                return_value=MagicMock(one_or_none=MagicMock(return_value=agent))
            ))

        monkeypatch.setattr(svc.db.session, "query", fake_query)
        principal = SimpleNamespace(
            admin_user_id=uuid4(),
            agent_id=agent.id,
            effective_permissions=frozenset({"builtin_tool:read"}),
        )
        monkeypatch.setattr(
            module, "_build_admin_agent_principal", lambda a: principal
        )
        gate = MagicMock()
        monkeypatch.setattr(module, "_build_budget_gate", lambda: gate)

        captured = {}

        class _FakeChat:
            def chat(self, **kwargs):
                captured.update(kwargs)
                yield 'event: answer\ndata:{"answer": "巡检完成"}\n\n'
                yield "event: end\ndata:{}\n\n"

        monkeypatch.setattr(
            module, "_build_admin_agent_chat", lambda: _FakeChat()
        )

        summary = svc._run_admin_agent_chat(task)

        assert captured["query"] == "每天盘点工具并汇报"
        assert captured["agent_id"] == agent.id
        assert captured["admin_user_id"] == principal.admin_user_id
        assert "巡检完成" in summary
        # 预检已由 chat 内部完成，本方法不得重复调用（否则 executions 翻倍）
        gate.check_and_record.assert_not_called()

    def test_precheck_not_duplicated_with_chat_internal(self, monkeypatch):
        """L2 回归防护：预检只在 chat 内发生一次，本方法零调用。

        若后人误在本方法补 `check_and_record`，executions 会翻倍，
        该用例即失败，钉死「记账唯一入口是 chat」这一契约。
        """
        svc = _svc()
        agent = _agent()
        task = _task(agent.id)
        task.task_type = "admin_agent_chat"
        task.input_params = {}
        task.prompt = "巡检"

        monkeypatch.setattr(
            svc.db.session, "query", lambda model: MagicMock(
                filter=MagicMock(return_value=MagicMock(one_or_none=MagicMock(return_value=agent)))
            )
        )
        principal = SimpleNamespace(
            admin_user_id=uuid4(),
            agent_id=agent.id,
            effective_permissions=frozenset(),
        )
        monkeypatch.setattr(module, "_build_admin_agent_principal", lambda a: principal)
        gate = MagicMock()
        monkeypatch.setattr(module, "_build_budget_gate", lambda: gate)

        calls = []

        class _FakeChat:
            def chat(self, **kwargs):
                calls.append(kwargs)
                yield 'event: answer\ndata:{"answer": "ok"}\n\n'
                yield "event: end\ndata:{}\n\n"

        monkeypatch.setattr(module, "_build_admin_agent_chat", lambda: _FakeChat())

        svc._run_admin_agent_chat(task)

        assert len(calls) == 1
        assert gate.check_and_record.call_count == 0
        assert gate.record_usage.call_count == 0

    def test_error_frame_raises_fail_exception(self, monkeypatch):
        """L2 缺陷1：chat 以 error 帧结束（预算超限/对话失败）时必须上抛异常。

        `AdminAgentChatService.chat` 的契约是「所有可预期失败都以
        `event: error` 帧结束且不上抛」（见 admin_agent_chat_service.chat
        的 except 分支：FailException / CustomException / PermissionError /
        AdminAgentBudgetExceeded / Exception 一律转 error 帧后 return）。
        本方法若只提取 answer 帧，会把失败静默转成 answer=""，使
        `execute_task` 记为 success=True 的空结果。回归防护：出现 error 帧
        必须 raise FailException，并携带帧内 error 文本。
        """
        svc = _svc()
        agent = _agent()
        task = _task(agent.id)
        task.task_type = "admin_agent_chat"
        task.input_params = {}
        task.prompt = "每天盘点工具并汇报"

        monkeypatch.setattr(
            svc.db.session,
            "query",
            lambda model: MagicMock(
                filter=MagicMock(return_value=MagicMock(one_or_none=MagicMock(return_value=agent)))
            ),
        )
        principal = SimpleNamespace(
            admin_user_id=uuid4(),
            agent_id=agent.id,
            effective_permissions=frozenset(),
        )
        monkeypatch.setattr(module, "_build_admin_agent_principal", lambda a: principal)

        class _FakeChat:
            def chat(self, **kwargs):
                yield (
                    'event: error\ndata:{"error": "预算闸门: daily_executions 周期额度已用完"}\n\n'
                )

        monkeypatch.setattr(module, "_build_admin_agent_chat", lambda: _FakeChat())

        with pytest.raises(FailException, match="预算闸门"):
            svc._run_admin_agent_chat(task)

    def test_error_frame_not_swallowed_as_empty_answer(self, monkeypatch):
        """L2 缺陷1 回归：error 帧绝不能被降级为 answer=""（成功空结果）。

        直接断言「未抛异常」与「返回空串」这一旧行为已不存在——否则
        `execute_task` 会记 success=True。此用例与上一个互补：上一个验证
        抛错类型与文本，此处钉死「不得静默返回」。
        """
        svc = _svc()
        agent = _agent()
        task = _task(agent.id)
        task.task_type = "admin_agent_chat"
        task.input_params = {}
        task.prompt = "巡检"

        monkeypatch.setattr(
            svc.db.session,
            "query",
            lambda model: MagicMock(
                filter=MagicMock(return_value=MagicMock(one_or_none=MagicMock(return_value=agent)))
            ),
        )
        principal = SimpleNamespace(
            admin_user_id=uuid4(),
            agent_id=agent.id,
            effective_permissions=frozenset(),
        )
        monkeypatch.setattr(module, "_build_admin_agent_principal", lambda a: principal)

        class _FakeChat:
            def chat(self, **kwargs):
                yield 'event: error\ndata:{"error": "对话失败：模型不可用"}\n\n'

        monkeypatch.setattr(module, "_build_admin_agent_chat", lambda: _FakeChat())

        with pytest.raises(FailException):
            svc._run_admin_agent_chat(task)


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
