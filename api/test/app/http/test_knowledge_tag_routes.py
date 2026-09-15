"""知识库素材标签路由测试：列出 / 打标签 / 移除标签的参数校验与服务调用。"""

import asyncio
from types import SimpleNamespace
from uuid import uuid4

import app.http.asgi_app as asgi_app
from app.http import knowledge_mcp_routes, support
from internal.service.knowledge_base_service import KnowledgeBaseService
from internal.service.knowledge_tag_service import KnowledgeTagService

knowledge_mcp_routes.register_routes(asgi_app.quart_app)


class _FakeKnowledgeBaseService:
    """只提供路由用到的归属校验，避免越权读改他人素材标签。"""

    def __init__(self):
        self.accessible_calls = []

    def get_accessible_base(self, knowledge_base_id, account):
        self.accessible_calls.append(knowledge_base_id)
        return SimpleNamespace(id=knowledge_base_id)


class _FakeTagService:
    """记录服务调用入参，便于断言路由传参正确。"""

    def __init__(self):
        self.calls = []
        self.tags = [
            SimpleNamespace(id=uuid4(), name="产品A"),
            SimpleNamespace(id=uuid4(), name="产品B"),
        ]

    def list_document_tags(self, knowledge_document_id):
        self.calls.append(("list", knowledge_document_id))
        return self.tags

    def attach_document_tag(
        self,
        account_id,
        knowledge_document_id,
        tag_id,
        verify_document: bool = False,
    ):
        self.calls.append(
            ("attach", account_id, knowledge_document_id, tag_id, verify_document)
        )
        return SimpleNamespace(id=uuid4())

    def detach_document_tag(self, knowledge_document_id, tag_id):
        self.calls.append(("detach", knowledge_document_id, tag_id))
        return True


def _setup(monkeypatch):
    account = SimpleNamespace(id=uuid4())
    svc = _FakeTagService()
    kb_svc = _FakeKnowledgeBaseService()

    async def _fake_resolve_account(account_id_override=None):
        return account, None

    def _fake_get_service(cls):
        if cls is KnowledgeTagService:
            return svc
        if cls is KnowledgeBaseService:
            return kb_svc
        return None

    monkeypatch.setattr(knowledge_mcp_routes, "_resolve_account", _fake_resolve_account)
    monkeypatch.setattr(support, "_get_service", _fake_get_service)
    return account, svc, kb_svc


class TestKnowledgeTagRoutes:
    def test_routes_registered(self):
        rules = [r.rule for r in asgi_app.quart_app.url_map.iter_rules()]
        assert (
            "/space/knowledge-bases/<uuid:knowledge_base_id>/documents/<uuid:document_id>/tags"
            in rules
        )
        assert (
            "/space/knowledge-bases/<uuid:knowledge_base_id>/documents/<uuid:document_id>"
            "/tags/<uuid:tag_id>/delete"
            in rules
        )

    def test_list_document_tags(self, monkeypatch):
        _, svc, kb_svc = _setup(monkeypatch)
        kb_id = uuid4()
        document_id = uuid4()

        async def _run():
            async with asgi_app.quart_app.test_client() as client:
                resp = await client.get(
                    f"/space/knowledge-bases/{kb_id}/documents/{document_id}/tags"
                )
                return resp, await resp.json

        resp, payload = asyncio.run(_run())
        assert resp.status_code == 200
        assert payload["data"] == [
            {"id": str(svc.tags[0].id), "name": "产品A"},
            {"id": str(svc.tags[1].id), "name": "产品B"},
        ]
        assert svc.calls[0] == ("list", document_id)
        assert kb_svc.accessible_calls == [kb_id]

    def test_attach_requires_tag_id(self, monkeypatch):
        _, svc, _ = _setup(monkeypatch)
        kb_id = uuid4()
        document_id = uuid4()

        async def _run():
            async with asgi_app.quart_app.test_client() as client:
                resp = await client.post(
                    f"/space/knowledge-bases/{kb_id}/documents/{document_id}/tags", json={}
                )
                return resp, await resp.json

        resp, payload = asyncio.run(_run())
        assert resp.status_code == 400
        assert payload["code"] == "validate_error"
        assert svc.calls == []

    def test_attach_rejects_invalid_tag_id(self, monkeypatch):
        _, svc, _ = _setup(monkeypatch)
        kb_id = uuid4()
        document_id = uuid4()

        async def _run():
            async with asgi_app.quart_app.test_client() as client:
                resp = await client.post(
                    f"/space/knowledge-bases/{kb_id}/documents/{document_id}/tags",
                    json={"tag_id": "not-a-uuid"},
                )
                return resp, await resp.json

        resp, payload = asyncio.run(_run())
        assert resp.status_code == 400
        assert payload["code"] == "validate_error"
        assert svc.calls == []

    def test_attach_document_tag(self, monkeypatch):
        account, svc, kb_svc = _setup(monkeypatch)
        kb_id = uuid4()
        document_id = uuid4()
        tag_id = uuid4()

        async def _run():
            async with asgi_app.quart_app.test_client() as client:
                resp = await client.post(
                    f"/space/knowledge-bases/{kb_id}/documents/{document_id}/tags",
                    json={"tag_id": str(tag_id)},
                )
                return resp, await resp.json

        resp, payload = asyncio.run(_run())
        assert resp.status_code == 200
        assert payload["data"]["id"]
        call = svc.calls[0]
        assert call[0] == "attach"
        assert call[1] == account.id
        assert call[2] == document_id
        assert call[3] == tag_id
        assert call[4] is True
        assert kb_svc.accessible_calls == [kb_id]

    def test_detach_document_tag(self, monkeypatch):
        _, svc, kb_svc = _setup(monkeypatch)
        kb_id = uuid4()
        document_id = uuid4()
        tag_id = uuid4()

        async def _run():
            async with asgi_app.quart_app.test_client() as client:
                resp = await client.post(
                    f"/space/knowledge-bases/{kb_id}/documents/{document_id}/tags/{tag_id}/delete"
                )
                return resp, await resp.json

        resp, payload = asyncio.run(_run())
        assert resp.status_code == 200
        assert payload["message"] == "移除标签成功"
        assert svc.calls[0] == ("detach", document_id, tag_id)
        assert kb_svc.accessible_calls == [kb_id]
