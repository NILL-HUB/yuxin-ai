"""分片上传路由测试：init / chunk / status / complete / abort 的校验与编排调用。"""

import asyncio
from types import SimpleNamespace
from uuid import uuid4

import app.http.asgi_app as asgi_app
from app.http import chunked_upload_routes, support
from internal.service.chunked_upload_service import ChunkedUploadService

chunked_upload_routes.register_routes(asgi_app.quart_app)


class _FakeChunkedUploadService:
    def __init__(self):
        self.calls = []

    def init(self, **kwargs):
        self.calls.append(("init", kwargs))
        return {
            "instant": False,
            "session_id": "sess-1",
            "chunk_size": kwargs["chunk_size"],
            "total_chunks": kwargs["total_chunks"],
            "received_chunks": [],
        }

    def save_chunk(self, **kwargs):
        self.calls.append(("save_chunk", kwargs))
        return {"received": 1, "total_chunks": 2, "missing_chunks": [1]}

    def status(self, **kwargs):
        self.calls.append(("status", kwargs))
        return {
            "session_id": kwargs["session_id"],
            "filename": "big.bin",
            "total_chunks": 2,
            "chunk_size": 1024,
            "received_chunks": [0],
            "missing_chunks": [1],
            "is_complete": False,
        }

    def complete(self, **kwargs):
        self.calls.append(("complete", kwargs))
        return {"upload_file_id": "f-1"}

    def abort(self, **kwargs):
        self.calls.append(("abort", kwargs))
        return None


def _setup(monkeypatch):
    account = SimpleNamespace(id=uuid4())
    svc = _FakeChunkedUploadService()

    async def _fake_resolve_account(account_id_override=None):
        return account, None

    # chunked_upload_routes 以「按值导入」方式持有 _resolve_account，必须在其模块命名空间打桩
    monkeypatch.setattr(chunked_upload_routes, "_resolve_account", _fake_resolve_account)
    monkeypatch.setattr(
        support, "_get_service", lambda cls: svc if cls is ChunkedUploadService else None
    )
    return account, svc


class TestChunkedUploadRoutes:
    def test_routes_registered(self):
        rules = [r.rule for r in asgi_app.quart_app.url_map.iter_rules()]
        assert "/space/chunked-uploads/init" in rules
        assert "/space/chunked-uploads/chunk" in rules
        assert "/space/chunked-uploads/<session_id>/status" in rules
        assert "/space/chunked-uploads/complete" in rules
        assert "/space/chunked-uploads/abort" in rules

    def test_init_missing_fields_returns_400(self, monkeypatch):
        _setup(monkeypatch)

        async def _run():
            async with asgi_app.quart_app.test_client() as client:
                resp = await client.post(
                    "/space/chunked-uploads/init", json={"filename": "a.bin"}
                )
                return resp, await resp.json

        resp, payload = asyncio.run(_run())
        assert resp.status_code == 400
        assert payload["code"] == "validate_error"

    def test_init_success(self, monkeypatch):
        _, svc = _setup(monkeypatch)

        async def _run():
            async with asgi_app.quart_app.test_client() as client:
                resp = await client.post(
                    "/space/chunked-uploads/init",
                    json={
                        "filename": "a.bin",
                        "total_size": 2048,
                        "chunk_size": 1024,
                        "total_chunks": 2,
                    },
                )
                return resp, await resp.json

        resp, payload = asyncio.run(_run())
        assert resp.status_code == 200
        assert payload["code"] == "success"
        assert payload["data"]["session_id"] == "sess-1"
        assert svc.calls[0][0] == "init"
        assert svc.calls[0][1]["filename"] == "a.bin"
        assert svc.calls[0][1]["total_chunks"] == 2

    def test_chunk_missing_session_id_returns_400(self, monkeypatch):
        _setup(monkeypatch)

        async def _run():
            async with asgi_app.quart_app.test_client() as client:
                resp = await client.post(
                    "/space/chunked-uploads/chunk", form={"index": "0"}
                )
                return resp, await resp.json

        resp, payload = asyncio.run(_run())
        assert resp.status_code == 400
        assert payload["code"] == "validate_error"

    def test_complete_missing_session_id_returns_400(self, monkeypatch):
        _setup(monkeypatch)

        async def _run():
            async with asgi_app.quart_app.test_client() as client:
                resp = await client.post("/space/chunked-uploads/complete", json={})
                return resp, await resp.json

        resp, payload = asyncio.run(_run())
        assert resp.status_code == 400
        assert payload["code"] == "validate_error"

    def test_status_returns_progress(self, monkeypatch):
        _, svc = _setup(monkeypatch)

        async def _run():
            async with asgi_app.quart_app.test_client() as client:
                resp = await client.get("/space/chunked-uploads/sess-1/status")
                return resp, await resp.json

        resp, payload = asyncio.run(_run())
        assert resp.status_code == 200
        assert payload["code"] == "success"
        assert payload["data"]["session_id"] == "sess-1"
        assert payload["data"]["missing_chunks"] == [1]
        assert payload["data"]["is_complete"] is False
        assert svc.calls[0][0] == "status"
