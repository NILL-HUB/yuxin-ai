"""管理端 Agent 定义 CRUD 路由测试。

本文件只验证路由接线（服务层单测已在 test_admin_agent_service.py）：
- 权限映射：GET → `agent_pool:read`，POST/PATCH/DELETE → `agent_pool:manage`
- `admin["id"]` 必须转成 UUID 再交给服务（服务契约声明 UUID，且
  `admin_agent.owner_admin_user_id` 是 UUID 列；传字符串会让 `get_agent`
  的属主比较恒不相等而误报 403）
- 服务层异常 → 正确 HTTP 状态码
"""
import asyncio
from datetime import datetime
from types import SimpleNamespace
from uuid import UUID, uuid4

import app.http.asgi_app as asgi_app
from app.http import support
from app.http.admin_routes_7 import register_routes

register_routes(asgi_app.quart_app)

ADMIN_ID = "11111111-1111-1111-1111-111111111111"


def _admin_ctx(admin_id, permissions):
    async def _fake(permission_code=None):
        return {
            "id": str(admin_id),
            "roles": ["operator"],
            "permissions": list(permissions),
        }, None

    return _fake


def _agent_row(agent_id):
    return SimpleNamespace(
        id=agent_id,
        name="运维 Agent",
        description="跑运维动作",
        prompt_key=None,
        granted_permissions=["builtin_tool:read"],
        automation_policy={"builtin_tool": "supervised"},
        enabled=True,
        created_at=datetime(2026, 1, 1),
        updated_at=datetime(2026, 1, 2),
    )


class _StubAgentService:
    def __init__(self, *, agents=None, error=None):
        self._agents = agents if agents is not None else []
        self._error = error
        self.calls = []

    def _record(self, name, kwargs):
        self.calls.append((name, kwargs))
        if self._error is not None:
            raise self._error

    def list_agents(self, *, admin_user_id):
        self._record("list_agents", {"admin_user_id": admin_user_id})
        return self._agents

    def create_agent(self, **kwargs):
        self._record("create_agent", kwargs)
        return _agent_row(uuid4())

    def update_agent(self, **kwargs):
        self._record("update_agent", kwargs)
        return _agent_row(kwargs["agent_id"])

    def delete_agent(self, **kwargs):
        self._record("delete_agent", kwargs)
        return None


def _wire(monkeypatch, admin_id, permissions, svc):
    monkeypatch.setattr(support, "_resolve_admin_permission", _admin_ctx(admin_id, permissions))
    monkeypatch.setattr(support, "_get_service", lambda cls: svc)
    return svc


def _req(method, path, body=None):
    async def _run():
        client = asgi_app.quart_app.test_client()
        return await client.open(path, method=method, json=body)

    resp = asyncio.run(_run())
    return resp, asyncio.run(resp.get_json())


class TestPermissionMapping:
    def test_list_maps_to_read(self):
        assert support._admin_route_permission("GET", "/admin/agents") == "agent_pool:read"

    def test_create_maps_to_manage(self):
        assert support._admin_route_permission("POST", "/admin/agents") == "agent_pool:manage"

    def test_update_maps_to_manage(self):
        assert (
            support._admin_route_permission("PATCH", f"/admin/agents/{ADMIN_ID}")
            == "agent_pool:manage"
        )

    def test_delete_maps_to_manage(self):
        assert (
            support._admin_route_permission("DELETE", f"/admin/agents/{ADMIN_ID}")
            == "agent_pool:manage"
        )


class TestListEndpoint:
    def test_lists_own_agents_and_passes_uuid(self, monkeypatch):
        admin_id = uuid4()
        svc = _wire(
            monkeypatch,
            admin_id,
            ["agent_pool:read"],
            _StubAgentService(agents=[_agent_row(uuid4())]),
        )

        resp, body = _req("GET", "/admin/agents")

        assert resp.status_code == 200
        assert len(body["data"]["items"]) == 1
        assert body["data"]["items"][0]["name"] == "运维 Agent"
        _, kwargs = svc.calls[0]
        assert isinstance(kwargs["admin_user_id"], UUID)
        assert kwargs["admin_user_id"] == admin_id


