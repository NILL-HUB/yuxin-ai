"""机密记忆读取确认端点（用户侧 + 管理端）接线测试。

只验证接线与隔离语义：
- 用户端主体键由 JWT 强制（``for_user``），确认记录只对发起者可见；
- 管理端主体键与召回一致（``for_admin`` + Agent 归属校验），非属主 Agent → 404；
- 权限映射：GET → agent_pool:read；confirm/cancel → agent_pool:manage（已有映射复用）；
- 过期/不存在/跨主体一律 404（不泄露"存在但不属于你"）。
"""
import asyncio
from types import SimpleNamespace
from uuid import uuid4

import app.http.asgi_app as asgi_app
from app.http import support
from app.http.admin_routes_7 import register_routes as register_admin_routes
from app.http.user_routes_9 import register_routes as register_user_routes

from test.internal.service.memory.test_memory_read_confirmation import _FakeRedis

register_user_routes(asgi_app.quart_app)
register_admin_routes(asgi_app.quart_app)


def _run(coro):
    return asyncio.run(coro)


def _confirmation_service(fake=None):
    from internal.service.memory.read_confirmation_service import (
        MemoryReadConfirmationService,
    )

    return MemoryReadConfirmationService(redis_client=fake or _FakeRedis())


def _items():
    return [
        {
            "memory_id": "m1",
            "types": ["phone"],
            "label": "手机号",
            "preview": "我的手机号是 [PHONE_REDACTED]",
        }
    ]


def _wire_user(monkeypatch, account_id, service):
    async def _fake_resolve_account(account_id_override=None):
        return SimpleNamespace(id=account_id), None

    monkeypatch.setattr(support, "_resolve_account", _fake_resolve_account)
    monkeypatch.setattr(support, "_get_service", lambda cls: service)
    return service


def _wire_admin(monkeypatch, admin_id, service, agent_owned=True):
    async def _fake_permission(permission_code=None):
        return {"id": str(admin_id), "roles": ["super_admin"], "permissions": ["*"]}, None

    class _StubAgentService:
        def get_agent(self, *, agent_id, admin_user_id):
            return SimpleNamespace(id=agent_id) if agent_owned else None

    services = {
        "MemoryReadConfirmationService": service,
        "AdminAgentService": _StubAgentService(),
    }

    monkeypatch.setattr(support, "_resolve_admin_permission", _fake_permission)
    monkeypatch.setattr(support, "_get_service", lambda cls: services[cls.__name__])
    return service


def _read_json(resp):
    import json

    # Quart 的 Response.get_data 是协程：测试里在事件循环外补一个 run 读取已缓冲的响应体。
    return json.loads(asyncio.run(resp.get_data(as_text=True)))


class TestUserSideRoutes:
    def test_confirm_then_detail_shows_confirmed(self, monkeypatch):
        service = _confirmation_service()
        account_id = uuid4()
        _wire_user(monkeypatch, account_id, service)
        from internal.entity.memory_owner_entity import MemoryOwnerKey

        owner_key = MemoryOwnerKey.for_user(account_id).to_key()
        confirmation_id = service.create(owner_key=owner_key, items=_items())

        async def _go():
            client = asgi_app.quart_app.test_client()
            confirmed = await client.post(
                f"/memory/confirmations/{confirmation_id}/confirm"
            )
            detail = await client.get(f"/memory/confirmations/{confirmation_id}")
            return confirmed, detail

        confirmed, detail = _run(_go())

        assert confirmed.status_code == 200
        assert _read_json(confirmed)["data"]["status"] == "confirmed"
        assert detail.status_code == 200
        assert _read_json(detail)["data"]["items"][0]["memory_id"] == "m1"
        assert service.authorized_ids(owner_key) == frozenset({"m1"})

    def test_cancel_grants_nothing(self, monkeypatch):
        service = _confirmation_service()
        account_id = uuid4()
        _wire_user(monkeypatch, account_id, service)
        from internal.entity.memory_owner_entity import MemoryOwnerKey

        owner_key = MemoryOwnerKey.for_user(account_id).to_key()
        confirmation_id = service.create(owner_key=owner_key, items=_items())

        async def _go():
            client = asgi_app.quart_app.test_client()
            return await client.post(f"/memory/confirmations/{confirmation_id}/cancel")

        resp = _run(_go())

        assert resp.status_code == 200
        assert _read_json(resp)["data"]["status"] == "cancelled"
        assert service.authorized_ids(owner_key) == frozenset()

    def test_unknown_id_returns_404(self, monkeypatch):
        _wire_user(monkeypatch, uuid4(), _confirmation_service())

        async def _go():
            client = asgi_app.quart_app.test_client()
            return await client.get("/memory/confirmations/not-exist")

        assert _run(_go()).status_code == 404

    def test_other_account_cannot_confirm(self, monkeypatch):
        """判别性：主体键由 JWT 强制，别人的确认记录一律 404。"""
        service = _confirmation_service()
        owner_id, attacker_id = uuid4(), uuid4()
        from internal.entity.memory_owner_entity import MemoryOwnerKey

        owner_key = MemoryOwnerKey.for_user(owner_id).to_key()
        confirmation_id = service.create(owner_key=owner_key, items=_items())

        _wire_user(monkeypatch, attacker_id, service)  # 以攻击者身份登录

        async def _go():
            client = asgi_app.quart_app.test_client()
            return await client.post(f"/memory/confirmations/{confirmation_id}/confirm")

        resp = _run(_go())

        assert resp.status_code == 404
        assert service.authorized_ids(owner_key) == frozenset()


