"""AdminApp 模块 Quart 异步端点（app.http.admin_routes_1）单元测试。"""

import asyncio
from types import SimpleNamespace
from uuid import uuid4

import pytest

import app.http.asgi_app as asgi_app
from app.http import support
from app.http.admin_routes_1 import register_routes

register_routes(asgi_app.quart_app)


def _fake_app_dict(app_id=None):
    return {
        "id": str(app_id or uuid4()),
        "name": "管理端应用",
        "icon": "",
        "description": "desc",
        "status": "draft",
        "app_type": "chat",
        "is_public": False,
        "agent_metadata": {},
        "debug_conversation_id": str(uuid4()),
        "creator_name": "管理员",
        "created_at": 1710000000,
        "updated_at": 1710000000,
    }


def _setup(monkeypatch, services):
    account = SimpleNamespace(id=uuid4())
    monkeypatch.setattr(support, "_load_account", lambda _aid: account)
    monkeypatch.setattr(support, "_get_service", lambda cls: services.get(cls))
    return account


class _FakeAdminAppService:
    def __init__(self):
        self.calls = []

    def list_apps(self, *, search="", status="all", current_page=1, page_size=20):
        self.calls.append(("list", search, status, current_page, page_size))
        return {
            "list": [_fake_app_dict()],
            "paginator": {
                "total_record": 1,
                "total_page": 1,
                "current_page": current_page,
                "page_size": page_size,
            },
        }

    def get_app(self, app_id):
        self.calls.append(("get", app_id))
        return _fake_app_dict(app_id)

    def update_app(self, app_id, *, status=None, is_public=None, agent_metadata=None):
        self.calls.append(("update", app_id, status, is_public, agent_metadata))
        return _fake_app_dict(app_id)

    def offline_app(self, app_id):
        self.calls.append(("offline", app_id))

    def batch_offline_apps(self, app_ids):
        self.calls.append(("batch_offline", app_ids))
        return {"succeeded": [str(a) for a in app_ids], "failed": []}

    def batch_delete_apps(self, app_ids, *, retention_days=None, deleted_by=None):
        self.calls.append(("batch_delete", app_ids, retention_days, deleted_by))
        return {"succeeded": [str(a) for a in app_ids], "failed": []}


class _FakeAppService:
    def __init__(self):
        self.calls = []

    def create_app(self, req, account=None, *, created_by_admin=None):
        self.calls.append(("create", req.name.data, created_by_admin))
        return SimpleNamespace(id=uuid4())

    def delete_app_for_admin(self, app_id, *, retention_days=None, deleted_by=None):
        self.calls.append(("delete", app_id, retention_days, deleted_by))

    def get_draft_app_config_for_admin(self, app_id):
        self.calls.append(("draft_get", app_id))
        return {"model_config": {"model": "fake"}}

    def update_draft_app_config_for_admin(self, app_id, draft_app_config):
        self.calls.append(("draft_update", app_id, draft_app_config))

    def import_app_for_admin(self, json_data, *, overwrite_name=False, created_by_admin=None):
        self.calls.append(("import", overwrite_name, created_by_admin))
        return SimpleNamespace(id=uuid4())

    def export_app_for_admin(self, app_id):
        self.calls.append(("export", app_id))
        return {"format": "yuxin-ai-app", "name": "应用"}

    def get_published_config_for_admin(self, app_id):
        self.calls.append(("published_get", app_id))
        return {"model_config": {"model": "fake"}}

    def regenerate_web_app_token_for_admin(self, app_id):
        self.calls.append(("regenerate_token", app_id))
        return "token-abc"

    def get_versions_for_admin(self, app_id):
        self.calls.append(("versions", app_id))
        return []


