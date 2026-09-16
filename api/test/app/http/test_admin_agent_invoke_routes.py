"""管理端 Agent 执行入口路由测试。

被测逻辑（分流域 / 审计域）已在 service 层单测；本文件只验证路由的接线：
路由必须把**当前管理员的实时权限**传给 get_principal，并把执行结果/异常映射为
正确的 HTTP 状态码。
"""
import asyncio

import app.http.asgi_app as asgi_app
from app.http import support
from app.http.admin_routes_7 import register_routes

register_routes(asgi_app.quart_app)


def _admin_ctx(admin_id, permissions):
    async def _fake(permission_code=None):
        return {
            "id": str(admin_id),
            "roles": ["operator"],
            "permissions": list(permissions),
        }, None

    return _fake


class _StubAgentService:
    def __init__(self, principal):
        self._principal = principal
        self.requests = []

    def get_principal(self, *, agent_id, admin_user_id, admin_permissions):
        self.requests.append(
            {
                "agent_id": agent_id,
                "admin_user_id": admin_user_id,
                "admin_permissions": list(admin_permissions),
            }
        )
        return self._principal

    def get_agent(self, *, agent_id, admin_user_id):
        # principal 为 None 时代表"Agent 不存在/不可用"
        return object() if self._principal is not None else None


class _StubExecutionService:
    def __init__(self, result=None, error=None):
        self.calls = []
        self._result = result or {
            "outcome": "executed",
            "result": {"ok": True},
            "draft_id": None,
        }
        self._error = error

    def run(self, principal, *, board, action, payload):
        self.calls.append(
            {"board": board, "action": action, "payload": payload}
        )
        if self._error is not None:
            raise self._error
        return self._result


class _StubDraftService:
    def list_drafts(self, *, status="", policy_type=""):
        from types import SimpleNamespace

        return [
            SimpleNamespace(
                id="11111111-1111-1111-1111-111111111111",
                policy_type="builtin_tool",
                target_id="t1",
                before_config={},
                after_config={},
                diff={},
                impact={"agent_id": "22222222-2222-2222-2222-222222222222"},
                status="pending",
                created_at=None,
            ),
            SimpleNamespace(
                id="33333333-3333-3333-3333-333333333333",
                policy_type="builtin_tool",
                target_id="t2",
                before_config={},
                after_config={},
                diff={},
                impact={"agent_id": "44444444-4444-4444-4444-444444444444"},
                status="pending",
                created_at=None,
            ),
        ]


def _wire(monkeypatch, admin_id, permissions, principal="default", execution=None):
    """接线替身。

    `principal="default"` 表示用默认 principal；显式传 `None` 表示"Agent 不存在"。
    """
    from internal.entity.admin_agent_entity import AdminAgentPrincipal

    if principal == "default":
        principal = AdminAgentPrincipal(
            admin_user_id=admin_id,
            agent_id="22222222-2222-2222-2222-222222222222",
            agent_name="运维 Agent",
            effective_permissions=frozenset({"builtin_tool:read"}),
        )
    monkeypatch.setattr(
        support, "_resolve_admin_permission", _admin_ctx(admin_id, permissions)
    )
    agent_svc = _StubAgentService(principal)
    exec_svc = execution or _StubExecutionService()
    draft_svc = _StubDraftService()
    services = {
        "AdminAgentService": agent_svc,
        "AdminChangeDraftService": draft_svc,
    }
    monkeypatch.setattr(support, "_get_service", lambda cls: services[cls.__name__])

    # 替换执行链工厂（真实实现会组装 board_executor/draft/audit 并写 DB）。
    import app.http.admin_routes_7 as routes7

    monkeypatch.setattr(
        routes7,
        "_build_execution_service",
        lambda a, *, board_executor, draft_service, audit_log_service: exec_svc,
    )
    return agent_svc, exec_svc, draft_svc


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


class TestPermissionMapping:
    def test_invoke_requires_agent_pool_manage(self):
        """执行入口是写性质操作，必须映射到 agent_pool:manage（不能落到 read）。"""
        assert (
            support._admin_route_permission(
                "POST", "/admin/agents/11111111-1111-1111-1111-111111111111/invoke"
            )
            == "agent_pool:manage"
        )

    def test_drafts_list_requires_agent_pool_read(self):
        assert (
            support._admin_route_permission(
                "GET", "/admin/agents/11111111-1111-1111-1111-111111111111/drafts"
            )
            == "agent_pool:read"
        )

    def test_existing_assignable_permissions_mapping_unchanged(self):
        assert (
            support._admin_route_permission("GET", "/admin/agents/assignable-permissions")
            == "agent_pool:read"
        )


