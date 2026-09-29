"""文件中心路由契约测试。

- 路由注册（6 个端点均在 url_map 上）；
- 端点行为（经 support._get_service / support._resolve_account 注入替身）。
"""
import asyncio
from types import SimpleNamespace
from uuid import uuid4

import app.http.asgi_app as asgi_app
from app.http import support
from app.http.file_center_routes import register_routes
from internal.exception import ValidateErrorException

register_routes(asgi_app.quart_app)


class _FakeEntry:
    def __init__(self, name="文档", is_folder=True):
        self.id = uuid4()
        self.parent_id = None
        self.name = name
        self.is_folder = is_folder
        self.upload_file_id = None
        self.source = "upload"
        self.origin = None


class _FakeFileCenterService:
    def __init__(self):
        self.calls = []

    def list_children(self, account_id, parent_id=None):
        self.calls.append(("list_children", parent_id))
        return [_FakeEntry("Docs")]

    def mkdir(self, account_id, *, parent_id=None, name=""):
        self.calls.append(("mkdir", name))
        if name == "dup":
            raise ValidateErrorException("同级已存在同名节点")
        return _FakeEntry(name)

    def move(self, account_id, entry_id, new_parent_id):
        self.calls.append(("move", str(entry_id)))
        return _FakeEntry("moved")

    def rename(self, account_id, entry_id, new_name):
        self.calls.append(("rename", new_name))
        return _FakeEntry(new_name)

    def delete_node(self, account_id, entry_id):
        self.calls.append(("delete_node", str(entry_id)))

    def import_upload_file(self, account_id, *, upload_file_id, parent_id=None, name="", **kw):
        self.calls.append(("import_upload_file", name))
        return _FakeEntry(name, is_folder=False)

    def list_all_files(self, *, account_id, page=1, page_size=20):
        return {
            "items": [],
            "total": 0,
            "page": page,
            "page_size": page_size,
            "total_pages": 0,
            "total_record": 0,
        }


def _setup(monkeypatch):
    from internal.service.file_center_service import FileCenterService

    service = _FakeFileCenterService()
    account = SimpleNamespace(id=uuid4())

    async def _fake_resolve_account(account_id_override=None):
        return account, None

    monkeypatch.setattr(support, "_resolve_account", _fake_resolve_account)
    monkeypatch.setattr(
        support, "_get_service", lambda cls: service if cls is FileCenterService else None
    )
    return service


def test_file_center_routes_are_registered():
    rules = {rule.rule for rule in asgi_app.quart_app.url_map.iter_rules()}
    assert "/space/files" in rules
    assert "/space/files/all" in rules
    assert "/space/files/folders" in rules
    assert "/space/files/import" in rules
    assert "/space/files/<string:entry_id>" in rules


class TestFileCenterRoutes:
    def test_list(self, monkeypatch):
        _setup(monkeypatch)

        async def _run():
            async with asgi_app.quart_app.test_client() as client:
                resp = await client.get("/space/files")
                return resp, await resp.json

        resp, payload = asyncio.run(_run())
        assert resp.status_code == 200
        assert payload["data"]["items"][0]["name"] == "Docs"

    def test_mkdir(self, monkeypatch):
        _setup(monkeypatch)

        async def _run():
            async with asgi_app.quart_app.test_client() as client:
                resp = await client.post("/space/files/folders", json={"name": "文档"})
                return resp, await resp.json

        resp, payload = asyncio.run(_run())
        assert resp.status_code == 200
        assert payload["data"]["name"] == "文档"

    def test_mkdir_conflict_returns_validate_error(self, monkeypatch):
        _setup(monkeypatch)

        async def _run():
            async with asgi_app.quart_app.test_client() as client:
                resp = await client.post("/space/files/folders", json={"name": "dup"})
                return resp, await resp.json

        resp, payload = asyncio.run(_run())
        assert resp.status_code == 400
        assert payload["code"] == "validate_error"

    def test_delete_ok(self, monkeypatch):
        _setup(monkeypatch)

        async def _run():
            async with asgi_app.quart_app.test_client() as client:
                resp = await client.delete(f"/space/files/{uuid4()}")
                return resp, await resp.json

        resp, _payload = asyncio.run(_run())
        assert resp.status_code == 200

    def test_import_requires_upload_file_id(self, monkeypatch):
        _setup(monkeypatch)

        async def _run():
            async with asgi_app.quart_app.test_client() as client:
                resp = await client.post("/space/files/import", json={})
                return resp, await resp.json

        resp, payload = asyncio.run(_run())
        assert resp.status_code == 400
        assert payload["code"] == "validate_error"
