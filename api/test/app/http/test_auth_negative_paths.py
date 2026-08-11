"""A1 轨鉴权负路径测试：Quart test_client 验证缺 token 401、Bearer 加载、openapi 鉴权。

由 A2 轨 test/internal/handler/test_route_auth_security.py 迁移而来。
注意：Quart 侧 /openapi/chat 复用 _resolve_account（JWT/admin token），
不再走 Flask 侧的 ApiKeyService Bearer API-Key 鉴权，因此对应成功路径未迁移。
"""

import asyncio
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest

from app.http import asgi_app
from app.http import support
from internal.exception import UnauthorizedException
from internal.service import HomeService, JwtService


HOME_ACCOUNT_ID = UUID("00000000-0000-0000-0000-000000000011")


class TestAuthNegativePaths:
    def test_home_intent_should_reject_missing_authorization(self):
        async def _run():
            async with asgi_app.quart_app.test_client() as client:
                resp = await client.get("/home/intent")
                payload = await resp.json
                return resp, payload

        resp, payload = asyncio.run(_run())

        assert resp.status_code == 401
        assert payload["code"] == "unauthorized"

    def test_home_intent_should_accept_bearer_token_and_load_current_user(self, monkeypatch):
        account = SimpleNamespace(
            id=HOME_ACCOUNT_ID,
            is_authenticated=True,
            name="tester",
            email="tester@example.com",
        )
        call_state = {}

        monkeypatch.setattr(
            JwtService,
            "parse_token",
            lambda token: {"sub": str(HOME_ACCOUNT_ID), "jti": f"session:{token}"},
        )
        monkeypatch.setattr(support, "_load_account", lambda _aid: account)
        monkeypatch.setattr(
            support,
            "_get_services",
            lambda: (
                None,
                None,
                SimpleNamespace(validate_access_session=lambda payload: None),
                None,
            ),
        )

        def _get_user_intent(account):
            call_state["user"] = account
            return {
                "intent": "build_app",
                "confidence": 0.88,
                "suggested_actions": [
                    {"label": "创建应用", "action": "create_app", "icon": "sparkles"}
                ],
                "is_default": False,
            }

        monkeypatch.setattr(
            support,
            "_get_service",
            lambda cls: SimpleNamespace(get_user_intent=_get_user_intent)
            if cls is HomeService
            else None,
        )

        async def _run():
            async with asgi_app.quart_app.test_client() as client:
                resp = await client.get(
                    "/home/intent", headers={"Authorization": "Bearer home-token"}
                )
                payload = await resp.json
                return resp, payload

        resp, payload = asyncio.run(_run())

        assert resp.status_code == 200
        assert payload["code"] == "success"
        assert payload["data"]["intent"] == "build_app"
        assert payload["data"]["confidence"] == pytest.approx(0.88)
        assert payload["data"]["suggested_actions"][0]["action"] == "create_app"
        assert call_state["user"].id == account.id
        assert call_state["user"].is_authenticated is True

    def test_user_token_should_reject_removed_user_api(self, monkeypatch):
        """用户端已收敛的接口，普通用户 JWT 应直接返回 403。"""
        account = SimpleNamespace(
            id=HOME_ACCOUNT_ID,
            is_authenticated=True,
            name="tester",
            email="tester@example.com",
        )
        monkeypatch.setattr(
            JwtService,
            "parse_token",
            lambda token: {"sub": str(HOME_ACCOUNT_ID)},
        )
        monkeypatch.setattr(support, "_load_account", lambda _aid: account)

        async def _run():
            async with asgi_app.quart_app.test_client() as client:
                resp = await client.post(
                    "/memory/write",
                    headers={"Authorization": "Bearer user-token"},
                    json={"content": "blocked"},
                )
                payload = await resp.json
                return resp, payload

        resp, payload = asyncio.run(_run())

        assert resp.status_code == 403
        assert payload["code"] == "forbidden"

    @pytest.mark.parametrize(
        ("method", "path"),
        [
            ("GET", "/apps"),
            ("GET", "/workflows"),
            ("GET", "/api-tools"),
            ("GET", "/mcp-providers"),
            ("GET", "/skills"),
            ("GET", "/builtin-tools"),
            ("GET", "/openapi/api-keys"),
            ("GET", "/platform/00000000-0000-0000-0000-000000000011/wechat-config"),
            ("GET", "/routing-logs/summary"),
            ("GET", "/tool-confirmations"),
            (
                "GET",
                "/conversations/00000000-0000-0000-0000-000000000011/variables",
            ),
            ("POST", "/ai/optimize-prompt"),
            ("POST", "/ai/chat"),
            ("POST", "/ai/openapi-schema-chat"),
            ("POST", "/ai/mcp-schema-chat"),
            ("POST", "/workflows/import"),
            ("POST", "/api/async/chat/completion"),
            ("POST", "/async/chat/completion"),
            ("POST", "/upload-files/file"),
            (
                "POST",
                "/conversations/00000000-0000-0000-0000-000000000011/is-pinned",
            ),
        ],
    )
    def test_user_token_should_reject_non_consumed_user_api(self, monkeypatch, method, path):
        account = SimpleNamespace(
            id=HOME_ACCOUNT_ID,
            is_authenticated=True,
            name="tester",
            email="tester@example.com",
        )
        monkeypatch.setattr(
            JwtService,
            "parse_token",
            lambda token: {"sub": str(HOME_ACCOUNT_ID)},
        )
        monkeypatch.setattr(support, "_load_account", lambda _aid: account)

        async def _run():
            async with asgi_app.quart_app.test_client() as client:
                body = {}
                if path in ("/api/async/chat/completion", "/async/chat/completion"):
                    body = {
                        "app_id": str(uuid4()),
                        "account_id": str(HOME_ACCOUNT_ID),
                        "query": "hello",
                    }
                if method == "POST":
                    resp = await client.post(
                        path,
                        headers={"Authorization": "Bearer user-token"},
                        json=body,
                    )
                else:
                    resp = await client.get(
                        path,
                        headers={"Authorization": "Bearer user-token"},
                    )
                payload = await resp.json
                return resp, payload

        resp, payload = asyncio.run(_run())

        assert resp.status_code == 403
        assert payload["code"] == "forbidden"

    def test_openapi_chat_should_reject_missing_authorization(self):
        async def _run():
            async with asgi_app.quart_app.test_client() as client:
                resp = await client.post(
                    "/openapi/chat", json={"app_id": str(uuid4()), "query": "hello"}
                )
                payload = await resp.json
                return resp, payload

        resp, payload = asyncio.run(_run())

        assert resp.status_code == 401
        assert payload["code"] == "unauthorized"

    def test_openapi_chat_should_reject_invalid_bearer_token(self, monkeypatch):
        monkeypatch.setattr(
            JwtService,
            "parse_token",
            lambda _token: (_ for _ in ()).throw(UnauthorizedException("bad token")),
        )
        monkeypatch.setattr(
            "internal.service.admin_user_service.AdminUserService.get_current_admin_from_token",
            lambda _self, token: None,
        )

        async def _run():
            async with asgi_app.quart_app.test_client() as client:
                resp = await client.post(
                    "/openapi/chat",
                    headers={"Authorization": "Bearer bad-token"},
                    json={"app_id": str(uuid4()), "query": "hello"},
                )
                payload = await resp.json
                return resp, payload

        resp, payload = asyncio.run(_run())

        assert resp.status_code == 401
        assert payload["code"] == "unauthorized"
