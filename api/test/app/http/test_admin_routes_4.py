"""admin_routes_4（管理员技能包 + 管理员 MCP）Quart 端点单元测试。

每个端点至少一个用例：路由注册后通过 asgi_app.quart_app.test_client() 请求，
monkeypatch asgi_app._load_account / _get_service 注入 fake account 与 fake service。
"""

import asyncio
import io
from types import SimpleNamespace
from uuid import uuid4

from werkzeug.datastructures import FileStorage

import app.http.asgi_app as asgi_app
from app.http import support
from app.http.admin_routes_4 import register_routes

register_routes(asgi_app.quart_app)


def _skill_package_payload(skill_id=None):
    return {
        "id": str(skill_id or uuid4()),
        "source_key": "demo-skill",
        "source_path": "",
        "name": "技能包A",
        "label": "技能包A",
        "icon": "",
        "description": "desc",
        "readme": "",
        "category": "通用",
        "tags": [],
        "capabilities": {},
        "executor_type": "prompt",
        "tool_count": 0,
        "tools": [],
        "task_keywords": [],
        "enabled": True,
        "current_version": 1,
        "sync_status": "skipped",
        "sync_error": "",
        "skill_code": "",
        "created_at": 1710000000,
        "updated_at": 1710000000,
    }


class _FakeAdminSkillService:
    def __init__(self):
        self.calls = []

    def get_skill_package(self, skill_id):
        self.calls.append(("get_skill_package", skill_id))
        return _skill_package_payload(skill_id)

    def get_skill_package_versions(self, skill_id):
        self.calls.append(("versions", skill_id))
        return [
            {
                "id": str(uuid4()),
                "skill_package_id": str(skill_id),
                "version": 1,
                "checksum": "c1",
                "sync_status": "skipped",
                "sync_error": "",
                "is_current_version": True,
                "summary": "v1",
                "tool_count": 0,
                "created_at": 1710000000,
                "updated_at": 1710000000,
            }
        ]

    def enable_skill_package(self, skill_id):
        self.calls.append(("enable", skill_id))

    def disable_skill_package(self, skill_id):
        self.calls.append(("disable", skill_id))

    def sync_skill_package(self, skill_id):
        self.calls.append(("sync", skill_id))

    def rollback_skill_package(self, skill_id, version):
        self.calls.append(("rollback", skill_id, version))

    def create_skill_package_for_admin(self, payload):
        self.calls.append(("create", payload))
        return _skill_package_payload()

    def update_skill_package_for_admin(self, skill_id, payload):
        self.calls.append(("update", skill_id, payload))
        return _skill_package_payload(skill_id)

    def delete_skill_package_for_admin(self, skill_id, retention_days=None, deleted_by=None):
        self.calls.append(("delete", skill_id, retention_days, deleted_by))

    def list_catalog_packages_for_admin(self):
        self.calls.append(("catalog",))
        return [
            {
                "source_key": "catalog-a",
                "name": "目录包",
                "label": "",
                "description": "",
                "category": "通用",
                "executor_type": "prompt",
                "version": 1,
                "tool_count": 0,
                "imported": False,
            }
        ]

    def import_catalog_package_for_admin(self, source_key):
        self.calls.append(("import_catalog", source_key))
        payload = _skill_package_payload()
        payload["source_key"] = source_key
        return payload


class _FakeAdminSkillImportService:
    def __init__(self):
        self.calls = []

    def import_from_zip(self, file_bytes, overwrite=False):
        self.calls.append(("zip", file_bytes, overwrite))
        return {"imported": [{"source_key": "zip-skill"}], "failed": []}

    def import_from_github_url(self, github_url, overwrite=False):
        self.calls.append(("github", github_url, overwrite))
        return {"imported": [{"source_key": "gh-skill"}], "failed": []}

    def import_from_json(self, config_json, overwrite=False):
        self.calls.append(("json", config_json, overwrite))
        return {"imported": [{"source_key": "json-skill"}], "failed": []}


