"""ADMIN-P4 T3：管理端 Agent 定时任务路由测试。

被测逻辑已在 service 层单测；本文件只验证路由的接线：
- 权限映射（POST/DELETE → agent_pool:manage，GET → agent_pool:read）
- create_task 以 owner_type='admin' + admin_agent_id 绑定
- list/delete 的归属透传
"""
from __future__ import annotations

import asyncio
from types import SimpleNamespace
from uuid import uuid4

import app.http.asgi_app as asgi_app
from app.http import support
from app.http.admin_routes_7 import register_routes

register_routes(asgi_app.quart_app)

AGENT_ID = "22222222-2222-2222-2222-222222222222"
TASK_ID = "33333333-3333-3333-3333-333333333333"


def _admin_ctx(admin_id, permissions):
    async def _fake(permission_code=None):
        return {
            "id": str(admin_id),
            "roles": ["operator"],
            "permissions": list(permissions),
        }, None

    return _fake


class _StubAgentService:
    def __init__(self, exists=True):
        self._exists = exists

    def get_agent(self, *, agent_id, admin_user_id):
        if not self._exists:
            return None
        return SimpleNamespace(id=AGENT_ID, name="巡检 Agent")


class _StubScheduleService:
    def __init__(self):
        self.created = []
        self.deleted = []

    def create_task(self, account=None, **kwargs):
        kwargs = dict(kwargs)
        # 模拟真实 service：绑定管理端 Agent 时强制 task_type=admin_agent_execution
        if kwargs.get("admin_agent_id"):
            kwargs.setdefault("task_type", "admin_agent_execution")
        self.created.append(kwargs)
        return SimpleNamespace(
            id=TASK_ID,
            name=kwargs.get("name"),
            prompt=kwargs.get("prompt"),
            app_id=None,
            admin_agent_id=kwargs.get("admin_agent_id"),
            task_type=kwargs.get("task_type"),
            input_params=kwargs.get("input_params") or {},
            owner_type=kwargs.get("owner_type"),
            trigger_type="cron",
            cron_expression=kwargs.get("cron_expression"),
            cron_humanized="",
            interval_config={},
            run_at=None,
            enabled=True,
            status="active",
            description="",
            run_count=0,
            last_run_at=None,
            last_run_status=None,
            last_result=None,
            next_run_at=None,
            created_at=None,
            updated_at=None,
        )

    def list_tasks(self, account, page, page_size, owner_type="user", agent_id=None):
        self.list_args = {
            "owner_type": owner_type,
            "agent_id": agent_id,
            "page": page,
            "page_size": page_size,
        }
        task = self.create_task(
            name="每日巡检",
            owner_type=owner_type,
            admin_agent_id=agent_id,
            task_type="admin_agent_execution",
        )
        return [task], 1

    def get_task(self, task_id, account, owner_type="user"):
        return SimpleNamespace(id=task_id, admin_agent_id=AGENT_ID)

    def delete_task(self, task_id, account, owner_type="user", **kwargs):
        self.deleted.append(
            {"task_id": task_id, "owner_type": owner_type, "kwargs": kwargs}
        )


def _wire(monkeypatch, admin_id, permissions, agent_exists=True):
    monkeypatch.setattr(
        support, "_resolve_admin_permission", _admin_ctx(admin_id, permissions)
    )
    agent_svc = _StubAgentService(exists=agent_exists)
    sched_svc = _StubScheduleService()
    monkeypatch.setattr(
        support,
        "_get_service",
        lambda cls: {
            "AdminAgentService": agent_svc,
            "ScheduleTaskService": sched_svc,
        }[cls.__name__],
    )
    return agent_svc, sched_svc


def _post(path, json_body):
    async def _run():
        client = asgi_app.quart_app.test_client()
        return await client.post(path, json=json_body)

    return asyncio.run(_run())


def _get(path):
    async def _run():
        client = asgi_app.quart_app.test_client()
        return await client.get(path)

    return asyncio.run(_run())


def _delete(path):
    async def _run():
        client = asgi_app.quart_app.test_client()
        return await client.delete(path)

    return asyncio.run(_run())


class TestPermissionMapping:
    def test_create_schedule_requires_manage(self):
        assert (
            support._admin_route_permission("POST", f"/admin/agents/{AGENT_ID}/schedules")
            == "agent_pool:manage"
        )

    def test_list_schedule_requires_read(self):
        assert (
            support._admin_route_permission("GET", f"/admin/agents/{AGENT_ID}/schedules")
            == "agent_pool:read"
        )

    def test_delete_schedule_requires_manage(self):
        assert (
            support._admin_route_permission(
                "DELETE", f"/admin/agents/{AGENT_ID}/schedules/{TASK_ID}"
            )
            == "agent_pool:manage"
        )


class TestCreateScheduleEndpoint:
    def test_binds_agent_and_input_params(self, monkeypatch):
        admin_id = uuid4()
        _, sched_svc = _wire(monkeypatch, admin_id, ["agent_pool:manage"])
        resp = _post(
            f"/admin/agents/{AGENT_ID}/schedules",
            {
                "name": "每日巡检",
                "prompt": "对服务器做巡检",
                "cron_expression": "0 0 7 * * *",
                "board": "builtin_tool",
                "action": "list",
                "payload": {"scope": "prod"},
            },
        )
        assert resp.status_code == 200
        body = asyncio.run(resp.get_json())
        assert body["data"]["id"] == TASK_ID
        created = sched_svc.created[0]
        assert created["owner_type"] == "admin"
        assert str(created["admin_agent_id"]) == AGENT_ID
        assert created["task_type"] == "admin_agent_execution"
        assert created["input_params"] == {
            "board": "builtin_tool",
            "action": "list",
            "payload": {"scope": "prod"},
        }

    def test_unknown_agent_returns_404(self, monkeypatch):
        _, sched_svc = _wire(
            monkeypatch, uuid4(), ["agent_pool:manage"], agent_exists=False
        )
        resp = _post(
            f"/admin/agents/{AGENT_ID}/schedules",
            {"name": "n", "cron_expression": "0 0 7 * * *", "board": "b", "action": "a"},
        )
        assert resp.status_code == 404
        assert sched_svc.created == []

    def test_missing_fields_returns_400(self, monkeypatch):
        _wire(monkeypatch, uuid4(), ["agent_pool:manage"])
        resp = _post(
            f"/admin/agents/{AGENT_ID}/schedules",
            {"name": "n"},
        )
        assert resp.status_code == 400


class TestListScheduleEndpoint:
    def test_lists_agent_schedules(self, monkeypatch):
        _, sched_svc = _wire(monkeypatch, uuid4(), ["agent_pool:read"])
        resp = _get(f"/admin/agents/{AGENT_ID}/schedules")
        assert resp.status_code == 200
        body = asyncio.run(resp.get_json())
        assert body["data"]["total"] == 1
        assert sched_svc.list_args["owner_type"] == "admin"
        assert str(sched_svc.list_args["agent_id"]) == AGENT_ID


class TestDeleteScheduleEndpoint:
    def test_delete_calls_service_with_admin_scope(self, monkeypatch):
        _, sched_svc = _wire(monkeypatch, uuid4(), ["agent_pool:manage"])
        resp = _delete(f"/admin/agents/{AGENT_ID}/schedules/{TASK_ID}")
        assert resp.status_code == 200
        assert sched_svc.deleted[0]["owner_type"] == "admin"
        assert str(sched_svc.deleted[0]["task_id"]) == TASK_ID
