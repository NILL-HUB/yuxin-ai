"""app.http.admin_routes_7 迁移端点单元测试。

覆盖 admin_rbac_handler / admin_storage_handler / admin_agent_pool_handler /
admin_sub_pool_handler / admin_customer_user_handler / admin_billing_plan_handler
的 Quart async 端点（每个端点至少一个用例）。

模式与 test/app/http/test_asgi_app.py 一致：asyncio.run + quart_app.test_client，
monkeypatch asgi_app._get_service 返回 SimpleNamespace fake service。
"""

import asyncio
import datetime as _dt
from types import SimpleNamespace
from uuid import uuid4

import app.http.asgi_app as asgi_app
from app.http import support
from app.http.admin_routes_7 import register_routes

register_routes(asgi_app.quart_app)


def _paginator(page=1, page_size=20):
    return {
        "total_record": 1,
        "total_page": 1,
        "current_page": page,
        "page_size": page_size,
    }


def _role():
    return {
        "id": str(uuid4()),
        "code": "admin",
        "name": "管理员",
        "description": "",
        "is_system": True,
        "permissions": ["role:read"],
    }


def _permission():
    return {
        "id": str(uuid4()),
        "code": "role:read",
        "name": "查看角色",
        "resource": "role",
        "action": "read",
    }


def _customer_user():
    return {
        "id": str(uuid4()),
        "email": "user@example.com",
        "name": "客户用户",
        "avatar": "",
        "status": "active",
        "disabled_at": None,
        "disabled_by": None,
        "disabled_reason": "",
        "last_login_at": 1710000000,
        "last_login_ip": "1.2.3.4",
        "created_at": 1710000000,
        "sessions": [],
        "is_online": True,
    }


def _plan():
    return {
        "id": str(uuid4()),
        "code": "basic",
        "name": "基础版",
        "description": "",
        "duration_days": 30,
        "grant_token_credits": 100,
        "price": "9.90",
        "status": "active",
        "sort_order": 0,
        "created_at": 1710000000,
        "updated_at": 1710000000,
        "entitlements": [],
    }


def _storage_config(backend="local"):
    return SimpleNamespace(
        id=str(uuid4()),
        backend=backend,
        configs={"access_key_id": "ak"},
        is_active=True,
        created_at=_dt.datetime(2026, 1, 1, 8, 0),
        updated_at=_dt.datetime(2026, 1, 1, 8, 0),
    )


def _migration_file():
    return SimpleNamespace(
        id=uuid4(),
        name="file.pdf",
        key="uploads/file.pdf",
        size=1024,
        extension="pdf",
        mime_type="application/pdf",
        storage_backend="local",
        created_at=_dt.datetime(2026, 1, 1, 8, 0),
    )


def _agent_pool():
    return {
        "id": str(uuid4()),
        "app_id": str(uuid4()),
        "enabled": True,
        "health_status": "healthy",
        "last_health_check_at": 1710000000,
        "metadata": {},
        "preset_prompt_summary": None,
        "created_at": 1710000000,
        "updated_at": 1710000000,
    }


def _sub_pool():
    return {"id": str(uuid4()), "name": "子池A"}


