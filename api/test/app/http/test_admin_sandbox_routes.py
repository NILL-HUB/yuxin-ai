"""沙箱 Admin 路由测试。

三层守卫：
1. 路径 → 权限映射（全局 before_request 的实际执行依据，新增权限点必须同步）；
2. 路由注册（5 个端点均在 app.url_map 上）；
3. 端点行为（经 support._get_service 注入 fake 服务）。
"""
import asyncio
from types import SimpleNamespace
from uuid import uuid4

import app.http.asgi_app as asgi_app
from app.http import support
from app.http.admin_routes_7 import register_routes
from internal.exception import ValidateErrorException

register_routes(asgi_app.quart_app)


class _FakeSandboxService:
    def __init__(self):
        self.calls = []

    def overview(self):
        self.calls.append("overview")
        return [
            {
                "capability": "code_interpreter",
                "active_backend": "disabled",
                "enabled": False,
                "reason": "该能力域已显式关闭（未开通）",
                "configs": {},
                "backends": [{"backend": "disabled", "label": "未开通", "is_active": True}],
            }
        ]

    def list_configs_view(self, capability=None):
        self.calls.append(("list_configs_view", capability))
        return [
            {
                "capability": "workflow_code",
                "backend": "http_sandbox",
                "label": "HTTP 远端执行服务",
                "configs": {"endpoint": "", "timeout_seconds": 60},
                "is_active": False,
            }
        ]

    def upsert_config(self, capability, backend, configs, credentials=None):
        self.calls.append(("upsert_config", capability, backend, configs, credentials or {}))
        if capability == "not_a_capability":
            raise ValidateErrorException("不支持的沙箱能力域")
        return SimpleNamespace(
            capability=capability,
            backend=backend,
            label=backend,
            configs=configs,
            credentials={},
            is_active=False,
        )

    def set_active_backend(self, capability, backend):
        self.calls.append(("set_active_backend", capability, backend))
        if backend == "not_allowed":
            raise ValidateErrorException("不支持的后端")
        return SimpleNamespace(
            capability=capability,
            backend=backend,
            label=backend,
            configs={},
            is_active=True,
        )

    def probe(self, capability):
        self.calls.append(("probe", capability))
        return {"capability": capability, "backend": "disabled", "ok": False, "reason": "未开通"}

    @staticmethod
    def serialize_config(row):
        return {
            "capability": row.capability,
            "backend": row.backend,
            "label": row.label,
            "configs": row.configs,
            "is_active": row.is_active,
        }


def _setup(monkeypatch):
    from internal.service.sandbox.sandbox_config_service import SandboxConfigService

    service = _FakeSandboxService()
    account = SimpleNamespace(id=uuid4())

    async def _fake_resolve_admin_permission(permission_code=None):
        return account, None

    monkeypatch.setattr(support, "_resolve_admin_permission", _fake_resolve_admin_permission)
    monkeypatch.setattr(
        support, "_get_service", lambda cls: service if cls is SandboxConfigService else None
    )
    return service


# --------------------------------------------------------------------------- #
#  1. 路径 → 权限映射
# --------------------------------------------------------------------------- #
def test_admin_route_permission_maps_sandbox_paths():
    assert support._admin_route_permission("GET", "/admin/sandbox/overview") == "sandbox:read"
    assert support._admin_route_permission("GET", "/admin/sandbox/configs") == "sandbox:read"
    assert support._admin_route_permission("POST", "/admin/sandbox/activate") == "sandbox:update"
    assert support._admin_route_permission("POST", "/admin/sandbox/probe") == "sandbox:update"


# --------------------------------------------------------------------------- #
#  2. 路由注册
# --------------------------------------------------------------------------- #
def test_sandbox_routes_are_registered():
    rules = {rule.rule for rule in asgi_app.quart_app.url_map.iter_rules()}
    assert "/admin/sandbox/overview" in rules
    assert "/admin/sandbox/configs" in rules
    assert "/admin/sandbox/configs/<string:capability>/<string:backend>" in rules
    assert "/admin/sandbox/activate" in rules
    assert "/admin/sandbox/probe" in rules