class _FakePlatformService:
    def __init__(self):
        self.calls = []

    def get_wechat_config_for_admin(self, app_id):
        self.calls.append(("wechat_get", app_id))
        return SimpleNamespace(
            app_id=app_id,
            wechat_app_id="wx123",
            wechat_app_secret="secret",
            wechat_token="token",
            status="configured",
            updated_at=1710000000,
            created_at=1710000000,
        )

    def update_wechat_config_for_admin(self, app_id, req):
        self.calls.append(("wechat_update", app_id, req.wechat_app_id.data))


class _FakePublicAppService:
    def __init__(self):
        self.calls = []

    def share_app_to_square_for_admin(self, app_id, tags):
        self.calls.append(("share", app_id, tags))

    def unshare_app_from_square_for_admin(self, app_id):
        self.calls.append(("unshare", app_id))


class _FakeAnalysisService:
    def __init__(self):
        self.calls = []

    def get_app_analysis_for_admin(self, app_id):
        self.calls.append(("analysis", app_id))
        return {"message_count": 10, "conversation_count": 3}


class _FakeAppDebugService:
    def __init__(self):
        self.calls = []

    def prompt_compare_chat_for_admin(self, app_id, req):
        self.calls.append(("pc", app_id, req.query.data, req.preset_prompt.data))

        def gen():
            yield "event: message\ndata:pc-1\n\n"
            yield "event: message\ndata:pc-2\n\n"

        return gen()

    def stop_prompt_compare_chat_for_admin(self, app_id, task_id):
        self.calls.append(("pc_stop", app_id, task_id))


class TestAdminAppRoutesRegistered:
    def test_routes_registered(self):
        rules = [r.rule for r in asgi_app.quart_app.url_map.iter_rules()]
        assert "/admin/apps" in rules
        assert "/admin/apps/<uuid:app_id>" in rules
        assert "/admin/apps/<uuid:app_id>/export" in rules
        assert "/admin/apps/tags" in rules
        assert "/admin/apps/<uuid:app_id>/conversations/messages" in rules
        assert "/admin/apps/<uuid:app_id>/conversations" in rules
        assert "/admin/apps/<uuid:app_id>/summary" in rules

    def test_register_routes_idempotent(self):
        from app.http import admin_routes_1

        admin_routes_1.register_routes(asgi_app.quart_app)
        assert admin_routes_1._registered is True


