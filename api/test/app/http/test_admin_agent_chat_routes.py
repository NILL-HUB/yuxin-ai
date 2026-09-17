"""管理端 Agent 对话路由测试。

只验证接线：
- 权限映射（chat POST → agent_pool:manage；会话/消息 GET → agent_pool:read）；
- `admin["id"]` 与 body 里的 `conversation_id` 都必须归一化为 UUID 后交给服务；
- chat 端点的失败语义：**HTTP 层恒为 200 + text/event-stream**，失败信息在 SSE
  帧内（服务层已把可预期异常统一转 `event: error`）；唯一例外是 body 参数
  本身非法（`conversation_id` 非 UUID）时路由直接 400。
"""
import asyncio
from datetime import datetime
from types import SimpleNamespace
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


class _StubAgentService:
    """`get_agent` 归属校验替身（None → NotFoundException，异常 → 上抛）。"""

    def __init__(self, error=None):
        self.calls = []
        self._error = error

    def get_agent(self, **kwargs):
        self.calls.append(kwargs)
        if self._error is not None:
            raise self._error


class _StubConversationService:
    def __init__(self, rows=None, error=None):
        self.calls = []
        self._rows = rows or []
        self._error = error

    def list_conversations(self, **kwargs):
        self.calls.append(("list_conversations", kwargs))
        return self._rows

    def get_conversation(self, conversation_id, **kwargs):
        self.calls.append(("get_conversation", {"conversation_id": conversation_id, **kwargs}))
        if self._error is not None:
            raise self._error

    def list_messages(self, **kwargs):
        self.calls.append(("list_messages", kwargs))
        return self._rows


def _wire(monkeypatch, admin_id, permissions, svc):
    monkeypatch.setattr(support, "_resolve_admin_permission", _admin_ctx(admin_id, permissions))
    monkeypatch.setattr(support, "_get_service", lambda cls: svc)
    return svc


def _wire_multi(monkeypatch, admin_id, permissions, services):
    """按类名分发替身（多服务路由用：Agent 归属校验 + 会话服务）。"""
    monkeypatch.setattr(
        support, "_resolve_admin_permission", _admin_ctx(admin_id, permissions)
    )

    def _get(cls):
        return services[cls.__name__]

    monkeypatch.setattr(support, "_get_service", _get)
    return services


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

    def test_chat_normalizes_conversation_id_to_uuid(self, monkeypatch):
        """续聊时 body 的 conversation_id 必须归一化为 UUID 交给服务。

        服务契约是 UUID；直接透传字符串在 SQLite 方言下会
        `AttributeError: 'str' object has no attribute 'hex'`。
        """
        conversation_id = uuid4()
        svc = _wire(monkeypatch, uuid4(), ["agent_pool:manage"], _StubChatService())

        async def _go():
            client = asgi_app.quart_app.test_client()
            return await client.post(
                f"/admin/agents/{uuid4()}/chat",
                json={"query": "继续", "conversation_id": str(conversation_id)},
            )

        resp = _run(_go())

        assert resp.status_code == 200
        passed = svc.calls[0]["conversation_id"]
        assert isinstance(passed, UUID)
        assert passed == conversation_id

    def test_chat_rejects_illegal_conversation_id_with_400(self, monkeypatch):
        svc = _wire(monkeypatch, uuid4(), ["agent_pool:manage"], _StubChatService())

        async def _go():
            client = asgi_app.quart_app.test_client()
            return await client.post(
                f"/admin/agents/{uuid4()}/chat",
                json={"query": "继续", "conversation_id": "not-a-uuid"},
            )

        resp = _run(_go())

        assert resp.status_code == 400
        assert svc.calls == [], "非法参数不得进入服务层"