class _FakeAdminMcpService:
    def __init__(self):
        self.calls = []

    def get_mcp_categories(self):
        self.calls.append(("categories",))
        return [{"id": "general", "name": "通用", "priority": 1, "background": ""}]

    def create_mcp_provider(self, req):
        self.calls.append(("create", req.name.data))
        return SimpleNamespace(id=uuid4())

    def get_mcp_provider_for_admin(self, provider_id):
        self.calls.append(("get", provider_id))
        return {
            "id": str(provider_id),
            "provider_key": "",
            "name": "MCP-A",
            "label": "",
            "icon": "",
            "background": "",
            "description": "desc",
            "category": "general",
            "transport": "http",
            "url": "",
            "command": "",
            "headers": [],
            "tool_names": [],
            "args": [],
            "env": {},
            "timeout_seconds": 30,
            "task_keywords": [],
            "source_type": "custom",
            "source_key": "",
            "source_url": "",
            "creator_name": "",
            "creator_avatar": "",
            "is_public": False,
            "is_bindable": False,
            "bind_reason": "",
            "published_at": 0,
            "created_at": 1710000000,
            "updated_at": 1710000000,
            "tool_count": 0,
            "tools": [],
            "binding": {},
        }

    def update_mcp_provider_for_admin(self, provider_id, req):
        self.calls.append(("update", provider_id, req.name.data))

    def regenerate_icon_for_admin(self, provider_id):
        self.calls.append(("regenerate_icon", provider_id))
        return "http://icon.example/mcp.png"

    def publish_mcp_provider_for_admin(self, provider_id):
        self.calls.append(("publish", provider_id))

    def unpublish_mcp_provider_for_admin(self, provider_id):
        self.calls.append(("unpublish", provider_id))

    def delete_mcp_provider_for_admin(self, provider_id, retention_days=None, deleted_by=None):
        self.calls.append(("delete", provider_id, retention_days, deleted_by))


class _FakeAdminMcpImportService:
    def __init__(self):
        self.calls = []

    def import_from_mcp_json(self, config_json, overwrite=False):
        self.calls.append(("mcp_json", config_json, overwrite))
        return {"imported": [{"name": "server-a"}], "skipped": [], "failed": []}

    def preview_tools_from_url(self, url, headers=None, transport="http"):
        self.calls.append(("preview", url, headers, transport))
        return {"tools": [{"name": "tool-a", "label": "", "description": ""}], "server_info": {}}

    def import_from_url(self, url, name, description, headers, transport="http", category="other", icon=""):
        self.calls.append(("import_url", url, name, headers, transport, category))
        return SimpleNamespace(id=uuid4())

    def import_from_json(self, config_json, overwrite=False):
        self.calls.append(("import_json", config_json, overwrite))
        return {"imported": [{"name": "server-a"}], "skipped": [], "failed": []}


def _setup(monkeypatch):
    from internal.service.mcp_import_service import McpImportService
    from internal.service.mcp_service import McpService
    from internal.service.skill_import_service import SkillImportService
    from internal.service.skill_service import SkillService

    account = SimpleNamespace(id=uuid4())
    skill_service = _FakeAdminSkillService()
    skill_import_service = _FakeAdminSkillImportService()
    mcp_service = _FakeAdminMcpService()
    mcp_import_service = _FakeAdminMcpImportService()
    monkeypatch.setattr(support, "_load_account", lambda _aid: account)
    services = {
        SkillService: skill_service,
        SkillImportService: skill_import_service,
        McpService: mcp_service,
        McpImportService: mcp_import_service,
    }
    monkeypatch.setattr(support, "_get_service", lambda cls: services.get(cls))
    return account, skill_service, skill_import_service, mcp_service, mcp_import_service