class TestAdminAppCrud:
    def _setup(self, monkeypatch):
        from internal.service import AppService
        from internal.service.admin_app_service import AdminAppService

        admin_svc = _FakeAdminAppService()
        app_svc = _FakeAppService()
        account = _setup(
            monkeypatch,
            {AdminAppService: admin_svc, AppService: app_svc},
        )
        return account, admin_svc, app_svc

    def test_list(self, monkeypatch):
        _, admin_svc, _ = self._setup(monkeypatch)

        async def _run():
            async with asgi_app.quart_app.test_client() as client:
                resp = await client.get(f"/admin/apps?account_id={uuid4()}&status=draft")
                return resp, await resp.json

        resp, payload = asyncio.run(_run())
        assert resp.status_code == 200
        assert payload["code"] == "success"
        assert len(payload["data"]["list"]) == 1
        assert admin_svc.calls[0][0] == "list"
        assert admin_svc.calls[0][2] == "draft"

    def test_get(self, monkeypatch):
        _, admin_svc, _ = self._setup(monkeypatch)
        app_id = uuid4()

        async def _run():
            async with asgi_app.quart_app.test_client() as client:
                resp = await client.get(f"/admin/apps/{app_id}?account_id={uuid4()}")
                return resp, await resp.json

        resp, payload = asyncio.run(_run())
        assert resp.status_code == 200
        assert payload["data"]["name"] == "管理端应用"
        assert admin_svc.calls[0] == ("get", app_id)

    def test_create(self, monkeypatch):
        _, _, app_svc = self._setup(monkeypatch)

        async def _run():
            async with asgi_app.quart_app.test_client() as client:
                resp = await client.post(
                    f"/admin/apps?account_id={uuid4()}", json={"name": "新应用"}
                )
                return resp, await resp.json

        resp, payload = asyncio.run(_run())
        assert resp.status_code == 200
        assert "id" in payload["data"]
        assert app_svc.calls[0][0] == "create"
        assert app_svc.calls[0][1] == "新应用"

    def test_create_requires_name(self, monkeypatch):
        self._setup(monkeypatch)

        async def _run():
            async with asgi_app.quart_app.test_client() as client:
                resp = await client.post(f"/admin/apps?account_id={uuid4()}", json={})
                return resp, await resp.json

        resp, payload = asyncio.run(_run())
        assert resp.status_code == 400
        assert payload["code"] == "validate_error"

    def test_update(self, monkeypatch):
        _, admin_svc, _ = self._setup(monkeypatch)
        app_id = uuid4()

        async def _run():
            async with asgi_app.quart_app.test_client() as client:
                resp = await client.patch(
                    f"/admin/apps/{app_id}?account_id={uuid4()}",
                    json={"status": "offline", "is_public": True},
                )
                return resp, await resp.json

        resp, payload = asyncio.run(_run())
        assert resp.status_code == 200
        assert admin_svc.calls[0][0] == "update"
        assert admin_svc.calls[0][2] == "offline"
        assert admin_svc.calls[0][3] is True

    def test_delete(self, monkeypatch):
        account, _, app_svc = self._setup(monkeypatch)
        app_id = uuid4()

        async def _run():
            async with asgi_app.quart_app.test_client() as client:
                resp = await client.delete(
                    f"/admin/apps/{app_id}?account_id={uuid4()}", json={}
                )
                return resp, await resp.json

        resp, payload = asyncio.run(_run())
        assert resp.status_code == 200
        assert payload["message"] == "删除Agent智能体应用成功"
        assert app_svc.calls[0] == ("delete", app_id, None, str(account.id))

    def test_offline(self, monkeypatch):
        _, admin_svc, _ = self._setup(monkeypatch)
        app_id = uuid4()

        async def _run():
            async with asgi_app.quart_app.test_client() as client:
                resp = await client.post(f"/admin/apps/{app_id}/offline?account_id={uuid4()}")
                return resp, await resp.json

        resp, payload = asyncio.run(_run())
        assert resp.status_code == 200
        assert payload["message"] == "下架应用成功"
        assert admin_svc.calls[0] == ("offline", app_id)

    def test_batch_offline(self, monkeypatch):
        _, admin_svc, _ = self._setup(monkeypatch)
        app_ids = [str(uuid4()), str(uuid4())]

        async def _run():
            async with asgi_app.quart_app.test_client() as client:
                resp = await client.post(
                    f"/admin/apps/batch/offline?account_id={uuid4()}",
                    json={"app_ids": app_ids},
                )
                return resp, await resp.json

        resp, payload = asyncio.run(_run())
        assert resp.status_code == 200
        assert payload["data"]["succeeded"] == app_ids
        assert admin_svc.calls[0][0] == "batch_offline"

    def test_batch_offline_requires_app_ids(self, monkeypatch):
        self._setup(monkeypatch)

        async def _run():
            async with asgi_app.quart_app.test_client() as client:
                resp = await client.post(
                    f"/admin/apps/batch/offline?account_id={uuid4()}", json={}
                )
                return resp, await resp.json

        resp, payload = asyncio.run(_run())
        assert resp.status_code == 400
        assert payload["code"] == "validate_error"

    def test_batch_delete(self, monkeypatch):
        _, admin_svc, _ = self._setup(monkeypatch)
        app_ids = [str(uuid4())]

        async def _run():
            async with asgi_app.quart_app.test_client() as client:
                resp = await client.post(
                    f"/admin/apps/batch/delete?account_id={uuid4()}",
                    json={"app_ids": app_ids, "retention_days": 30},
                )
                return resp, await resp.json

        resp, payload = asyncio.run(_run())
        assert resp.status_code == 200
        assert payload["data"]["succeeded"] == app_ids
        assert admin_svc.calls[0][0] == "batch_delete"
        assert admin_svc.calls[0][2] == 30

    def test_batch_delete_requires_app_ids(self, monkeypatch):
        self._setup(monkeypatch)

        async def _run():
            async with asgi_app.quart_app.test_client() as client:
                resp = await client.post(
                    f"/admin/apps/batch/delete?account_id={uuid4()}",
                    json={"app_ids": []},
                )
                return resp, await resp.json

        resp, payload = asyncio.run(_run())
        assert resp.status_code == 400
        assert payload["code"] == "validate_error"