class TestInvokeEndpoint:
    def test_invoke_passes_live_admin_permissions(self, monkeypatch):
        """路由必须把**当前管理员**的实时权限传给 get_principal（运行时重算）。"""
        from uuid import uuid4

        admin_id = uuid4()
        agent_svc, exec_svc, _ = _wire(
            monkeypatch,
            admin_id,
            ["builtin_tool:read", "builtin_tool:update"],
        )
        resp = _post(
            f"/admin/agents/{uuid4()}/invoke",
            {"board": "builtin_tool", "action": "list", "payload": {}},
        )
        assert resp.status_code == 200
        body = asyncio.run(resp.get_json())
        assert body["data"]["outcome"] == "executed"
        # 路由透传的是 `admin["id"]`（字符串），与 `_resolve_admin_permission`
        # 的返回结构一致——不在这里额外做 UUID 转换，避免与既有惯例不一致。
        assert agent_svc.requests[0]["admin_user_id"] == str(admin_id)
        assert set(agent_svc.requests[0]["admin_permissions"]) == {
            "builtin_tool:read",
            "builtin_tool:update",
        }
        assert exec_svc.calls[0]["board"] == "builtin_tool"

    def test_unknown_agent_returns_404(self, monkeypatch):
        from uuid import uuid4

        _wire(monkeypatch, uuid4(), ["builtin_tool:read"], principal=None)
        resp = _post(
            f"/admin/agents/{uuid4()}/invoke",
            {"board": "builtin_tool", "action": "list"},
        )
        assert resp.status_code == 404

    def test_permission_error_returns_403(self, monkeypatch):
        from uuid import uuid4

        admin_id = uuid4()
        _wire(
            monkeypatch,
            admin_id,
            ["builtin_tool:update"],
            execution=_StubExecutionService(
                error=PermissionError("Agent 无权限执行该动作")
            ),
        )
        resp = _post(
            f"/admin/agents/{uuid4()}/invoke",
            {"board": "builtin_tool", "action": "update_enabled"},
        )
        assert resp.status_code == 403

    def test_undeclared_action_returns_400(self, monkeypatch):
        from uuid import uuid4

        _wire(
            monkeypatch,
            uuid4(),
            ["builtin_tool:update"],
            execution=_StubExecutionService(error=ValueError("未登记的动作")),
        )
        resp = _post(
            f"/admin/agents/{uuid4()}/invoke",
            {"board": "builtin_tool", "action": "nope"},
        )
        assert resp.status_code == 400

    def test_missing_board_or_action_returns_400(self, monkeypatch):
        from uuid import uuid4

        _wire(monkeypatch, uuid4(), ["builtin_tool:update"])
        resp = _post(f"/admin/agents/{uuid4()}/invoke", {})
        assert resp.status_code == 400

    def test_drafted_outcome_is_passed_through(self, monkeypatch):
        """supervised 档的草稿结果必须原样透出（含 draft_id），供前端提示。"""
        from uuid import uuid4

        _wire(
            monkeypatch,
            uuid4(),
            ["builtin_tool:update"],
            execution=_StubExecutionService(
                result={
                    "outcome": "drafted",
                    "result": None,
                    "draft_id": "55555555-5555-5555-5555-555555555555",
                }
            ),
        )
        resp = _post(
            f"/admin/agents/{uuid4()}/invoke",
            {"board": "builtin_tool", "action": "update_enabled"},
        )
        body = asyncio.run(resp.get_json())
        assert body["data"]["outcome"] == "drafted"
        assert body["data"]["draft_id"] == "55555555-5555-5555-5555-555555555555"


class TestDraftsEndpoint:
    def test_lists_only_own_agent_drafts(self, monkeypatch):
        """按 impact.agent_id 过滤——只能看到本 Agent 的草稿。"""
        agent_id = "22222222-2222-2222-2222-222222222222"
        _wire(monkeypatch, "11111111-1111-1111-1111-111111111111", ["agent_pool:read"])
        resp = _get(f"/admin/agents/{agent_id}/drafts")
        assert resp.status_code == 200
        body = asyncio.run(resp.get_json())
        items = body["data"]["items"]
        assert len(items) == 1, "另一 Agent（4444…）的草稿不得出现"
        assert items[0]["id"] == "11111111-1111-1111-1111-111111111111"

    def test_unknown_agent_returns_404(self, monkeypatch):
        from uuid import uuid4

        _wire(monkeypatch, uuid4(), ["agent_pool:read"], principal=None)
        resp = _get(f"/admin/agents/{uuid4()}/drafts")
        assert resp.status_code == 404
