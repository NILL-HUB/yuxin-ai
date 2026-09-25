"""管理端 Agent 路由测试（设计 §4.3 展示即受限）。

模式比照 test_admin_rbac_guard.py：直接 register_routes + quart test_client。
注意：conftest 的 autouse fixture 会把 support._resolve_admin_permission
替换为无条件放行（permissions=["*"]），因此本文件专门覆盖该替身来测
"展示即受限"。
"""
import asyncio

import app.http.asgi_app as asgi_app
from app.http import support
from app.http.admin_routes_7 import register_routes

register_routes(asgi_app.quart_app)


def _admin_ctx(admin_id, permissions):
    async def _fake(permission_code=None):
        return {"id": str(admin_id), "roles": [], "permissions": list(permissions)}, None

    return _fake


def _stub_service(monkeypatch):
    """让端点用**真实**的 AdminAgentService（仅替身注入 db），而非重写其逻辑。

    为什么不能在这里重写 `list_assignable_permissions`：那会让测试只验证
    "替身返回了什么"，而**完全不覆盖**真实实现——把实现改成返回全量目录时
    测试依然通过（假通过）。该方法是纯计算、不触碰 db，故传 None 即可。
    """
    from internal.service.admin_agent_service import AdminAgentService

    service = AdminAgentService(db=None)
    monkeypatch.setattr(support, "_get_service", lambda cls: service)


class TestAssignablePermissionsEndpoint:
    def test_returns_only_intersection(self, monkeypatch):
        """A 管理员只有模型池/工具池/Agent池 → 可分配列表只有这几项。"""
        admin_id = "11111111-1111-1111-1111-111111111111"
        perms = [
            "model_pool:read", "model_pool:manage", "agent_pool:read",
            "agent_pool:manage", "tool_governance:read", "tool_governance:manage",
        ]
        monkeypatch.setattr(support, "_resolve_admin_permission", _admin_ctx(admin_id, perms))
        _stub_service(monkeypatch)

        async def _run():
            client = asgi_app.quart_app.test_client()
            resp = await client.get("/admin/agents/assignable-permissions")
            return resp

        resp = asyncio.run(_run())
        assert resp.status_code == 200
        body = asyncio.run(resp.get_json())
        # 响应体是 {"codes": [...]}（由 AdminAgentAssignablePermissionsResp 包裹，
        # 便于日后追加 total/分组等字段而不破坏契约）。
        codes = body["data"]["codes"]
        assert set(codes) == set(perms)
        # 不含管理员没有的
        assert "user:read" not in codes
        assert "order:view" not in codes
        # 同时返回同源语义明细（供前端显示中文名，避免另调全量 /admin/permissions）
        permissions = body["data"]["permissions"]
        assert [item["code"] for item in permissions] == codes
        assert all("name" in item and "resource" in item for item in permissions)
        # 语义名称来自 RBAC 目录（单一事实源）
        from internal.core.rbac import PERMISSION_BY_CODE

        for item in permissions:
            assert item["name"] == PERMISSION_BY_CODE[item["code"]].name

    def test_excludes_banned_even_if_admin_holds_them(self, monkeypatch):
        admin_id = "22222222-2222-2222-2222-222222222222"
        perms = ["role:read", "permission:read", "admin_user:read", "model_pool:read"]
        monkeypatch.setattr(support, "_resolve_admin_permission", _admin_ctx(admin_id, perms))
        _stub_service(monkeypatch)

        async def _run():
            client = asgi_app.quart_app.test_client()
            return await client.get("/admin/agents/assignable-permissions")

        resp = asyncio.run(_run())
        body = asyncio.run(resp.get_json())
        assert body["data"]["codes"] == ["model_pool:read"]