class TestAdminAppConfig:
    def _setup(self, monkeypatch):
        from internal.service import AppService

        app_svc = _FakeAppService()
        account = _setup(monkeypatch, {AppService: app_svc})
        return account, app_svc

    def test_get_draft_app_config(self, monkeypatch):
        _, app_svc = self._setup(monkeypatch)

        async def _run():
            async with asgi_app.quart_app.test_client() as client:
                resp = await client.get(
                    f"/admin/apps/{uuid4()}/draft-app-config?account_id={uuid4()}"
                )
                return resp, await resp.json

        resp, payload = asyncio.run(_run())
        assert resp.status_code == 200
        assert payload["data"]["model_config"]["model"] == "fake"
        assert app_svc.calls[0][0] == "draft_get"

    def test_update_draft_app_config(self, monkeypatch):
        _, app_svc = self._setup(monkeypatch)

        async def _run():
            async with asgi_app.quart_app.test_client() as client:
                resp = await client.post(
                    f"/admin/apps/{uuid4()}/draft-app-config?account_id={uuid4()}",
                    json={"model_config": {"provider": "openai"}},
                )
                return resp, await resp.json

        resp, payload = asyncio.run(_run())
        assert resp.status_code == 200
        assert payload["message"] == "更新应用草稿配置成功"
        assert app_svc.calls[0][0] == "draft_update"

    def test_get_published_config(self, monkeypatch):
        _, app_svc = self._setup(monkeypatch)

        async def _run():
            async with asgi_app.quart_app.test_client() as client:
                resp = await client.get(
                    f"/admin/apps/{uuid4()}/published-config?account_id={uuid4()}"
                )
                return resp, await resp.json

        resp, payload = asyncio.run(_run())
        assert resp.status_code == 200
        assert "model_config" in payload["data"]
        assert app_svc.calls[0][0] == "published_get"

    def test_regenerate_web_app_token(self, monkeypatch):
        _, app_svc = self._setup(monkeypatch)

        async def _run():
            async with asgi_app.quart_app.test_client() as client:
                resp = await client.post(
                    f"/admin/apps/{uuid4()}/published-config/regenerate-web-app-token?account_id={uuid4()}"
                )
                return resp, await resp.json

        resp, payload = asyncio.run(_run())
        assert resp.status_code == 200
        assert payload["data"]["token"] == "token-abc"

    def test_get_versions(self, monkeypatch):
        _, app_svc = self._setup(monkeypatch)

        async def _run():
            async with asgi_app.quart_app.test_client() as client:
                resp = await client.get(
                    f"/admin/apps/{uuid4()}/versions?account_id={uuid4()}"
                )
                return resp, await resp.json

        resp, payload = asyncio.run(_run())
        assert resp.status_code == 200
        assert payload["data"]["list"] == []
        assert app_svc.calls[0][0] == "versions"

    def test_import_app(self, monkeypatch):
        _, app_svc = self._setup(monkeypatch)

        async def _run():
            async with asgi_app.quart_app.test_client() as client:
                resp = await client.post(
                    f"/admin/apps/import?account_id={uuid4()}",
                    json={"json_data": {"name": "导入应用"}, "overwrite_name": True},
                )
                return resp, await resp.json

        resp, payload = asyncio.run(_run())
        assert resp.status_code == 200
        assert "id" in payload["data"]
        assert app_svc.calls[0][0] == "import"
        assert app_svc.calls[0][1] is True

    def test_import_app_rejects_invalid_body(self, monkeypatch):
        self._setup(monkeypatch)

        async def _run():
            async with asgi_app.quart_app.test_client() as client:
                resp = await client.post(
                    f"/admin/apps/import?account_id={uuid4()}",
                    json=[1, 2, 3],
                )
                return resp, await resp.json

        resp, payload = asyncio.run(_run())
        assert resp.status_code == 400
        assert payload["code"] == "validate_error"

    def test_export_app(self, monkeypatch):
        _, app_svc = self._setup(monkeypatch)

        async def _run():
            async with asgi_app.quart_app.test_client() as client:
                resp = await client.get(
                    f"/admin/apps/{uuid4()}/export?account_id={uuid4()}"
                )
                return resp, await resp.json

        resp, payload = asyncio.run(_run())
        assert resp.status_code == 200
        assert payload["data"]["format"] == "yuxin-ai-app"
        assert app_svc.calls[0][0] == "export"


