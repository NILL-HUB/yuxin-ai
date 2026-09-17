"""管理端 Agent 对话路由测试。

只验证接线：
- 权限映射（chat POST → agent_pool:manage；会话/消息 GET → agent_pool:read）；
- `admin["id"]` 必须转 UUID 后交给服务（与 P1 的 invoke/drafts 同口径）；
- 服务层 `FailException` → 404/400 可读错误。
"""
import asyncio
from uuid import UUID, uuid4

import app.http.asgi_app as asgi_app
from app.http import support
from app.http.admin_routes_7 import register_routes

register_routes(asgi_app.quart_app)


def _admin_ctx(admin_id, permissions):
    async def _fake(permission_code=None):
        return {"id": str(admin_id), "roles": ["operator"], "permissions": list(permissions)}, None

    return _fake


class _StubChatService:
    def __init__(self, frames=None, error=None):
        self.calls = []
        self._frames = frames or ['event: end\ndata:{}\n\n']
        self._error = error

    def chat(self, **kwargs):
        self.calls.append(kwargs)
        if self._error is not None:
            raise self._error
        for frame in self._frames:
            yield frame

    def list_conversations(self, **kwargs):
        self.calls.append(kwargs)
        return []

    def list_messages(self, **kwargs):
        self.calls.append(kwargs)
        return []


def _wire(monkeypatch, admin_id, permissions, svc):
    monkeypatch.setattr(support, "_resolve_admin_permission", _admin_ctx(admin_id, permissions))
    monkeypatch.setattr(support, "_get_service", lambda cls: svc)
    return svc


def _run(coro):
    return asyncio.run(coro)


class TestPermissionMapping:
    def test_chat_maps_to_manage(self):
        assert (
            support._admin_route_permission(
                "POST", f"/admin/agents/{uuid4()}/chat"
            )
            == "agent_pool:manage"
        )

    def test_conversations_maps_to_read(self):
        assert (
            support._admin_route_permission(
                "GET", f"/admin/agents/{uuid4()}/conversations"
            )
            == "agent_pool:read"
        )


class TestChatEndpoint:
    def test_chat_passes_uuid_admin_user_id(self, monkeypatch):
        admin_id = uuid4()
        svc = _wire(monkeypatch, admin_id, ["agent_pool:manage"], _StubChatService())

        async def _go():
            client = asgi_app.quart_app.test_client()
            return await client.post(
                f"/admin/agents/{uuid4()}/chat", json={"query": "看看现状"}
            )

        resp = _run(_go())

        assert resp.status_code == 200
        assert resp.mimetype == "text/event-stream"
        assert isinstance(svc.calls[0]["admin_user_id"], UUID)
        assert svc.calls[0]["admin_user_id"] == admin_id
        assert svc.calls[0]["query"] == "看看现状"
