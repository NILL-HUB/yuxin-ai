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

    def test_delete_admin_user_requires_dedicated_permission(self):
        """删除管理员必须用专用 admin_user:delete，不得继承 admin_user:update。

        若映射缺失或兜底到 update，则只持有"更新"权限的管理员即可删除账号
        （权限放大）。这是本改动新增端点时最易踩的坑。
        """
        assert (
            support._admin_route_permission("DELETE", "/admin/admin-users/<uuid:admin_id>")
            == "admin_user:delete"
        )
        # 对照：其它方法仍映射到各自权限点，未被误改
        assert support._admin_route_permission("GET", "/admin/admin-users") == "admin_user:read"
        assert support._admin_route_permission("POST", "/admin/admin-users") == "admin_user:create"
        assert support._admin_route_permission("PATCH", "/admin/admin-users/<uuid:admin_id>") == "admin_user:update"
        assert support._admin_route_permission("POST", "/admin/admin-users/<uuid:admin_id>/disable") == "admin_user:disable"

    def test_unregistered_admin_users_method_fails_closed(self):
        """未显式登记的 admin-users 方法必须 fail closed（返回 None 被拒）。

        历史实现以 `return "admin_user:update"` 兜底，会让任何新增方法
        静默继承 update 权限——这是权限放大隐患，故改为拒绝。
        """
        assert support._admin_route_permission("PUT", "/admin/admin-users/<uuid:admin_id>") == "admin_user:update"
        # 未登记的方法（如 TRACE）不得落到任何权限点
        assert support._admin_route_permission("TRACE", "/admin/admin-users") is None

    def test_admin_distribution_capability_is_removed(self):
        """管理端不提供分销能力：分销上下级绑定是用户端独有功能。

        历史路径 `/admin/distribution/*` 与 `/admin/users/<id>/superior` 必须
        fail closed（返回 None 被拒绝），且不能被 `admin/users` 通用分支误判为
        `user:update` 而放行。
        """
        assert support._admin_route_permission("GET", "/admin/distribution/overview") is None
        assert support._admin_route_permission("GET", "/admin/distribution/relations") is None
        assert support._admin_route_permission("PUT", "/admin/users/<user_id>/superior") is None
        assert support._admin_route_permission("PUT", "/admin/users/abc/superior") is None
        # 同前缀的普通用户管理路由不受影响
        assert support._admin_route_permission("PATCH", "/admin/users/<uuid:account_id>") == "user:update"
        assert support._admin_route_permission("GET", "/admin/users") == "user:read"


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