class TestAdminAppWechatSquareAnalysis:
    def _setup(self, monkeypatch):
        from internal.service import AnalysisService, PlatformService, PublicAppService

        platform_svc = _FakePlatformService()
        public_svc = _FakePublicAppService()
        analysis_svc = _FakeAnalysisService()
        account = _setup(
            monkeypatch,
            {
                PlatformService: platform_svc,
                PublicAppService: public_svc,
                AnalysisService: analysis_svc,
            },
        )
        return account, platform_svc, public_svc, analysis_svc

    def test_get_wechat_config(self, monkeypatch):
        _, platform_svc, _, _ = self._setup(monkeypatch)

        async def _run():
            async with asgi_app.quart_app.test_client() as client:
                resp = await client.get(
                    f"/admin/apps/{uuid4()}/wechat-config?account_id={uuid4()}"
                )
                return resp, await resp.json

        resp, payload = asyncio.run(_run())
        assert resp.status_code == 200
        assert payload["data"]["wechat_app_id"] == "wx123"
        assert platform_svc.calls[0][0] == "wechat_get"

    def test_update_wechat_config(self, monkeypatch):
        _, platform_svc, _, _ = self._setup(monkeypatch)
        app_id = uuid4()

        async def _run():
            async with asgi_app.quart_app.test_client() as client:
                resp = await client.post(
                    f"/admin/apps/{app_id}/wechat-config?account_id={uuid4()}",
                    json={"wechat_app_id": "wx-new"},
                )
                return resp, await resp.json

        resp, payload = asyncio.run(_run())
        assert resp.status_code == 200
        assert payload["message"] == "更新Agent应用微信公众号配置成功"
        assert platform_svc.calls[0] == ("wechat_update", app_id, "wx-new")

    def test_share_app_to_square(self, monkeypatch):
        _, _, public_svc, _ = self._setup(monkeypatch)
        app_id = uuid4()

        async def _run():
            async with asgi_app.quart_app.test_client() as client:
                resp = await client.post(
                    f"/admin/apps/{app_id}/share-to-square?account_id={uuid4()}",
                    json={"tags": "效率"},
                )
                return resp, await resp.json

        resp, payload = asyncio.run(_run())
        assert resp.status_code == 200
        assert payload["message"] == "应用已共享到广场"
        assert public_svc.calls[0] == ("share", app_id, "效率")

    def test_unshare_app_from_square(self, monkeypatch):
        _, _, public_svc, _ = self._setup(monkeypatch)
        app_id = uuid4()

        async def _run():
            async with asgi_app.quart_app.test_client() as client:
                resp = await client.post(
                    f"/admin/apps/{app_id}/unshare-from-square?account_id={uuid4()}"
                )
                return resp, await resp.json

        resp, payload = asyncio.run(_run())
        assert resp.status_code == 200
        assert payload["message"] == "应用已从广场取消共享"
        assert public_svc.calls[0] == ("unshare", app_id)

    def test_get_app_analysis(self, monkeypatch):
        _, _, _, analysis_svc = self._setup(monkeypatch)

        async def _run():
            async with asgi_app.quart_app.test_client() as client:
                resp = await client.get(
                    f"/admin/apps/{uuid4()}/analysis?account_id={uuid4()}"
                )
                return resp, await resp.json

        resp, payload = asyncio.run(_run())
        assert resp.status_code == 200
        assert payload["data"]["message_count"] == 10
        assert analysis_svc.calls[0][0] == "analysis"