class TestConversationsEndpoint:
    def test_lists_conversations_after_ownership_check(self, monkeypatch):
        admin_id = uuid4()
        agent_id = uuid4()
        rows = [
            SimpleNamespace(
                id=uuid4(),
                admin_agent_id=agent_id,
                title="看看现状",
                created_at=datetime(2026, 1, 1),
                updated_at=datetime(2026, 1, 2),
            )
        ]
        agent_svc = _StubAgentService()
        conv_svc = _StubConversationService(rows=rows)
        _wire_multi(
            monkeypatch,
            admin_id,
            ["agent_pool:read"],
            {
                "AdminAgentService": agent_svc,
                "AdminAgentConversationService": conv_svc,
            },
        )

        async def _go():
            client = asgi_app.quart_app.test_client()
            return await client.get(f"/admin/agents/{agent_id}/conversations")

        resp = _run(_go())
        body = _run(resp.get_json())

        assert resp.status_code == 200
        assert len(body["data"]["items"]) == 1
        assert body["data"]["items"][0]["title"] == "看看现状"
        # 归属校验必须先于查询，且 admin_user_id 为 UUID
        assert agent_svc.calls[0]["agent_id"] == agent_id
        assert isinstance(agent_svc.calls[0]["admin_user_id"], UUID)
        assert conv_svc.calls[0][0] == "list_conversations"

    def test_conversations_returns_403_for_non_owner(self, monkeypatch):
        _wire_multi(
            monkeypatch,
            uuid4(),
            ["agent_pool:read"],
            {
                "AdminAgentService": _StubAgentService(
                    error=PermissionError("仅创建者可使用该 Agent")
                ),
                "AdminAgentConversationService": _StubConversationService(),
            },
        )

        async def _go():
            client = asgi_app.quart_app.test_client()
            return await client.get(f"/admin/agents/{uuid4()}/conversations")

        resp = _run(_go())

        assert resp.status_code == 403


class TestMessagesEndpoint:
    def test_lists_messages_after_conversation_ownership_check(self, monkeypatch):
        conversation_id = uuid4()
        rows = [
            SimpleNamespace(
                id=uuid4(),
                role="user",
                content="看看现状",
                tool_calls=[],
                created_at=datetime(2026, 1, 1),
            )
        ]
        conv_svc = _StubConversationService(rows=rows)
        _wire_multi(
            monkeypatch,
            uuid4(),
            ["agent_pool:read"],
            {"AdminAgentConversationService": conv_svc},
        )

        async def _go():
            client = asgi_app.quart_app.test_client()
            return await client.get(f"/admin/agents/conversations/{conversation_id}/messages")

        resp = _run(_go())
        body = _run(resp.get_json())

        assert resp.status_code == 200
        assert body["data"]["items"][0]["role"] == "user"
        # 必须先 get_conversation（校验归属）再 list_messages
        assert [name for name, _ in conv_svc.calls] == ["get_conversation", "list_messages"]

    def test_messages_returns_404_when_conversation_missing(self, monkeypatch):
        from internal.exception import NotFoundException

        _wire_multi(
            monkeypatch,
            uuid4(),
            ["agent_pool:read"],
            {
                "AdminAgentConversationService": _StubConversationService(
                    error=NotFoundException("会话不存在")
                )
            },
        )

        async def _go():
            client = asgi_app.quart_app.test_client()
            return await client.get(f"/admin/agents/conversations/{uuid4()}/messages")

        resp = _run(_go())

        assert resp.status_code == 404

    def test_messages_returns_403_for_foreign_admin(self, monkeypatch):
        from internal.exception import ForbiddenException

        _wire_multi(
            monkeypatch,
            uuid4(),
            ["agent_pool:read"],
            {
                "AdminAgentConversationService": _StubConversationService(
                    error=ForbiddenException("无权访问该会话")
                )
            },
        )

        async def _go():
            client = asgi_app.quart_app.test_client()
            return await client.get(f"/admin/agents/conversations/{uuid4()}/messages")

        resp = _run(_go())

        assert resp.status_code == 403