# --------------------------------------------------------------------------- #
#  3. 端点行为
# --------------------------------------------------------------------------- #
class TestAdminSandboxRoutes:
    def test_overview(self, monkeypatch):
        service = _setup(monkeypatch)

        async def _run():
            async with asgi_app.quart_app.test_client() as client:
                resp = await client.get("/admin/sandbox/overview")
                return resp, await resp.json

        resp, payload = asyncio.run(_run())
        assert resp.status_code == 200
        assert payload["data"]["items"][0]["capability"] == "code_interpreter"
        assert service.calls[0] == "overview"

    def test_list_configs_passes_capability_filter(self, monkeypatch):
        service = _setup(monkeypatch)

        async def _run():
            async with asgi_app.quart_app.test_client() as client:
                resp = await client.get("/admin/sandbox/configs?capability=workflow_code")
                return resp, await resp.json

        resp, payload = asyncio.run(_run())
        assert resp.status_code == 200
        assert service.calls[0] == ("list_configs_view", "workflow_code")
        assert payload["data"]["items"][0]["backend"] == "http_sandbox"

    def test_activate_requires_capability_and_backend(self, monkeypatch):
        _setup(monkeypatch)

        async def _run():
            async with asgi_app.quart_app.test_client() as client:
                resp = await client.post("/admin/sandbox/activate", json={"capability": "x"})
                return resp, await resp.json

        resp, payload = asyncio.run(_run())
        assert resp.status_code == 400
        assert payload["code"] == "validate_error"

    def test_upsert_config_forwards_credentials(self, monkeypatch):
        service = _setup(monkeypatch)

        async def _run():
            async with asgi_app.quart_app.test_client() as client:
                resp = await client.post(
                    "/admin/sandbox/configs/code_interpreter/baidu_cfc",
                    json={
                        "configs": {"template_alias": "t"},
                        "credentials": {"E2B_API_KEY": "secret", "E2B_DOMAIN": "d.example.com"},
                    },
                )
                return resp, await resp.json

        resp, _payload = asyncio.run(_run())
        assert resp.status_code == 200
        upsert_calls = [call for call in service.calls if isinstance(call, tuple) and call[0] == "upsert_config"]
        assert upsert_calls, "upsert_config 未被调用"
        assert upsert_calls[-1][4] == {"E2B_API_KEY": "secret", "E2B_DOMAIN": "d.example.com"}

    def test_upsert_config_without_credentials_sends_empty(self, monkeypatch):
        service = _setup(monkeypatch)

        async def _run():
            async with asgi_app.quart_app.test_client() as client:
                resp = await client.post(
                    "/admin/sandbox/configs/code_interpreter/baidu_cfc",
                    json={"configs": {"template_alias": "t"}},
                )
                return resp, await resp.json

        resp, _payload = asyncio.run(_run())
        assert resp.status_code == 200
        upsert_calls = [call for call in service.calls if isinstance(call, tuple) and call[0] == "upsert_config"]
        # 未带 credentials 时传空 dict（服务层据此保持既有凭证不变）
        assert upsert_calls[-1][4] == {}

    def test_activate_rejects_disallowed_backend(self, monkeypatch):
        _setup(monkeypatch)

        async def _run():
            async with asgi_app.quart_app.test_client() as client:
                resp = await client.post(
                    "/admin/sandbox/activate",
                    json={"capability": "workflow_code", "backend": "not_allowed"},
                )
                return resp, await resp.json

        resp, payload = asyncio.run(_run())
        assert resp.status_code == 400
        assert payload["code"] == "validate_error"

    def test_upsert_config_rejects_unknown_capability(self, monkeypatch):
        _setup(monkeypatch)

        async def _run():
            async with asgi_app.quart_app.test_client() as client:
                resp = await client.post(
                    "/admin/sandbox/configs/not_a_capability/baidu_cfc",
                    json={"configs": {"template_alias": "t"}},
                )
                return resp, await resp.json

        resp, payload = asyncio.run(_run())
        assert resp.status_code == 400
        assert payload["code"] == "validate_error"

    def test_probe_requires_capability(self, monkeypatch):
        _setup(monkeypatch)

        async def _run():
            async with asgi_app.quart_app.test_client() as client:
                resp = await client.post("/admin/sandbox/probe", json={})
                return resp, await resp.json

        resp, payload = asyncio.run(_run())
        assert resp.status_code == 400
        assert payload["code"] == "validate_error"