class TestAdminSkillsRoutes:
    def test_get_skill_package(self, monkeypatch):
        _, skill_service, _, _, _ = _setup(monkeypatch)
        skill_id = uuid4()

        async def _run():
            async with asgi_app.quart_app.test_client() as client:
                resp = await client.get(f"/admin/skills/{skill_id}?account_id={uuid4()}")
                return resp, await resp.json

        resp, payload = asyncio.run(_run())
        assert resp.status_code == 200
        assert payload["code"] == "success"
        assert payload["data"]["source_key"] == "demo-skill"
        assert skill_service.calls[0] == ("get_skill_package", skill_id)

    def test_get_skill_package_versions(self, monkeypatch):
        _, skill_service, _, _, _ = _setup(monkeypatch)
        skill_id = uuid4()

        async def _run():
            async with asgi_app.quart_app.test_client() as client:
                resp = await client.get(f"/admin/skills/{skill_id}/versions?account_id={uuid4()}")
                return resp, await resp.json

        resp, payload = asyncio.run(_run())
        assert resp.status_code == 200
        assert payload["data"]["list"][0]["is_current_version"] is True
        assert skill_service.calls[0] == ("versions", skill_id)

    def test_enable_skill_package(self, monkeypatch):
        _, skill_service, _, _, _ = _setup(monkeypatch)
        skill_id = uuid4()

        async def _run():
            async with asgi_app.quart_app.test_client() as client:
                resp = await client.post(f"/admin/skills/{skill_id}/enable?account_id={uuid4()}")
                return resp, await resp.json

        resp, payload = asyncio.run(_run())
        assert resp.status_code == 200
        assert payload["message"] == "启用技能包成功"
        assert skill_service.calls[0] == ("enable", skill_id)

    def test_disable_skill_package(self, monkeypatch):
        _, skill_service, _, _, _ = _setup(monkeypatch)
        skill_id = uuid4()

        async def _run():
            async with asgi_app.quart_app.test_client() as client:
                resp = await client.post(f"/admin/skills/{skill_id}/disable?account_id={uuid4()}")
                return resp, await resp.json

        resp, payload = asyncio.run(_run())
        assert resp.status_code == 200
        assert payload["message"] == "停用技能包成功"
        assert skill_service.calls[0] == ("disable", skill_id)

    def test_sync_skill_package(self, monkeypatch):
        _, skill_service, _, _, _ = _setup(monkeypatch)
        skill_id = uuid4()

        async def _run():
            async with asgi_app.quart_app.test_client() as client:
                resp = await client.post(f"/admin/skills/{skill_id}/sync?account_id={uuid4()}")
                return resp, await resp.json

        resp, payload = asyncio.run(_run())
        assert resp.status_code == 200
        assert payload["message"] == "同步技能包成功"
        assert skill_service.calls[0] == ("sync", skill_id)

    def test_rollback_skill_package(self, monkeypatch):
        _, skill_service, _, _, _ = _setup(monkeypatch)
        skill_id = uuid4()

        async def _run():
            async with asgi_app.quart_app.test_client() as client:
                resp = await client.post(
                    f"/admin/skills/{skill_id}/rollback?account_id={uuid4()}",
                    json={"version": 2},
                )
                return resp, await resp.json

        resp, payload = asyncio.run(_run())
        assert resp.status_code == 200
        assert payload["message"] == "回滚技能包成功"
        assert skill_service.calls[0] == ("rollback", skill_id, 2)

    def test_rollback_skill_package_requires_version(self, monkeypatch):
        _setup(monkeypatch)

        async def _run():
            async with asgi_app.quart_app.test_client() as client:
                resp = await client.post(
                    f"/admin/skills/{uuid4()}/rollback?account_id={uuid4()}", json={}
                )
                return resp, await resp.json

        resp, payload = asyncio.run(_run())
        assert resp.status_code == 400
        assert payload["code"] == "validate_error"
        assert payload["message"] == "技能版本不能为空"

    def test_create_skill_package(self, monkeypatch):
        _, skill_service, _, _, _ = _setup(monkeypatch)

        async def _run():
            async with asgi_app.quart_app.test_client() as client:
                resp = await client.post(
                    f"/admin/skills?account_id={uuid4()}",
                    json={"source_key": "my-skill", "name": "我的技能"},
                )
                return resp, await resp.json

        resp, payload = asyncio.run(_run())
        assert resp.status_code == 200
        assert payload["data"]["source_key"] == "demo-skill"
        assert skill_service.calls[0][0] == "create"
        assert skill_service.calls[0][1]["source_key"] == "my-skill"

    def test_create_skill_package_requires_source_key(self, monkeypatch):
        _setup(monkeypatch)

        async def _run():
            async with asgi_app.quart_app.test_client() as client:
                resp = await client.post(f"/admin/skills?account_id={uuid4()}", json={})
                return resp, await resp.json

        resp, payload = asyncio.run(_run())
        assert resp.status_code == 400
        assert payload["code"] == "validate_error"
        assert payload["message"] == "source_key 不能为空"

    def test_update_skill_package(self, monkeypatch):
        _, skill_service, _, _, _ = _setup(monkeypatch)
        skill_id = uuid4()

        async def _run():
            async with asgi_app.quart_app.test_client() as client:
                resp = await client.post(
                    f"/admin/skills/{skill_id}?account_id={uuid4()}",
                    json={"name": "新名字"},
                )
                return resp, await resp.json

        resp, payload = asyncio.run(_run())
        assert resp.status_code == 200
        assert payload["data"]["id"] == str(skill_id)
        assert skill_service.calls[0][0] == "update"
        assert skill_service.calls[0][1] == skill_id

    def test_delete_skill_package(self, monkeypatch):
        _, skill_service, _, _, _ = _setup(monkeypatch)
        skill_id = uuid4()

        async def _run():
            async with asgi_app.quart_app.test_client() as client:
                resp = await client.post(
                    f"/admin/skills/{skill_id}/delete?account_id={uuid4()}",
                    json={"retention_days": 7},
                )
                return resp, await resp.json

        resp, payload = asyncio.run(_run())
        assert resp.status_code == 200
        assert payload["message"] == "删除技能包成功"
        assert skill_service.calls[0][0] == "delete"
        assert skill_service.calls[0][2] == 7

    def test_list_catalog_packages(self, monkeypatch):
        _, skill_service, _, _, _ = _setup(monkeypatch)

        async def _run():
            async with asgi_app.quart_app.test_client() as client:
                resp = await client.get(f"/admin/skills/catalog-packages?account_id={uuid4()}")
                return resp, await resp.json

        resp, payload = asyncio.run(_run())
        assert resp.status_code == 200
        assert payload["data"]["list"][0]["source_key"] == "catalog-a"
        assert skill_service.calls[0] == ("catalog",)

    def test_import_catalog_package(self, monkeypatch):
        _, skill_service, _, _, _ = _setup(monkeypatch)

        async def _run():
            async with asgi_app.quart_app.test_client() as client:
                resp = await client.post(
                    f"/admin/skills/import-catalog?account_id={uuid4()}",
                    json={"source_key": "catalog-a"},
                )
                return resp, await resp.json

        resp, payload = asyncio.run(_run())
        assert resp.status_code == 200
        assert payload["data"]["source_key"] == "catalog-a"
        assert skill_service.calls[0] == ("import_catalog", "catalog-a")

    def test_import_skill_zip(self, monkeypatch):
        _, _, skill_import_service, _, _ = _setup(monkeypatch)

        async def _run():
            async with asgi_app.quart_app.test_client() as client:
                resp = await client.post(
                    f"/admin/skills/import-zip?account_id={uuid4()}",
                    form={"overwrite": "true"},
                    files={
                        "file": FileStorage(
                            stream=io.BytesIO(b"zip-bytes"), filename="skill.zip"
                        )
                    },
                )
                return resp, await resp.json

        resp, payload = asyncio.run(_run())
        assert resp.status_code == 200
        assert payload["data"]["imported"][0]["source_key"] == "zip-skill"
        assert skill_import_service.calls[0][0] == "zip"
        assert skill_import_service.calls[0][1] == b"zip-bytes"
        assert skill_import_service.calls[0][2] is True

    def test_import_skill_zip_requires_file(self, monkeypatch):
        _setup(monkeypatch)

        async def _run():
            async with asgi_app.quart_app.test_client() as client:
                resp = await client.post(f"/admin/skills/import-zip?account_id={uuid4()}")
                return resp, await resp.json

        resp, payload = asyncio.run(_run())
        assert resp.status_code == 400
        assert payload["code"] == "validate_error"
        assert payload["message"] == "请选择要上传的 zip 文件"

    def test_import_skill_github(self, monkeypatch):
        _, _, skill_import_service, _, _ = _setup(monkeypatch)

        async def _run():
            async with asgi_app.quart_app.test_client() as client:
                resp = await client.post(
                    f"/admin/skills/import-github?account_id={uuid4()}",
                    json={"github_url": "https://github.com/owner/repo", "overwrite": True},
                )
                return resp, await resp.json

        resp, payload = asyncio.run(_run())
        assert resp.status_code == 200
        assert payload["data"]["imported"][0]["source_key"] == "gh-skill"
        assert skill_import_service.calls[0][0] == "github"
        assert skill_import_service.calls[0][2] is True

    def test_import_skill_github_requires_url(self, monkeypatch):
        _setup(monkeypatch)

        async def _run():
            async with asgi_app.quart_app.test_client() as client:
                resp = await client.post(f"/admin/skills/import-github?account_id={uuid4()}", json={})
                return resp, await resp.json

        resp, payload = asyncio.run(_run())
        assert resp.status_code == 400
        assert payload["code"] == "validate_error"
        assert payload["message"] == "github_url 不能为空"

    def test_import_skill_json(self, monkeypatch):
        _, _, skill_import_service, _, _ = _setup(monkeypatch)

        async def _run():
            async with asgi_app.quart_app.test_client() as client:
                resp = await client.post(
                    f"/admin/skills/import-json?account_id={uuid4()}",
                    json={"config_json": '{"source_key": "s"}'},
                )
                return resp, await resp.json

        resp, payload = asyncio.run(_run())
        assert resp.status_code == 200
        assert payload["data"]["imported"][0]["source_key"] == "json-skill"
        assert skill_import_service.calls[0][0] == "json"

    def test_import_skill_json_requires_config(self, monkeypatch):
        _setup(monkeypatch)

        async def _run():
            async with asgi_app.quart_app.test_client() as client:
                resp = await client.post(f"/admin/skills/import-json?account_id={uuid4()}", json={})
                return resp, await resp.json

        resp, payload = asyncio.run(_run())
        assert resp.status_code == 400
        assert payload["code"] == "validate_error"
        assert payload["message"] == "config_json 不能为空"


