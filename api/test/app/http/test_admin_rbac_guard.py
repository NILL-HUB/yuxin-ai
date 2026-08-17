import asyncio

import app.http.asgi_app as asgi_app
from app.http import support


class TestAdminRoutePermissionMap:
    def test_every_registered_admin_route_has_a_permission(self):
        seen = {}
        for rule in asgi_app.quart_app.url_map.iter_rules():
            if rule.rule.startswith("/admin"):
                seen[rule.rule] = tuple(sorted(rule.methods or []))

        missing = []
        for rule, methods in seen.items():
            if rule in support._ADMIN_AUTH_ONLY_PATHS or rule in support._ADMIN_PUBLIC_PATHS:
                continue
            for method in methods:
                if method in {"HEAD", "OPTIONS"}:
                    continue
                if not support._admin_route_permission(method, rule):
                    missing.append((method, rule))

        assert missing == []

    def test_unknown_admin_path_fails_closed(self):
        assert support._admin_route_permission("GET", "/admin/unknown-resource") is None
        assert support._admin_route_permission("POST", "/admin/unknown-resource") is None

    def test_route_permission_uses_readable_codes(self):
        assert support._admin_route_permission("GET", "/admin/roles") == "role:read"
        assert support._admin_route_permission("POST", "/admin/roles") == "role:create"
        assert support._admin_route_permission("GET", "/admin/apps") == "app:read"
        assert support._admin_route_permission("PATCH", "/admin/apps/<uuid:app_id>") == "app:update"
        assert support._admin_route_permission("POST", "/admin/users/<uuid:account_id>/disable") == "user:disable"
        assert support._admin_route_permission("POST", "/admin/recycle-bin/1/restore") == "recycle_bin:write"


class TestAdminRbacGuard:
    def test_admin_endpoint_requires_admin_token(self, monkeypatch):
        async def _deny(permission_code=None):
            return None, support._err("unauthorized", "管理员凭证无效", 401)

        monkeypatch.setattr(support, "_resolve_admin_permission", _deny)

        async def _run():
            async with asgi_app.quart_app.test_client() as client:
                resp = await client.get("/admin/roles")
                return resp, await resp.json

        resp, payload = asyncio.run(_run())

        assert resp.status_code == 401
        assert payload["code"] == "unauthorized"

    def test_admin_endpoint_denies_missing_permission(self, monkeypatch):
        async def _deny(permission_code=None):
            return None, support._err("forbidden", "无权限执行该操作", 403)

        monkeypatch.setattr(support, "_resolve_admin_permission", _deny)

        async def _run():
            async with asgi_app.quart_app.test_client() as client:
                resp = await client.get("/admin/roles")
                return resp, await resp.json

        resp, payload = asyncio.run(_run())

        assert resp.status_code == 403
        assert payload["code"] == "forbidden"

    def test_login_endpoint_is_public(self, monkeypatch):
        async def _never_called(permission_code=None):
            raise AssertionError("login should not require admin permission")

        monkeypatch.setattr(support, "_resolve_admin_permission", _never_called)

        async def _run():
            async with asgi_app.quart_app.test_client() as client:
                resp = await client.post("/admin/auth/login", json={})
                return resp

        resp = asyncio.run(_run())
        assert resp.status_code == 400