class TestAdminAppTags:
    def test_get_app_tags(self, monkeypatch):
        from internal.service.admin_app_service import AdminAppService

        admin_svc = _FakeAdminAppService()
        _setup(monkeypatch, {AdminAppService: admin_svc})

        import internal.extension.database_extension as de

        fake_db = SimpleNamespace(
            session=SimpleNamespace(
                query=lambda *a, **k: SimpleNamespace(
                    all=lambda: [(["效率", "智能"],), (None,)]
                )
            )
        )
        monkeypatch.setattr(de, "db", fake_db)

        async def _run():
            async with asgi_app.quart_app.test_client() as client:
                resp = await client.get(f"/admin/apps/tags?account_id={uuid4()}")
                return resp, await resp.json

        resp, payload = asyncio.run(_run())
        assert resp.status_code == 200
        assert len(payload["data"]["tags"]) == 2


class TestAdminAppPromptCompare:
    def _setup(self, monkeypatch):
        from internal.service.app_debug_service import AppDebugService

        debug_svc = _FakeAppDebugService()
        account = _setup(monkeypatch, {AppDebugService: debug_svc})
        return account, debug_svc

    def test_prompt_compare_chat_sse(self, monkeypatch):
        _, debug_svc = self._setup(monkeypatch)

        async def _run():
            async with asgi_app.quart_app.test_client() as client:
                resp = await client.post(
                    f"/admin/apps/{uuid4()}/prompt-compare/chat?account_id={uuid4()}",
                    json={"query": "q", "preset_prompt": "p"},
                )
                body = await resp.get_data(as_text=True)
                return resp, body

        resp, body = asyncio.run(_run())
        assert resp.status_code == 200
        assert resp.mimetype == "text/event-stream"
        assert "pc-1" in body
        assert "pc-2" in body
        assert debug_svc.calls[0][2] == "q"

    def test_prompt_compare_chat_requires_query(self, monkeypatch):
        self._setup(monkeypatch)

        async def _run():
            async with asgi_app.quart_app.test_client() as client:
                resp = await client.post(
                    f"/admin/apps/{uuid4()}/prompt-compare/chat?account_id={uuid4()}",
                    json={"preset_prompt": "p"},
                )
                return resp, await resp.json

        resp, payload = asyncio.run(_run())
        assert resp.status_code == 400
        assert payload["code"] == "validate_error"

    def test_prompt_compare_chat_requires_preset_prompt(self, monkeypatch):
        self._setup(monkeypatch)

        async def _run():
            async with asgi_app.quart_app.test_client() as client:
                resp = await client.post(
                    f"/admin/apps/{uuid4()}/prompt-compare/chat?account_id={uuid4()}",
                    json={"query": "q"},
                )
                return resp, await resp.json

        resp, payload = asyncio.run(_run())
        assert resp.status_code == 400
        assert payload["code"] == "validate_error"

    def test_stop_prompt_compare_chat(self, monkeypatch):
        _, debug_svc = self._setup(monkeypatch)
        app_id = uuid4()
        task_id = uuid4()

        async def _run():
            async with asgi_app.quart_app.test_client() as client:
                resp = await client.post(
                    f"/admin/apps/{app_id}/prompt-compare/tasks/{task_id}/stop?account_id={uuid4()}"
                )
                return resp, await resp.json

        resp, payload = asyncio.run(_run())
        assert resp.status_code == 200
        assert payload["message"] == "停止提示词对比调试会话成功"
        assert debug_svc.calls[0] == ("pc_stop", app_id, task_id)