class TestAdminRbacRoutes:
    def _setup(self, monkeypatch):
        from internal.service.admin_rbac_service import AdminRbacService

        service = SimpleNamespace(
            list_roles=lambda: [_role()],
            create_role=lambda **kw: _role(),
            get_role=lambda role_code: _role(),
            update_role=lambda role_code, **kw: _role(),
            delete_role=lambda role_code, **kw: None,
            list_permissions=lambda: [_permission()],
        )
        monkeypatch.setattr(support, "_get_service", lambda cls: service if cls is AdminRbacService else None)
        return service

    def test_list_roles(self, monkeypatch):
        self._setup(monkeypatch)

        async def _run():
            async with asgi_app.quart_app.test_client() as client:
                resp = await client.get("/admin/roles")
                return resp, await resp.json

        resp, payload = asyncio.run(_run())
        assert resp.status_code == 200
        assert payload["code"] == "success"
        assert len(payload["data"]) == 1
        assert payload["data"][0]["code"] == "admin"

    def test_create_role(self, monkeypatch):
        self._setup(monkeypatch)

        async def _run():
            async with asgi_app.quart_app.test_client() as client:
                resp = await client.post(
                    "/admin/roles",
                    json={"code": "ops", "name": "运营", "permission_codes": []},
                )
                return resp, await resp.json

        resp, payload = asyncio.run(_run())
        assert resp.status_code == 200
        assert payload["code"] == "success"
        assert payload["data"]["code"] == "admin"

    def test_create_role_requires_code(self, monkeypatch):
        self._setup(monkeypatch)

        async def _run():
            async with asgi_app.quart_app.test_client() as client:
                resp = await client.post("/admin/roles", json={"name": "运营"})
                return resp, await resp.json

        resp, payload = asyncio.run(_run())
        assert resp.status_code == 400
        assert payload["code"] == "validate_error"
        assert "角色编码不能为空" in payload["message"]

    def test_get_role(self, monkeypatch):
        self._setup(monkeypatch)

        async def _run():
            async with asgi_app.quart_app.test_client() as client:
                resp = await client.get("/admin/roles/operator")
                return resp, await resp.json

        resp, payload = asyncio.run(_run())
        assert resp.status_code == 200
        assert payload["code"] == "success"

    def test_update_role(self, monkeypatch):
        self._setup(monkeypatch)

        async def _run():
            async with asgi_app.quart_app.test_client() as client:
                resp = await client.patch(
                    "/admin/roles/operator", json={"name": "新名称"}
                )
                return resp, await resp.json

        resp, payload = asyncio.run(_run())
        assert resp.status_code == 200
        assert payload["code"] == "success"

    def test_delete_role(self, monkeypatch):
        self._setup(monkeypatch)

        async def _run():
            async with asgi_app.quart_app.test_client() as client:
                resp = await client.delete("/admin/roles/operator")
                return resp, await resp.json

        resp, payload = asyncio.run(_run())
        assert resp.status_code == 200
        assert payload["message"] == "删除角色成功"

    def test_list_permissions(self, monkeypatch):
        self._setup(monkeypatch)

        async def _run():
            async with asgi_app.quart_app.test_client() as client:
                resp = await client.get("/admin/permissions")
                return resp, await resp.json

        resp, payload = asyncio.run(_run())
        assert resp.status_code == 200
        assert len(payload["data"]) == 1
        assert payload["data"][0]["code"] == "role:read"


class TestAdminCustomerUserRoutes:
    def _setup(self, monkeypatch):
        from internal.service.admin_customer_user_service import AdminCustomerUserService

        service = SimpleNamespace(
            list_customer_users=lambda **kw: {
                "list": [_customer_user()],
                "paginator": _paginator(kw.get("current_page", 1), kw.get("page_size", 20)),
            },
            get_customer_user=lambda account_id: _customer_user(),
            disable_customer_user=lambda account_id, **kw: _customer_user(),
            enable_customer_user=lambda account_id, **kw: _customer_user(),
            revoke_customer_user_sessions=lambda account_id, **kw: {"revoked_sessions": 2},
        )
        monkeypatch.setattr(
            support, "_get_service", lambda cls: service if cls is AdminCustomerUserService else None
        )
        return service

    def test_list(self, monkeypatch):
        self._setup(monkeypatch)

        async def _run():
            async with asgi_app.quart_app.test_client() as client:
                resp = await client.get("/admin/users?current_page=1&page_size=10")
                return resp, await resp.json

        resp, payload = asyncio.run(_run())
        assert resp.status_code == 200
        assert payload["code"] == "success"
        assert len(payload["data"]["list"]) == 1
        assert payload["data"]["paginator"]["page_size"] == 10

    def test_get(self, monkeypatch):
        self._setup(monkeypatch)

        async def _run():
            async with asgi_app.quart_app.test_client() as client:
                resp = await client.get(f"/admin/users/{uuid4()}")
                return resp, await resp.json

        resp, payload = asyncio.run(_run())
        assert resp.status_code == 200
        assert payload["code"] == "success"

    def test_disable(self, monkeypatch):
        self._setup(monkeypatch)

        async def _run():
            async with asgi_app.quart_app.test_client() as client:
                resp = await client.post(
                    f"/admin/users/{uuid4()}/disable", json={"reason": "违规"}
                )
                return resp, await resp.json

        resp, payload = asyncio.run(_run())
        assert resp.status_code == 200
        assert payload["code"] == "success"

    def test_enable(self, monkeypatch):
        self._setup(monkeypatch)

        async def _run():
            async with asgi_app.quart_app.test_client() as client:
                resp = await client.post(f"/admin/users/{uuid4()}/enable")
                return resp, await resp.json

        resp, payload = asyncio.run(_run())
        assert resp.status_code == 200
        assert payload["code"] == "success"

    def test_revoke_sessions(self, monkeypatch):
        self._setup(monkeypatch)

        async def _run():
            async with asgi_app.quart_app.test_client() as client:
                resp = await client.post(f"/admin/users/{uuid4()}/sessions/revoke")
                return resp, await resp.json

        resp, payload = asyncio.run(_run())
        assert resp.status_code == 200
        assert payload["data"]["revoked_sessions"] == 2


