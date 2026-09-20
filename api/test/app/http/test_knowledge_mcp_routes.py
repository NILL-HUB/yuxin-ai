"""用户端知识库与 MCP 路由测试：usage 路由与文档 schema 媒体字段。"""

import asyncio
from types import SimpleNamespace
from uuid import uuid4

import app.http.asgi_app as asgi_app
from app.http import knowledge_mcp_routes, support
from internal.service.storage_quota_service import StorageQuotaService

# register_routes 幂等；若 asgi_app 已注册则直接复用既有路由对象，
# 测试只需替换模块命名空间的 _resolve_account / support._get_service。
knowledge_mcp_routes.register_routes(asgi_app.quart_app)


def _setup(monkeypatch, service=None):
    """打桩路由依赖：账号解析 + 服务解析。

    knowledge_mcp_routes 持有 _resolve_account（按值导入）与 _get_service
    （转发 support），故两条都要打桩。
    """
    account = SimpleNamespace(id=uuid4())

    async def _fake_resolve_account(account_id_override=None):
        return account, None

    monkeypatch.setattr(knowledge_mcp_routes, "_resolve_account", _fake_resolve_account)
    monkeypatch.setattr(
        support, "_get_service", lambda cls: service if cls is StorageQuotaService else None
    )
    return account


class TestStorageUsageRoute:
    def test_route_registered(self):
        rules = [r.rule for r in asgi_app.quart_app.url_map.iter_rules()]
        assert "/space/storage/usage" in rules

    def test_storage_usage_returns_quota_summary(self, monkeypatch):
        """GET /space/storage/usage 返回 total/used/remaining/percent。"""
        calls = {}

        class _FakeQuota:
            def get_usage_summary(self, account_id):
                calls["account_id"] = account_id
                return {
                    "total_bytes": 100,
                    "used_bytes": 30,
                    "remaining_bytes": 70,
                    "usage_percent": 30.0,
                }

        account = _setup(monkeypatch, service=_FakeQuota())

        async def _run():
            async with asgi_app.quart_app.test_client() as client:
                resp = await client.get("/space/storage/usage")
                return resp, await resp.json

        resp, payload = asyncio.run(_run())

        assert resp.status_code == 200
        assert payload["code"] == "success"
        assert payload["data"] == {
            "total_bytes": 100,
            "used_bytes": 30,
            "remaining_bytes": 70,
            "usage_percent": 30.0,
        }
        assert calls["account_id"] == account.id


class _FakeDocModel:
    """构造 schema pre_dump 所需最小属性的假 KnowledgeDocument。"""

    def __init__(self, **kw):
        for key, value in kw.items():
            setattr(self, key, value)


class TestDocumentMediaFields:
    def test_document_list_includes_media_fields(self, monkeypatch):
        """文档列表响应应带 media_type/content_type/parse_profile，网格据此渲染。"""
        from datetime import UTC, datetime

        from internal.service import KnowledgeBaseService

        fake_doc = _FakeDocModel(
            id=uuid4(),
            name="demo.mp4",
            media_type="video",
            content_type="document",
            parse_profile={"video_frame_count": 12},
            character_count=120,
            segment_count=3,
            status="completed",
            error="",
            updated_at=datetime.now(UTC),
            created_at=datetime.now(UTC),
        )
        from dataclasses import dataclass

        @dataclass
        class Paginator:
            current_page: int = 1
            page_size: int = 20
            total_page: int = 1
            total_record: int = 1

        paginator = Paginator()

        class _FakeKb:
            @staticmethod
            def get_documents_with_page(knowledge_base_id, req, account):
                return [fake_doc], paginator

        account = _setup(monkeypatch, service=None)
        monkeypatch.setattr(
            support, "_get_service",
            lambda cls: _FakeKb() if cls is KnowledgeBaseService else None,
        )

        async def _run():
            async with asgi_app.quart_app.test_client() as client:
                resp = await client.get(f"/space/knowledge-bases/{uuid4()}/documents")
                return resp, await resp.json

        resp, payload = asyncio.run(_run())

        assert resp.status_code == 200
        item = payload["data"]["list"][0]
        assert item["media_type"] == "video"
        assert item["content_type"] == "document"
        assert item["parse_profile"] == {"video_frame_count": 12}
        assert item["segment_count"] == 3

    def test_document_detail_includes_media_fields(self, monkeypatch):
        """文档详情响应应带媒体字段。"""
        from datetime import UTC, datetime

        from internal.service import KnowledgeBaseService

        fake_doc = _FakeDocModel(
            id=uuid4(),
            knowledge_base_id=uuid4(),
            name="audio.mp3",
            media_type="audio",
            content_type="document",
            parse_profile={},
            character_count=50,
            segment_count=1,
            status="completed",
            error="",
            updated_at=datetime.now(UTC),
            created_at=datetime.now(UTC),
        )

        class _FakeKb:
            @staticmethod
            def get_document_detail(knowledge_base_id, document_id, account):
                return fake_doc

        _setup(monkeypatch, service=None)
        monkeypatch.setattr(
            support, "_get_service",
            lambda cls: _FakeKb() if cls is KnowledgeBaseService else None,
        )

        async def _run():
            async with asgi_app.quart_app.test_client() as client:
                resp = await client.get(
                    f"/space/knowledge-bases/{uuid4()}/documents/{uuid4()}"
                )
                return resp, await resp.json

        resp, payload = asyncio.run(_run())

        assert resp.status_code == 200
        item = payload["data"]
        assert item["media_type"] == "audio"
        assert item["parse_profile"] == {}