class TestCreateEndpoint:
    def test_create_passes_uuid_and_fields(self, monkeypatch):
        admin_id = uuid4()
        svc = _wire(monkeypatch, admin_id, ["agent_pool:manage"], _StubAgentService())

        resp, body = _req(
            "POST",
            "/admin/agents",
            {
                "name": "运维 Agent",
                "granted_permissions": ["builtin_tool:read"],
                "automation_policy": {"builtin_tool": "supervised"},
            },
        )

        assert resp.status_code == 200
        assert body["data"]["name"] == "运维 Agent"
        _, kwargs = svc.calls[0]
        assert isinstance(kwargs["admin_user_id"], UUID)
        assert kwargs["admin_user_id"] == admin_id
        assert kwargs["name"] == "运维 Agent"
        assert kwargs["granted_permissions"] == ["builtin_tool:read"]
        assert kwargs["automation_policy"] == {"builtin_tool": "supervised"}

    def test_missing_name_rejected(self, monkeypatch):
        _wire(monkeypatch, uuid4(), ["agent_pool:manage"], _StubAgentService())

        resp, _ = _req("POST", "/admin/agents", {})

        assert resp.status_code == 400

    def test_grant_violation_returns_400_with_message(self, monkeypatch):
        _wire(
            monkeypatch,
            uuid4(),
            ["agent_pool:manage"],
            _StubAgentService(error=ValueError("无权下放以下权限（管理员不具备）: role:read")),
        )

        resp, body = _req(
            "POST", "/admin/agents", {"name": "x", "granted_permissions": ["role:read"]}
        )

        assert resp.status_code == 400
        assert "无权下放" in body["message"]


class TestUpdateEndpoint:
    def test_update_passes_partial_fields(self, monkeypatch):
        agent_id = uuid4()
        svc = _wire(monkeypatch, uuid4(), ["agent_pool:manage"], _StubAgentService())

        resp, _ = _req("PATCH", f"/admin/agents/{agent_id}", {"enabled": False})

        assert resp.status_code == 200
        _, kwargs = svc.calls[0]
        assert kwargs["agent_id"] == agent_id
        assert kwargs["enabled"] is False
        # 未提供的字段保持 None（服务层据此判定"不修改"）
        assert kwargs["name"] is None
        assert kwargs["granted_permissions"] is None

    def test_not_found_returns_404(self, monkeypatch):
        _wire(
            monkeypatch,
            uuid4(),
            ["agent_pool:manage"],
            _StubAgentService(error=LookupError("Agent 不存在")),
        )

        resp, _ = _req("PATCH", f"/admin/agents/{uuid4()}", {"name": "x"})

        assert resp.status_code == 404

    def test_not_owner_returns_403(self, monkeypatch):
        _wire(
            monkeypatch,
            uuid4(),
            ["agent_pool:manage"],
            _StubAgentService(error=PermissionError("仅创建者可使用该 Agent")),
        )

        resp, _ = _req("PATCH", f"/admin/agents/{uuid4()}", {"name": "x"})

        assert resp.status_code == 403

    def test_illegal_automation_level_returns_400(self, monkeypatch):
        _wire(
            monkeypatch,
            uuid4(),
            ["agent_pool:manage"],
            _StubAgentService(error=ValueError("非法自动化级别: x='y'")),
        )

        resp, _ = _req(
            "PATCH", f"/admin/agents/{uuid4()}", {"automation_policy": {"x": "y"}}
        )

        assert resp.status_code == 400


class TestDeleteEndpoint:
    def test_delete_passes_uuid(self, monkeypatch):
        agent_id = uuid4()
        svc = _wire(monkeypatch, uuid4(), ["agent_pool:manage"], _StubAgentService())

        resp, _ = _req("DELETE", f"/admin/agents/{agent_id}")

        assert resp.status_code == 200
        _, kwargs = svc.calls[0]
        assert kwargs["agent_id"] == agent_id
        assert isinstance(kwargs["admin_user_id"], UUID)

    def test_not_found_returns_404(self, monkeypatch):
        _wire(
            monkeypatch,
            uuid4(),
            ["agent_pool:manage"],
            _StubAgentService(error=LookupError("Agent 不存在")),
        )

        resp, _ = _req("DELETE", f"/admin/agents/{uuid4()}")

        assert resp.status_code == 404