class TestAdminBillingPlanRoutes:
    def _setup(self, monkeypatch):
        from internal.service.admin_billing_plan_service import AdminBillingPlanService

        service = SimpleNamespace(
            list_plans=lambda **kw: {
                "list": [_plan()],
                "paginator": _paginator(kw.get("current_page", 1), kw.get("page_size", 20)),
            },
            get_plan=lambda plan_id: _plan(),
            create_plan=lambda payload, **kw: _plan(),
            update_plan=lambda plan_id, payload, **kw: _plan(),
            set_plan_status=lambda plan_id, status, **kw: _plan(),
        )
        monkeypatch.setattr(
            support, "_get_service", lambda cls: service if cls is AdminBillingPlanService else None
        )
        return service

    def test_list(self, monkeypatch):
        self._setup(monkeypatch)

        async def _run():
            async with asgi_app.quart_app.test_client() as client:
                resp = await client.get("/admin/plans")
                return resp, await resp.json

        resp, payload = asyncio.run(_run())
        assert resp.status_code == 200
        assert payload["code"] == "success"
        assert len(payload["data"]["list"]) == 1

    def test_create(self, monkeypatch):
        self._setup(monkeypatch)

        async def _run():
            async with asgi_app.quart_app.test_client() as client:
                resp = await client.post(
                    "/admin/plans", json={"code": "pro", "name": "专业版"}
                )
                return resp, await resp.json

        resp, payload = asyncio.run(_run())
        assert resp.status_code == 200
        assert payload["code"] == "success"

    def test_get(self, monkeypatch):
        self._setup(monkeypatch)

        async def _run():
            async with asgi_app.quart_app.test_client() as client:
                resp = await client.get(f"/admin/plans/{uuid4()}")
                return resp, await resp.json

        resp, payload = asyncio.run(_run())
        assert resp.status_code == 200
        assert payload["code"] == "success"

    def test_update(self, monkeypatch):
        self._setup(monkeypatch)

        async def _run():
            async with asgi_app.quart_app.test_client() as client:
                resp = await client.post(
                    f"/admin/plans/{uuid4()}", json={"name": "新名称"}
                )
                return resp, await resp.json

        resp, payload = asyncio.run(_run())
        assert resp.status_code == 200
        assert payload["code"] == "success"

    def test_set_status(self, monkeypatch):
        self._setup(monkeypatch)

        async def _run():
            async with asgi_app.quart_app.test_client() as client:
                resp = await client.post(
                    f"/admin/plans/{uuid4()}/status", json={"status": "disabled"}
                )
                return resp, await resp.json

        resp, payload = asyncio.run(_run())
        assert resp.status_code == 200
        assert payload["code"] == "success"

    def test_set_status_requires_status(self, monkeypatch):
        self._setup(monkeypatch)

        async def _run():
            async with asgi_app.quart_app.test_client() as client:
                resp = await client.post(f"/admin/plans/{uuid4()}/status", json={})
                return resp, await resp.json

        resp, payload = asyncio.run(_run())
        assert resp.status_code == 400
        assert payload["code"] == "validate_error"


