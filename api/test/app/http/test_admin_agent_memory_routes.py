"""ADMIN-P4 T4：管理端 Agent 记忆读路由测试。

只验证接线：
- GET /admin/agents/<id>/memory/stats | list 复用 agent_pool:read
- get_agent 归属校验（Agent 不存在 → 404）
- service 调用参数透传
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


class _StubMemoryService:
    def __init__(self):
        self.calls = []

    def memory_stats(self, *, admin_user_id, agent_id=None):
        self.calls.append(("stats", admin_user_id, agent_id))
        return {
            "total_nodes": 3,
            "episodes": 2,
            "skills": 1,
            "recent_memories": [],
        }

    def list_memories(self, *, admin_user_id, agent_id=None, page=1, page_size=20):
        self.calls.append(("list", admin_user_id, agent_id, page, page_size))
        return {"items": [], "total": 0}


def _wire(monkeypatch, admin_id, permissions, agent_exists=True):
    monkeypatch.setattr(
        support, "_resolve_admin_permission", _admin_ctx(admin_id, permissions)
    )
    agent_svc = _StubAgentService(exists=agent_exists)
    memory_svc = _StubMemoryService()
    monkeypatch.setattr(
        support,
        "_get_service",
        lambda cls: {
            "AdminAgentService": agent_svc,
            "AdminMemoryReadService": memory_svc,
        }[cls.__name__],
    )
    return agent_svc, memory_svc


def _get(path):
    async def _run():
        client = asgi_app.quart_app.test_client()
        return await client.get(path)

    return asyncio.run(_run())


class TestPermissionMapping:
    def test_stats_requires_read(self):
        assert (
            support._admin_route_permission("GET", f"/admin/agents/{AGENT_ID}/memory/stats")
            == "agent_pool:read"
        )

    def test_list_requires_read(self):
        assert (
            support._admin_route_permission("GET", f"/admin/agents/{AGENT_ID}/memory/list")
            == "agent_pool:read"
        )


class TestMemoryStatsEndpoint:
    def test_returns_stats_for_agent(self, monkeypatch):
        admin_id = uuid4()
        _, memory_svc = _wire(monkeypatch, admin_id, ["agent_pool:read"])
        resp = _get(f"/admin/agents/{AGENT_ID}/memory/stats")
        assert resp.status_code == 200
        body = asyncio.run(resp.get_json())
        assert body["data"]["total_nodes"] == 3
        kind, called_admin, called_agent = memory_svc.calls[0]
        assert kind == "stats"
        assert str(called_admin) == str(admin_id)
        assert str(called_agent) == AGENT_ID

    def test_unknown_agent_returns_404(self, monkeypatch):
        _, memory_svc = _wire(
            monkeypatch, uuid4(), ["agent_pool:read"], agent_exists=False
        )
        resp = _get(f"/admin/agents/{AGENT_ID}/memory/stats")
        assert resp.status_code == 404
        assert memory_svc.calls == []


class TestMemoryListEndpoint:
    def test_returns_paginated_list(self, monkeypatch):
        admin_id = uuid4()
        _, memory_svc = _wire(monkeypatch, admin_id, ["agent_pool:read"])
        resp = _get(f"/admin/agents/{AGENT_ID}/memory/list?page=2&page_size=10")
        assert resp.status_code == 200
        body = asyncio.run(resp.get_json())
        assert body["data"]["total"] == 0
        kind, called_admin, called_agent, page, page_size = memory_svc.calls[0]
        assert kind == "list"
        assert page == 2
        assert page_size == 10

    def test_unknown_agent_returns_404(self, monkeypatch):
        _, memory_svc = _wire(
            monkeypatch, uuid4(), ["agent_pool:read"], agent_exists=False
        )
        resp = _get(f"/admin/agents/{AGENT_ID}/memory/list")
        assert resp.status_code == 404
        assert memory_svc.calls == []
