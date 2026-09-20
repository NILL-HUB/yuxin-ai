"""ADMIN-P4 T3：定时任务 admin_agent 通道（service 层）。

覆盖：
1. create_task 支持 task_type='admin_agent_execution' + admin_agent_id（仅 owner_type='admin'）
2. _validate_admin_agent_binding：存在性 + 归属当前管理员校验
3. list_tasks 按 agent_id 过滤透传
"""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock
from uuid import uuid4

import pytest

from internal.exception import FailException
from internal.service.schedule_task_service import (
    TASK_TYPE_ADMIN_AGENT_EXECUTION,
    TASK_TYPES,
    ScheduleTaskService,
)


def test_admin_agent_execution_type_registered():
    assert TASK_TYPE_ADMIN_AGENT_EXECUTION == "admin_agent_execution"
    assert TASK_TYPE_ADMIN_AGENT_EXECUTION in TASK_TYPES


class TestCreateAdminAgentTask:
    def test_sets_type_and_binding(self, monkeypatch):
        svc = ScheduleTaskService.__new__(ScheduleTaskService)
        agent_id = uuid4()
        admin_user_id = uuid4()
        created = {}

        def fake_create(model, **kwargs):
            created.update(kwargs)
            return SimpleNamespace(**kwargs, id=uuid4())

        monkeypatch.setattr(svc, "create", fake_create)
        monkeypatch.setattr(svc, "_get_platform_account", lambda: SimpleNamespace(id=uuid4()))
        monkeypatch.setattr(
            svc, "_validate_admin_agent_binding", lambda aid, uid: aid
        )
        svc.create_task(
            None,
            "每日巡检",
            "对服务器做巡检",
            "0 0 7 * * *",
            owner_type="admin",
            admin_agent_id=agent_id,
            admin_user_id=admin_user_id,
            input_params={"board": "builtin_tool", "action": "list", "payload": {}},
        )
        assert created["owner_type"] == "admin"
        assert created["task_type"] == TASK_TYPE_ADMIN_AGENT_EXECUTION
        assert created["admin_agent_id"] == agent_id
        assert created["input_params"] == {
            "board": "builtin_tool",
            "action": "list",
            "payload": {},
        }

    def test_user_owner_cannot_bind_agent(self, monkeypatch):
        svc = ScheduleTaskService.__new__(ScheduleTaskService)
        monkeypatch.setattr(svc, "create", lambda model, **kw: SimpleNamespace(**kw, id=uuid4()))
        monkeypatch.setattr(svc, "_get_platform_account", lambda: SimpleNamespace(id=uuid4()))
        with pytest.raises(FailException, match="仅平台级"):
            svc.create_task(
                None,
                "t",
                "p",
                "0 0 7 * * *",
                owner_type="user",
                admin_agent_id=uuid4(),
                admin_user_id=uuid4(),
            )

    def test_app_and_agent_binding_conflict(self, monkeypatch):
        svc = ScheduleTaskService.__new__(ScheduleTaskService)
        monkeypatch.setattr(svc, "create", lambda model, **kw: SimpleNamespace(**kw, id=uuid4()))
        monkeypatch.setattr(svc, "_get_platform_account", lambda: SimpleNamespace(id=uuid4()))
        monkeypatch.setattr(svc, "_validate_bound_app", lambda *a, **k: uuid4())
        with pytest.raises(FailException, match="不能同时绑定应用"):
            svc.create_task(
                None,
                "t",
                "p",
                "0 0 7 * * *",
                owner_type="admin",
                app_id=uuid4(),
                admin_agent_id=uuid4(),
                admin_user_id=uuid4(),
            )


class TestValidateAdminAgentBinding:
    def _svc(self, agent):
        db = MagicMock()
        db.session.query.return_value.filter.return_value.one_or_none.return_value = agent
        svc = ScheduleTaskService.__new__(ScheduleTaskService)
        svc.db = db
        return svc

    def test_missing_agent_rejected(self):
        with pytest.raises(FailException, match="不存在"):
            self._svc(None)._validate_admin_agent_binding(uuid4(), uuid4())

    def test_foreign_agent_rejected(self):
        svc = self._svc(
            SimpleNamespace(id=uuid4(), owner_admin_user_id=uuid4())
        )
        with pytest.raises(FailException, match="不属于"):
            svc._validate_admin_agent_binding(uuid4(), uuid4())

    def test_own_agent_accepted(self):
        admin_user_id = uuid4()
        agent = SimpleNamespace(id=uuid4(), owner_admin_user_id=admin_user_id)
        svc = self._svc(agent)
        assert svc._validate_admin_agent_binding(agent.id, admin_user_id) == agent.id

    def test_missing_admin_user_rejected(self):
        with pytest.raises(FailException, match="管理员身份"):
            self._svc(SimpleNamespace(id=uuid4(), owner_admin_user_id=uuid4()))._validate_admin_agent_binding(
                uuid4(), None
            )


class TestListTasksAgentFilter:
    def test_admin_list_filters_by_agent_id(self):
        agent_id = uuid4()
        db = MagicMock()
        query = db.session.query.return_value
        query.filter.return_value = query
        query.order_by.return_value = query
        query.offset.return_value = query
        query.limit.return_value = query
        query.count.return_value = 0
        query.all.return_value = []
        svc = ScheduleTaskService(db=db)

        tasks, total = svc.list_tasks(None, 1, 20, owner_type="admin", agent_id=agent_id)

        assert total == 0
        assert tasks == []
        # 必须同时过滤 owner_type=admin 与 admin_agent_id=agent_id
        call_args = [
            arg
            for call in query.filter.call_args_list
            for arg in call.args
        ]
        targets = [
            getattr(getattr(cond, "left", None), "name", None) for cond in call_args
        ]
        assert "owner_type" in targets
        assert "admin_agent_id" in targets