class TestAdminStorageRoutes:
    def _setup(self, monkeypatch):
        from internal.service.storage.runtime_storage_service import RuntimeStorageProxy
        from internal.service.storage.storage_config_service import StorageConfigService
        from internal.service.storage.storage_migration_service import StorageMigrationService

        config_service = SimpleNamespace(
            get_active_backend=lambda: "local",
            list_configs=lambda: [_storage_config()],
            get_storage_stats=lambda: {"total_files": 2, "total_size": 2048},
            upsert_config=lambda backend, configs=None: _storage_config(backend),
            set_active_backend=lambda backend: _storage_config(backend),
        )
        migration_service = SimpleNamespace(
            list_files=lambda **kw: {
                "items": [_migration_file()],
                "total": 1,
                "page": 1,
                "page_size": 20,
                "total_pages": 1,
                "total_record": 1,
            },
            list_extensions=lambda source_backend: ["pdf", "png"],
            migrate=lambda **kw: {"total": 1, "succeeded": 1, "failed": 0, "failures": []},
        )
        runtime_service = SimpleNamespace(
            get_file_url=lambda key, download_name=None, backend=None: "http://example.com/" + key,
        )
        services = {
            StorageConfigService: config_service,
            StorageMigrationService: migration_service,
            RuntimeStorageProxy: runtime_service,
        }
        monkeypatch.setattr(support, "_get_service", lambda cls: services.get(cls))
        return config_service, migration_service

    def test_overview(self, monkeypatch):
        self._setup(monkeypatch)

        async def _run():
            async with asgi_app.quart_app.test_client() as client:
                resp = await client.get("/admin/storage/overview")
                return resp, await resp.json

        resp, payload = asyncio.run(_run())
        assert resp.status_code == 200
        assert payload["code"] == "success"
        assert payload["data"]["active_backend"] == "local"
        assert len(payload["data"]["backend_items"]) == 1

    def test_list_configs(self, monkeypatch):
        self._setup(monkeypatch)

        async def _run():
            async with asgi_app.quart_app.test_client() as client:
                resp = await client.get("/admin/storage/configs")
                return resp, await resp.json

        resp, payload = asyncio.run(_run())
        assert resp.status_code == 200
        assert payload["code"] == "success"
        assert len(payload["data"]["items"]) == 1

    def test_update_config(self, monkeypatch):
        self._setup(monkeypatch)

        async def _run():
            async with asgi_app.quart_app.test_client() as client:
                resp = await client.post(
                    "/admin/storage/configs/cos", json={"configs": {"secret_id": "x"}}
                )
                return resp, await resp.json

        resp, payload = asyncio.run(_run())
        assert resp.status_code == 200
        assert payload["code"] == "success"
        assert payload["data"]["backend"] == "cos"

    def test_activate(self, monkeypatch):
        self._setup(monkeypatch)

        async def _run():
            async with asgi_app.quart_app.test_client() as client:
                resp = await client.post("/admin/storage/activate", json={"backend": "cos"})
                return resp, await resp.json

        resp, payload = asyncio.run(_run())
        assert resp.status_code == 200
        assert payload["code"] == "success"
        assert payload["data"]["backend"] == "cos"

    def test_activate_invalid_backend(self, monkeypatch):
        self._setup(monkeypatch)

        async def _run():
            async with asgi_app.quart_app.test_client() as client:
                resp = await client.post("/admin/storage/activate", json={"backend": "s3"})
                return resp, await resp.json

        resp, payload = asyncio.run(_run())
        assert resp.status_code == 400
        assert payload["code"] == "validate_error"

    def test_migration_list(self, monkeypatch):
        self._setup(monkeypatch)

        async def _run():
            async with asgi_app.quart_app.test_client() as client:
                resp = await client.get("/admin/storage/migration/files")
                return resp, await resp.json

        resp, payload = asyncio.run(_run())
        assert resp.status_code == 200
        assert payload["code"] == "success"
        assert payload["data"]["total"] == 1
        assert len(payload["data"]["items"]) == 1
        assert payload["data"]["extensions"] == ["pdf", "png"]

    def test_migration_run(self, monkeypatch):
        self._setup(monkeypatch)

        async def _run():
            async with asgi_app.quart_app.test_client() as client:
                resp = await client.post(
                    "/admin/storage/migration/run",
                    json={"source_backend": "local", "target_backend": "cos"},
                )
                return resp, await resp.json

        resp, payload = asyncio.run(_run())
        assert resp.status_code == 200
        assert payload["code"] == "success"
        assert payload["data"]["succeeded"] == 1