class TestAdminMcpRoutes:
    def test_get_mcp_categories(self, monkeypatch):
        _, _, _, mcp_service, _ = _setup(monkeypatch)

        async def _run():
            async with asgi_app.quart_app.test_client() as client:
                resp = await client.get(f"/admin/mcp/categories?account_id={uuid4()}")
                return resp, await resp.json

        resp, payload = asyncio.run(_run())
        assert resp.status_code == 200
        assert payload["data"]["categories"][0]["id"] == "general"
        assert mcp_service.calls[0] == ("categories",)

    def test_import_mcp_json(self, monkeypatch):
        _, _, _, _, mcp_import_service = _setup(monkeypatch)

        async def _run():
            async with asgi_app.quart_app.test_client() as client:
                resp = await client.post(
                    f"/admin/mcp/import-mcp-json?account_id={uuid4()}",
                    json={"config_json": '{"mcpServers":{}}', "overwrite": True},
                )
                return resp, await resp.json

        resp, payload = asyncio.run(_run())
        assert resp.status_code == 200
        assert payload["data"]["imported"][0]["name"] == "server-a"
        assert mcp_import_service.calls[0][0] == "mcp_json"
        assert mcp_import_service.calls[0][2] is True

    def test_import_mcp_json_requires_config(self, monkeypatch):
        _setup(monkeypatch)

        async def _run():
            async with asgi_app.quart_app.test_client() as client:
                resp = await client.post(f"/admin/mcp/import-mcp-json?account_id={uuid4()}", json={})
                return resp, await resp.json

        resp, payload = asyncio.run(_run())
        assert resp.status_code == 400
        assert payload["code"] == "validate_error"
        assert payload["message"] == "config_json 不能为空"

    def test_preview_mcp_url(self, monkeypatch):
        _, _, _, _, mcp_import_service = _setup(monkeypatch)

        async def _run():
            async with asgi_app.quart_app.test_client() as client:
                resp = await client.post(
                    f"/admin/mcp/preview-url?account_id={uuid4()}",
                    json={"url": "https://example.com/mcp", "transport": "http"},
                )
                return resp, await resp.json

        resp, payload = asyncio.run(_run())
        assert resp.status_code == 200
        assert payload["data"]["tools"][0]["name"] == "tool-a"
        assert mcp_import_service.calls[0][0] == "preview"
        assert mcp_import_service.calls[0][2] == []
        assert mcp_import_service.calls[0][3] == "http"

    def test_import_mcp_url(self, monkeypatch):
        _, _, _, _, mcp_import_service = _setup(monkeypatch)

        async def _run():
            async with asgi_app.quart_app.test_client() as client:
                resp = await client.post(
                    f"/admin/mcp/import-url?account_id={uuid4()}",
                    json={"url": "https://example.com/mcp", "name": "远程MCP"},
                )
                return resp, await resp.json

        resp, payload = asyncio.run(_run())
        assert resp.status_code == 200
        assert "id" in payload["data"]
        assert mcp_import_service.calls[0][0] == "import_url"
        assert mcp_import_service.calls[0][1] == "https://example.com/mcp"
        assert mcp_import_service.calls[0][2] == "远程MCP"

    def test_import_mcp_url_requires_name(self, monkeypatch):
        _setup(monkeypatch)

        async def _run():
            async with asgi_app.quart_app.test_client() as client:
                resp = await client.post(
                    f"/admin/mcp/import-url?account_id={uuid4()}",
                    json={"url": "https://example.com/mcp"},
                )
                return resp, await resp.json

        resp, payload = asyncio.run(_run())
        assert resp.status_code == 400
        assert payload["code"] == "validate_error"
        assert payload["message"] == "MCP 名称不能为空"

    def test_import_mcp_json_config(self, monkeypatch):
        _, _, _, _, mcp_import_service = _setup(monkeypatch)

        async def _run():
            async with asgi_app.quart_app.test_client() as client:
                resp = await client.post(
                    f"/admin/mcp/import-json?account_id={uuid4()}",
                    json={"config_json": '{"name": "srv"}'},
                )
                return resp, await resp.json

        resp, payload = asyncio.run(_run())
        assert resp.status_code == 200
        assert payload["data"]["imported"][0]["name"] == "server-a"
        assert mcp_import_service.calls[0][0] == "import_json"

    def test_create_mcp_provider(self, monkeypatch):
        _, _, _, mcp_service, _ = _setup(monkeypatch)

        async def _run():
            async with asgi_app.quart_app.test_client() as client:
                resp = await client.post(
                    f"/admin/mcp?account_id={uuid4()}",
                    json={"name": "MCP-A", "description": "desc"},
                )
                return resp, await resp.json

        resp, payload = asyncio.run(_run())
        assert resp.status_code == 200
        assert "id" in payload["data"]
        assert mcp_service.calls[0] == ("create", "MCP-A")

    def test_create_mcp_provider_requires_name(self, monkeypatch):
        _setup(monkeypatch)

        async def _run():
            async with asgi_app.quart_app.test_client() as client:
                resp = await client.post(f"/admin/mcp?account_id={uuid4()}", json={})
                return resp, await resp.json

        resp, payload = asyncio.run(_run())
        assert resp.status_code == 400
        assert payload["code"] == "validate_error"
        assert payload["message"] == "MCP 名称不能为空"

    def test_get_mcp_provider(self, monkeypatch):
        _, _, _, mcp_service, _ = _setup(monkeypatch)
        provider_id = uuid4()

        async def _run():
            async with asgi_app.quart_app.test_client() as client:
                resp = await client.get(f"/admin/mcp/{provider_id}?account_id={uuid4()}")
                return resp, await resp.json

        resp, payload = asyncio.run(_run())
        assert resp.status_code == 200
        assert payload["data"]["name"] == "MCP-A"
        assert mcp_service.calls[0] == ("get", provider_id)

    def test_update_mcp_provider(self, monkeypatch):
        _, _, _, mcp_service, _ = _setup(monkeypatch)
        provider_id = uuid4()

        async def _run():
            async with asgi_app.quart_app.test_client() as client:
                resp = await client.patch(
                    f"/admin/mcp/{provider_id}?account_id={uuid4()}",
                    json={"name": "MCP-New", "description": "desc"},
                )
                return resp, await resp.json

        resp, payload = asyncio.run(_run())
        assert resp.status_code == 200
        assert payload["message"] == "更新MCP成功"
        assert mcp_service.calls[0][0] == "update"
        assert mcp_service.calls[0][1] == provider_id

    def test_update_mcp_provider_requires_description(self, monkeypatch):
        _setup(monkeypatch)

        async def _run():
            async with asgi_app.quart_app.test_client() as client:
                resp = await client.patch(
                    f"/admin/mcp/{uuid4()}?account_id={uuid4()}", json={"name": "MCP-New"}
                )
                return resp, await resp.json

        resp, payload = asyncio.run(_run())
        assert resp.status_code == 400
        assert payload["code"] == "validate_error"
        assert payload["message"] == "MCP 描述不能为空"

    def test_regenerate_mcp_icon(self, monkeypatch):
        _, _, _, mcp_service, _ = _setup(monkeypatch)
        provider_id = uuid4()

        async def _run():
            async with asgi_app.quart_app.test_client() as client:
                resp = await client.post(
                    f"/admin/mcp/{provider_id}/regenerate-icon?account_id={uuid4()}"
                )
                return resp, await resp.json

        resp, payload = asyncio.run(_run())
        assert resp.status_code == 200
        assert payload["data"]["icon"] == "http://icon.example/mcp.png"
        assert mcp_service.calls[0] == ("regenerate_icon", provider_id)

    def test_publish_mcp_provider(self, monkeypatch):
        _, _, _, mcp_service, _ = _setup(monkeypatch)
        provider_id = uuid4()

        async def _run():
            async with asgi_app.quart_app.test_client() as client:
                resp = await client.post(f"/admin/mcp/{provider_id}/publish?account_id={uuid4()}")
                return resp, await resp.json

        resp, payload = asyncio.run(_run())
        assert resp.status_code == 200
        assert payload["message"] == "发布MCP成功"
        assert mcp_service.calls[0] == ("publish", provider_id)

    def test_unpublish_mcp_provider(self, monkeypatch):
        _, _, _, mcp_service, _ = _setup(monkeypatch)
        provider_id = uuid4()

        async def _run():
            async with asgi_app.quart_app.test_client() as client:
                resp = await client.post(f"/admin/mcp/{provider_id}/unpublish?account_id={uuid4()}")
                return resp, await resp.json

        resp, payload = asyncio.run(_run())
        assert resp.status_code == 200
        assert payload["message"] == "取消发布MCP成功"
        assert mcp_service.calls[0] == ("unpublish", provider_id)

    def test_delete_mcp_provider(self, monkeypatch):
        _, _, _, mcp_service, _ = _setup(monkeypatch)
        provider_id = uuid4()

        async def _run():
            async with asgi_app.quart_app.test_client() as client:
                resp = await client.delete(
                    f"/admin/mcp/{provider_id}?account_id={uuid4()}", json={"retention_days": 7}
                )
                return resp, await resp.json

        resp, payload = asyncio.run(_run())
        assert resp.status_code == 200
        assert payload["message"] == "删除MCP成功"
        assert mcp_service.calls[0][0] == "delete"
        assert mcp_service.calls[0][2] == 7