class TestAdminSideRoutes:
    def test_admin_confirm_uses_admin_owner_key(self, monkeypatch):
        service = _confirmation_service()
        admin_id, agent_id = uuid4(), uuid4()
        _wire_admin(monkeypatch, admin_id, service)
        from internal.entity.memory_owner_entity import MemoryOwnerKey

        owner_key = MemoryOwnerKey.for_admin(admin_id, agent_id=agent_id).to_key()
        confirmation_id = service.create(owner_key=owner_key, items=_items())

        async def _go():
            client = asgi_app.quart_app.test_client()
            confirmed = await client.post(
                f"/admin/agents/{agent_id}/memory/confirmations/{confirmation_id}/confirm"
            )
            detail = await client.get(
                f"/admin/agents/{agent_id}/memory/confirmations/{confirmation_id}"
            )
            return confirmed, detail

        confirmed, detail = _run(_go())

        assert confirmed.status_code == 200
        assert _read_json(confirmed)["data"]["status"] == "confirmed"
        assert detail.status_code == 200
        assert service.authorized_ids(owner_key) == frozenset({"m1"})

    def test_admin_agent_not_owned_returns_404(self, monkeypatch):
        service = _confirmation_service()
        admin_id, agent_id, other_agent_id = uuid4(), uuid4(), uuid4()
        _wire_admin(monkeypatch, admin_id, service, agent_owned=False)
        from internal.entity.memory_owner_entity import MemoryOwnerKey

        owner_key = MemoryOwnerKey.for_admin(admin_id, agent_id=agent_id).to_key()
        confirmation_id = service.create(owner_key=owner_key, items=_items())

        async def _go():
            client = asgi_app.quart_app.test_client()
            return await client.get(
                f"/admin/agents/{other_agent_id}/memory/confirmations/{confirmation_id}"
            )

        assert _run(_go()).status_code == 404

    def test_admin_cross_agent_record_returns_404(self, monkeypatch):
        """判别性：另一 Agent 的确认记录在访问范围内也不可见（主体键不同）。"""
        service = _confirmation_service()
        admin_id, agent_a, agent_b = uuid4(), uuid4(), uuid4()
        _wire_admin(monkeypatch, admin_id, service)
        from internal.entity.memory_owner_entity import MemoryOwnerKey

        owner_key_a = MemoryOwnerKey.for_admin(admin_id, agent_id=agent_a).to_key()
        confirmation_id = service.create(owner_key=owner_key_a, items=_items())

        async def _go():
            client = asgi_app.quart_app.test_client()
            return await client.post(
                f"/admin/agents/{agent_b}/memory/confirmations/{confirmation_id}/confirm"
            )

        assert _run(_go()).status_code == 404


class TestPermissionMapping:
    def test_detail_maps_to_read_and_decision_to_manage(self):
        agent_id = uuid4()
        confirmation_id = "abc123"
        assert (
            support._admin_route_permission(
                "GET", f"/admin/agents/{agent_id}/memory/confirmations/{confirmation_id}"
            )
            == "agent_pool:read"
        )
        assert (
            support._admin_route_permission(
                "POST",
                f"/admin/agents/{agent_id}/memory/confirmations/{confirmation_id}/confirm",
            )
            == "agent_pool:manage"
        )

    def test_user_paths_are_not_blocked_for_user_jwt(self):
        """用户端确认端点必须对用户 JWT 放行（否则登录用户拿不到卡片闭环）。"""
        assert not support._is_user_api_blocked(
            "/memory/confirmations/abc123/confirm", "POST"
        )
        assert not support._is_user_api_blocked("/memory/confirmations/abc123", "GET")