class TestAdminAgentPoolRoutes:
    def _setup(self, monkeypatch):
        from internal.service.admin_agent_pool_service import AdminAgentPoolService

        service = SimpleNamespace(
            list_configs=lambda **kw: {
                "list": [_agent_pool()],
                "paginator": _paginator(kw.get("page", 1), kw.get("per_page", 20)),
            },
            create_config=lambda payload: _agent_pool(),
            get_config=lambda config_id: _agent_pool(),
            update_config=lambda config_id, payload: _agent_pool(),
            delete_config=lambda config_id: None,
            set_enabled=lambda config_id, enabled: _agent_pool(),
            check_health=lambda config_id: _agent_pool(),
            list_pool_stats=lambda: {"list": [{"total": 3, "enabled": 2, "healthy": 1}]},
        )
        monkeypatch.setattr(
            support, "_get_service", lambda cls: service if cls is AdminAgentPoolService else None
        )
        return service

    def test_list(self, monkeypatch):
        self._setup(monkeypatch)

        async def _run():
            async with asgi_app.quart_app.test_client() as client:
                resp = await client.get("/admin/agent-pool?current_page=1&page_size=5")
                return resp, await resp.json

        resp, payload = asyncio.run(_run())
        assert resp.status_code == 200
        assert payload["code"] == "success"
        assert len(payload["data"]["list"]) == 1
        assert payload["data"]["paginator"]["page_size"] == 5

    def test_create(self, monkeypatch):
        self._setup(monkeypatch)

        async def _run():
            async with asgi_app.quart_app.test_client() as client:
                resp = await client.post(
                    "/admin/agent-pool", json={"app_id": str(uuid4())}
                )
                return resp, await resp.json

        resp, payload = asyncio.run(_run())
        assert resp.status_code == 200
        assert payload["code"] == "success"

    def test_list_stats(self, monkeypatch):
        self._setup(monkeypatch)

        async def _run():
            async with asgi_app.quart_app.test_client() as client:
                resp = await client.get("/admin/agent-pool/stats")
                return resp, await resp.json

        resp, payload = asyncio.run(_run())
        assert resp.status_code == 200
        assert payload["code"] == "success"
        assert payload["data"]["list"][0]["total"] == 3

    def test_get(self, monkeypatch):
        self._setup(monkeypatch)

        async def _run():
            async with asgi_app.quart_app.test_client() as client:
                resp = await client.get(f"/admin/agent-pool/{uuid4()}")
                return resp, await resp.json

        resp, payload = asyncio.run(_run())
        assert resp.status_code == 200
        assert payload["code"] == "success"

    def test_update(self, monkeypatch):
        self._setup(monkeypatch)

        async def _run():
            async with asgi_app.quart_app.test_client() as client:
                resp = await client.patch(
                    f"/admin/agent-pool/{uuid4()}", json={"enabled": "false"}
                )
                return resp, await resp.json

        resp, payload = asyncio.run(_run())
        assert resp.status_code == 200
        assert payload["code"] == "success"

    def test_delete(self, monkeypatch):
        self._setup(monkeypatch)

        async def _run():
            async with asgi_app.quart_app.test_client() as client:
                resp = await client.delete(f"/admin/agent-pool/{uuid4()}")
                return resp, await resp.json

        resp, payload = asyncio.run(_run())
        assert resp.status_code == 200
        assert payload["message"] == "删除Agent池配置成功"

    def test_set_status(self, monkeypatch):
        self._setup(monkeypatch)

        async def _run():
            async with asgi_app.quart_app.test_client() as client:
                resp = await client.post(
                    f"/admin/agent-pool/{uuid4()}/status", json={"enabled": "true"}
                )
                return resp, await resp.json

        resp, payload = asyncio.run(_run())
        assert resp.status_code == 200
        assert payload["code"] == "success"

    def test_set_status_requires_enabled(self, monkeypatch):
        self._setup(monkeypatch)

        async def _run():
            async with asgi_app.quart_app.test_client() as client:
                resp = await client.post(f"/admin/agent-pool/{uuid4()}/status", json={})
                return resp, await resp.json

        resp, payload = asyncio.run(_run())
        assert resp.status_code == 400
        assert payload["code"] == "validate_error"

    def test_check_health(self, monkeypatch):
        self._setup(monkeypatch)

        async def _run():
            async with asgi_app.quart_app.test_client() as client:
                resp = await client.post(f"/admin/agent-pool/{uuid4()}/health")
                return resp, await resp.json

        resp, payload = asyncio.run(_run())
        assert resp.status_code == 200
        assert payload["code"] == "success"


class TestAdminSubPoolRoutes:
    def _setup(self, monkeypatch):
        from internal.service.admin_sub_pool_service import AdminSubPoolService

        service = SimpleNamespace(
            list_definitions=lambda **kw: {
                "list": [_sub_pool()],
                "paginator": _paginator(kw.get("page", 1), kw.get("per_page", 20)),
            },
            create_definition=lambda payload: _sub_pool(),
            get_definition=lambda def_id: {"id": str(def_id)},
            update_definition=lambda def_id, payload: {"id": str(def_id)},
            delete_definition=lambda def_id: None,
            set_enabled=lambda def_id, enabled: {"id": str(def_id)},
        )
        monkeypatch.setattr(
            support, "_get_service", lambda cls: service if cls is AdminSubPoolService else None
        )
        return service

    def test_list(self, monkeypatch):
        self._setup(monkeypatch)

        async def _run():
            async with asgi_app.quart_app.test_client() as client:
                resp = await client.get("/admin/sub-pool-definitions")
                return resp, await resp.json

        resp, payload = asyncio.run(_run())
        assert resp.status_code == 200
        assert payload["code"] == "success"
        assert len(payload["data"]["list"]) == 1

    def test_create(self, monkeypatch):
        self._setup(monkeypatch)

        async def _run():
            async with asgi_app.quart_app.test_client() as client:
                resp = await client.post(
                    "/admin/sub-pool-definitions", json={"name": "子池A"}
                )
                return resp, await resp.json

        resp, payload = asyncio.run(_run())
        assert resp.status_code == 200
        assert payload["code"] == "success"

    def test_get(self, monkeypatch):
        self._setup(monkeypatch)

        async def _run():
            async with asgi_app.quart_app.test_client() as client:
                resp = await client.get(f"/admin/sub-pool-definitions/{uuid4()}")
                return resp, await resp.json

        resp, payload = asyncio.run(_run())
        assert resp.status_code == 200
        assert payload["code"] == "success"

    def test_update(self, monkeypatch):
        self._setup(monkeypatch)

        async def _run():
            async with asgi_app.quart_app.test_client() as client:
                resp = await client.patch(
                    f"/admin/sub-pool-definitions/{uuid4()}", json={"name": "新子池"}
                )
                return resp, await resp.json

        resp, payload = asyncio.run(_run())
        assert resp.status_code == 200
        assert payload["code"] == "success"

    def test_delete(self, monkeypatch):
        self._setup(monkeypatch)

        async def _run():
            async with asgi_app.quart_app.test_client() as client:
                resp = await client.delete(f"/admin/sub-pool-definitions/{uuid4()}")
                return resp, await resp.json

        resp, payload = asyncio.run(_run())
        assert resp.status_code == 200
        assert payload["message"] == "删除子池定义成功"

    def test_set_status(self, monkeypatch):
        self._setup(monkeypatch)

        async def _run():
            async with asgi_app.quart_app.test_client() as client:
                resp = await client.post(
                    f"/admin/sub-pool-definitions/{uuid4()}/status",
                    json={"enabled": "false"},
                )
                return resp, await resp.json

        resp, payload = asyncio.run(_run())
        assert resp.status_code == 200
        assert payload["code"] == "success"
