"""app.http.admin_routes_2（管理员工作流 + 管理员系统知识库）Quart 异步端点测试。

覆盖 internal/router/router.py 中 admin_workflow_handler 与
admin_system_knowledge_handler 注册的全部端点，每个端点至少一个用例。
"""

import asyncio
import io
from dataclasses import dataclass
from types import SimpleNamespace
from uuid import uuid4

import pytest
from werkzeug.datastructures import FileStorage

import app.http.asgi_app as asgi_app
from app.http import support
from app.http.admin_routes_2 import register_routes

register_routes(asgi_app.quart_app)


@dataclass
class _Paginator:
    total_page: int = 1
    total_record: int = 1
    current_page: int = 1
    page_size: int = 20


class _FakeQuery:
    def filter_by(self, **kwargs):
        return self

    def join(self, *args, **kwargs):
        return self

    def filter(self, *args, **kwargs):
        return self

    def scalar(self):
        return 0

    def one_or_none(self):
        return None


def _mock_schema_db(monkeypatch):
    """SystemKnowledgeResp.pre_dump 会查询 db.session，替换为可链式调用的假对象。"""
    monkeypatch.setattr(
        "internal.schema.admin_system_knowledge_schema.db",
        SimpleNamespace(session=SimpleNamespace(query=lambda *a, **k: _FakeQuery())),
    )


def _workflow_dict(workflow_id=None):
    return {
        "id": str(workflow_id or uuid4()),
        "name": "管理工作流",
        "tool_call_name": "admin_workflow",
        "icon": "http://icon.example/wf.png",
        "description": "desc",
        "status": "published",
        "is_public": True,
        "task_keywords": ["admin"],
        "creator_name": "Root",
        "created_at": 1710000000,
        "updated_at": 1710000000,
    }


class _FakeAdminWorkflowService:
    def __init__(self):
        self.calls = []

    def list_workflows(self, *, search="", status="all", current_page=1, page_size=20):
        self.calls.append(("list", search, status, current_page, page_size))
        return {
            "list": [_workflow_dict()],
            "paginator": {
                "total_record": 1,
                "total_page": 1,
                "current_page": current_page,
                "page_size": page_size,
            },
        }

    def get_workflow(self, workflow_id):
        self.calls.append(("get", workflow_id))
        return _workflow_dict(workflow_id)

    def update_workflow(self, workflow_id, *, status=None, is_public=None, task_keywords=None):
        self.calls.append(("update", workflow_id, status, is_public, task_keywords))
        return _workflow_dict(workflow_id)

    def offline_workflow(self, workflow_id):
        self.calls.append(("offline", workflow_id))

    def batch_offline_workflows(self, workflow_ids):
        self.calls.append(("batch_offline", workflow_ids))
        return {"succeeded": [str(w) for w in workflow_ids], "failed": []}


class _FakeWorkflowService:
    def __init__(self):
        self.calls = []

    def create_workflow(self, req, created_by_admin=None):
        self.calls.append(("create", req.name.data, created_by_admin))
        return SimpleNamespace(id=uuid4())

    def delete_workflow_for_admin(self, workflow_id, *, retention_days=None, deleted_by=None):
        self.calls.append(("delete", workflow_id, retention_days, deleted_by))

    def get_draft_graph_for_admin(self, workflow_id):
        self.calls.append(("draft_get", workflow_id))
        return {"nodes": [], "edges": []}

    def update_draft_graph_for_admin(self, workflow_id, draft_graph_dict):
        self.calls.append(("draft_update", workflow_id, draft_graph_dict))

    def publish_workflow_for_admin(self, workflow_id, summary=""):
        self.calls.append(("publish", workflow_id, summary))

    def get_workflow_versions_for_admin(self, workflow_id):
        self.calls.append(("versions", workflow_id))
        return [
            SimpleNamespace(
                id=uuid4(),
                workflow_id=workflow_id,
                version=1,
                is_current_published=True,
                summary="v1",
                created_at=1710000000,
                updated_at=1710000000,
            )
        ]

    def rollback_workflow_version_for_admin(self, workflow_id, version_id):
        self.calls.append(("rollback", workflow_id, version_id))

    def import_workflow(self, json_data, overwrite_name=False, created_by_admin=None):
        self.calls.append(("import", overwrite_name, created_by_admin))
        return SimpleNamespace(id=uuid4(), name="导入的工作流")

    def export_workflow_for_admin(self, workflow_id, *, include_versions=False):
        self.calls.append(("export", workflow_id, include_versions))
        return {"format": "yuxin-ai-workflow", "name": "工作流A"}


class TestAdminWorkflowRoutes:
    def _setup(self, monkeypatch):
        from internal.service import WorkflowService
        from internal.service.admin_workflow_service import AdminWorkflowService

        admin_wf_service = _FakeAdminWorkflowService()
        wf_service = _FakeWorkflowService()
        services = {AdminWorkflowService: admin_wf_service, WorkflowService: wf_service}
        monkeypatch.setattr(support, "_get_service", lambda cls: services.get(cls))
        return admin_wf_service, wf_service

    def test_list_workflows(self, monkeypatch):
        from urllib.parse import quote

        admin_wf_service, _ = self._setup(monkeypatch)

        async def _run():
            async with asgi_app.quart_app.test_client() as client:
                resp = await client.get(
                    "/admin/workflows?current_page=2&page_size=10&status=published&search=%s"
                    % quote("工作流")
                )
                return resp, await resp.json

        resp, payload = asyncio.run(_run())

        assert resp.status_code == 200
        assert payload["code"] == "success"
        assert len(payload["data"]["list"]) == 1
        assert payload["data"]["list"][0]["name"] == "管理工作流"
        assert payload["data"]["paginator"]["page_size"] == 10
        assert admin_wf_service.calls[0] == ("list", "工作流", "published", 2, 10)

    def test_get_workflow(self, monkeypatch):
        admin_wf_service, _ = self._setup(monkeypatch)
        workflow_id = uuid4()

        async def _run():
            async with asgi_app.quart_app.test_client() as client:
                resp = await client.get(f"/admin/workflows/{workflow_id}")
                return resp, await resp.json

        resp, payload = asyncio.run(_run())

        assert resp.status_code == 200
        assert payload["data"]["id"] == str(workflow_id)
        assert admin_wf_service.calls[0][0] == "get"
        assert admin_wf_service.calls[0][1] == workflow_id

    def test_update_workflow(self, monkeypatch):
        admin_wf_service, _ = self._setup(monkeypatch)
        workflow_id = uuid4()

        async def _run():
            async with asgi_app.quart_app.test_client() as client:
                resp = await client.patch(
                    f"/admin/workflows/{workflow_id}",
                    json={"status": "draft", "is_public": False, "task_keywords": ["kw1"]},
                )
                return resp, await resp.json

        resp, payload = asyncio.run(_run())

        assert resp.status_code == 200
        assert payload["code"] == "success"
        call = admin_wf_service.calls[0]
        assert call[0] == "update"
        assert call[1] == workflow_id
        assert call[2] == "draft"
        assert call[3] is False
        assert call[4] == ["kw1"]

    def test_update_workflow_rejects_bad_task_keywords(self, monkeypatch):
        self._setup(monkeypatch)

        async def _run():
            async with asgi_app.quart_app.test_client() as client:
                resp = await client.patch(
                    f"/admin/workflows/{uuid4()}",
                    json={"task_keywords": "not-a-list"},
                )
                return resp, await resp.json

        resp, payload = asyncio.run(_run())

        assert resp.status_code == 400
        assert payload["code"] == "validate_error"

    def test_offline_workflow(self, monkeypatch):
        admin_wf_service, _ = self._setup(monkeypatch)
        workflow_id = uuid4()

        async def _run():
            async with asgi_app.quart_app.test_client() as client:
                resp = await client.post(f"/admin/workflows/{workflow_id}/offline")
                return resp, await resp.json

        resp, payload = asyncio.run(_run())

        assert resp.status_code == 200
        assert payload["message"] == "下架工作流成功"
        assert admin_wf_service.calls[0] == ("offline", workflow_id)

    def test_create_workflow(self, monkeypatch):
        _, wf_service = self._setup(monkeypatch)

        async def _run():
            async with asgi_app.quart_app.test_client() as client:
                resp = await client.post(
                    "/admin/workflows",
                    json={
                        "name": "新工作流",
                        "tool_call_name": "new_wf",
                        "icon": "http://icon.example/a.png",
                        "description": "描述",
                        "task_keywords": ["kw"],
                    },
                )
                return resp, await resp.json

        resp, payload = asyncio.run(_run())

        assert resp.status_code == 200
        assert "id" in payload["data"]
        assert wf_service.calls[0][0] == "create"
        assert wf_service.calls[0][1] == "新工作流"

    def test_create_workflow_requires_name(self, monkeypatch):
        self._setup(monkeypatch)

        async def _run():
            async with asgi_app.quart_app.test_client() as client:
                resp = await client.post("/admin/workflows", json={})
                return resp, await resp.json

        resp, payload = asyncio.run(_run())

        assert resp.status_code == 400
        assert payload["code"] == "validate_error"

    def test_delete_workflow(self, monkeypatch):
        _, wf_service = self._setup(monkeypatch)
        workflow_id = uuid4()

        async def _run():
            async with asgi_app.quart_app.test_client() as client:
                resp = await client.delete(
                    f"/admin/workflows/{workflow_id}",
                    json={"retention_days": 7},
                )
                return resp, await resp.json

        resp, payload = asyncio.run(_run())

        assert resp.status_code == 200
        assert payload["message"] == "删除工作流成功"
        assert wf_service.calls[0][0] == "delete"
        assert wf_service.calls[0][1] == workflow_id
        assert wf_service.calls[0][2] == 7

    def test_get_draft_graph(self, monkeypatch):
        _, wf_service = self._setup(monkeypatch)
        workflow_id = uuid4()

        async def _run():
            async with asgi_app.quart_app.test_client() as client:
                resp = await client.get(f"/admin/workflows/{workflow_id}/draft-graph")
                return resp, await resp.json

        resp, payload = asyncio.run(_run())

        assert resp.status_code == 200
        assert "nodes" in payload["data"]
        assert wf_service.calls[0] == ("draft_get", workflow_id)

    def test_update_draft_graph(self, monkeypatch):
        _, wf_service = self._setup(monkeypatch)
        workflow_id = uuid4()

        async def _run():
            async with asgi_app.quart_app.test_client() as client:
                resp = await client.post(
                    f"/admin/workflows/{workflow_id}/draft-graph",
                    json={"nodes": [], "edges": []},
                )
                return resp, await resp.json

        resp, payload = asyncio.run(_run())

        assert resp.status_code == 200
        assert payload["message"] == "更新工作流草稿配置成功"
        assert wf_service.calls[0][0] == "draft_update"
        assert wf_service.calls[0][2] == {"nodes": [], "edges": []}

    def test_publish_workflow(self, monkeypatch):
        _, wf_service = self._setup(monkeypatch)
        workflow_id = uuid4()

        async def _run():
            async with asgi_app.quart_app.test_client() as client:
                resp = await client.post(
                    f"/admin/workflows/{workflow_id}/publish", json={"summary": "发布说明"}
                )
                return resp, await resp.json

        resp, payload = asyncio.run(_run())

        assert resp.status_code == 200
        assert payload["message"] == "发布工作流成功"
        assert wf_service.calls[0] == ("publish", workflow_id, "发布说明")

    def test_get_workflow_versions(self, monkeypatch):
        _, wf_service = self._setup(monkeypatch)
        workflow_id = uuid4()

        async def _run():
            async with asgi_app.quart_app.test_client() as client:
                resp = await client.get(f"/admin/workflows/{workflow_id}/versions")
                return resp, await resp.json

        resp, payload = asyncio.run(_run())

        assert resp.status_code == 200
        assert len(payload["data"]["list"]) == 1
        assert payload["data"]["list"][0]["version"] == 1
        assert wf_service.calls[0] == ("versions", workflow_id)

    def test_rollback_workflow_version(self, monkeypatch):
        _, wf_service = self._setup(monkeypatch)
        workflow_id = uuid4()
        version_id = uuid4()

        async def _run():
            async with asgi_app.quart_app.test_client() as client:
                resp = await client.post(
                    f"/admin/workflows/{workflow_id}/versions/{version_id}/rollback"
                )
                return resp, await resp.json

        resp, payload = asyncio.run(_run())

        assert resp.status_code == 200
        assert payload["message"] == "回滚工作流版本成功"
        assert wf_service.calls[0] == ("rollback", workflow_id, version_id)

    def test_batch_publish_workflows(self, monkeypatch):
        _, wf_service = self._setup(monkeypatch)
        wf_ids = [uuid4(), uuid4()]

        async def _run():
            async with asgi_app.quart_app.test_client() as client:
                resp = await client.post(
                    "/admin/workflows/batch/publish",
                    json={"workflow_ids": [str(w) for w in wf_ids]},
                )
                return resp, await resp.json

        resp, payload = asyncio.run(_run())

        assert resp.status_code == 200
        assert len(payload["data"]["succeeded"]) == 2
        assert wf_service.calls[0][0] == "publish"

    def test_batch_publish_requires_ids(self, monkeypatch):
        self._setup(monkeypatch)

        async def _run():
            async with asgi_app.quart_app.test_client() as client:
                resp = await client.post("/admin/workflows/batch/publish", json={})
                return resp, await resp.json

        resp, payload = asyncio.run(_run())

        assert resp.status_code == 400
        assert payload["code"] == "validate_error"

    def test_batch_offline_workflows(self, monkeypatch):
        admin_wf_service, _ = self._setup(monkeypatch)
        wf_ids = [uuid4(), uuid4()]

        async def _run():
            async with asgi_app.quart_app.test_client() as client:
                resp = await client.post(
                    "/admin/workflows/batch/offline",
                    json={"workflow_ids": [str(w) for w in wf_ids]},
                )
                return resp, await resp.json

        resp, payload = asyncio.run(_run())

        assert resp.status_code == 200
        assert len(payload["data"]["succeeded"]) == 2
        assert admin_wf_service.calls[0][0] == "batch_offline"
        assert [str(w) for w in admin_wf_service.calls[0][1]] == [str(w) for w in wf_ids]

    def test_import_workflow(self, monkeypatch):
        _, wf_service = self._setup(monkeypatch)

        async def _run():
            async with asgi_app.quart_app.test_client() as client:
                resp = await client.post(
                    "/admin/workflows/import",
                    json={"json_data": {"name": "wf", "format": "yuxin-ai-workflow"}, "overwrite_name": True},
                )
                return resp, await resp.json

        resp, payload = asyncio.run(_run())

        assert resp.status_code == 200
        assert payload["data"]["name"] == "导入的工作流"
        assert wf_service.calls[0][0] == "import"
        assert wf_service.calls[0][1] is True

    def test_import_workflow_rejects_bad_body(self, monkeypatch):
        self._setup(monkeypatch)

        async def _run():
            async with asgi_app.quart_app.test_client() as client:
                resp = await client.post("/admin/workflows/import", json={"foo": 1})
                return resp, await resp.json

        resp, payload = asyncio.run(_run())

        assert resp.status_code == 400
        assert payload["code"] == "validate_error"

    def test_export_workflow(self, monkeypatch):
        _, wf_service = self._setup(monkeypatch)
        workflow_id = uuid4()

        async def _run():
            async with asgi_app.quart_app.test_client() as client:
                resp = await client.get(
                    f"/admin/workflows/{workflow_id}/export?include_versions=true"
                )
                return resp, await resp.json

        resp, payload = asyncio.run(_run())

        assert resp.status_code == 200
        assert payload["data"]["format"] == "yuxin-ai-workflow"
        assert wf_service.calls[0] == ("export", workflow_id, True)


def _make_kb(**overrides):
    defaults = {
        "id": uuid4(),
        "name": "系统知识库",
        "description": "系统级描述",
        "knowledge_scope": "system",
        "owner_admin_user_id": None,
        "enabled": True,
        "created_at": 1710000000,
        "updated_at": 1710000000,
        "visibility_scope": "internal",
    }
    defaults.update(overrides)
    return SimpleNamespace(**defaults)


def _make_document(kb_id):
    return SimpleNamespace(
        id=uuid4(),
        knowledge_base_id=kb_id,
        name="文档A",
        character_count=10,
        segment_count=0,
        status="completed",
        error="",
        updated_at=1710000000,
        created_at=1710000000,
    )


class _FakeSystemKnowledgeService:
    def __init__(self):
        self.calls = []
        self.kb = _make_kb()

    def list_system_knowledge(self, *, page=1, page_size=20, search_word=""):
        self.calls.append(("list", page, page_size, search_word))
        return {
            "items": [self.kb],
            "total": 1,
            "page": page,
            "page_size": page_size,
            "total_pages": 1,
            "total_record": 1,
        }

    def create_system_knowledge(self, *, name, admin_user, description="", visibility_scope="internal"):
        self.calls.append(("create", name, admin_user.id, description, visibility_scope))
        return _make_kb(name=name, visibility_scope=visibility_scope)

    def get_system_knowledge(self, knowledge_base_id):
        self.calls.append(("get", knowledge_base_id))
        return self.kb

    def update_system_knowledge(self, knowledge_base_id, *, name=None, description=None, enabled=None, visibility_scope=None, embedding_model_id=None, admin_user=None):
        self.calls.append(
            ("update", knowledge_base_id, name, description, enabled, visibility_scope, admin_user.id)
        )
        return _make_kb(id=knowledge_base_id, name=name or "系统知识库", enabled=enabled, visibility_scope=visibility_scope)

    def delete_system_knowledge(self, knowledge_base_id, *, admin_user=None, retention_days=None):
        self.calls.append(("delete", knowledge_base_id, admin_user.id, retention_days))

    def list_documents_for_admin(self, knowledge_base_id, req):
        self.calls.append(
            ("doc_list", knowledge_base_id, req.current_page.data, req.page_size.data, req.search_word.data)
        )
        return [_make_document(knowledge_base_id)], _Paginator(page_size=req.page_size.data)

    def upload_document_for_admin(self, knowledge_base_id, file):
        self.calls.append(("doc_upload", knowledge_base_id, file.filename))
        return SimpleNamespace(id=uuid4(), name=file.filename)

    def get_document_for_admin(self, knowledge_base_id, document_id):
        self.calls.append(("doc_get", knowledge_base_id, document_id))
        return _make_document(knowledge_base_id)

    def delete_document_for_admin(self, knowledge_base_id, document_id, *, admin_user=None, retention_days=None):
        self.calls.append(("doc_delete", knowledge_base_id, document_id, admin_user.id, retention_days))

    def create_text_document_for_admin(self, knowledge_base_id, name, content):
        self.calls.append(("doc_text_create", knowledge_base_id, name, content))
        return SimpleNamespace(id=uuid4(), name=name)

    def update_text_document_for_admin(self, knowledge_base_id, document_id, name, content):
        self.calls.append(("doc_text_update", knowledge_base_id, document_id, name, content))
        return SimpleNamespace(id=uuid4(), name=name)

    def get_segments_for_admin(self, knowledge_base_id, document_id, req):
        self.calls.append(("seg_list", knowledge_base_id, document_id, req.current_page.data))
        return [], _Paginator(page_size=req.page_size.data)

    def hit_test_for_admin(self, knowledge_base_id, req):
        self.calls.append(("hit", knowledge_base_id, req.query.data, req.k.data))
        return {"hits": []}


class TestAdminSystemKnowledgeRoutes:
    def _setup(self, monkeypatch):
        from internal.service.scoped_knowledge_service import SystemKnowledgeService

        _mock_schema_db(monkeypatch)
        service = _FakeSystemKnowledgeService()
        monkeypatch.setattr(
            support, "_get_service", lambda cls: service if cls is SystemKnowledgeService else None
        )
        return service

    def test_list_system_knowledge(self, monkeypatch):
        from urllib.parse import quote

        service = self._setup(monkeypatch)

        async def _run():
            async with asgi_app.quart_app.test_client() as client:
                resp = await client.get(
                    "/admin/system-knowledge?page=2&page_size=10&search_word=%s"
                    % quote("规则")
                )
                return resp, await resp.json

        resp, payload = asyncio.run(_run())

        assert resp.status_code == 200
        assert payload["code"] == "success"
        assert payload["data"]["total"] == 1
        assert payload["data"]["items"][0]["name"] == "系统知识库"
        assert payload["data"]["page"] == 2
        assert payload["data"]["page_size"] == 10
        assert service.calls[0] == ("list", 2, 10, "规则")

    def test_create_system_knowledge(self, monkeypatch):
        service = self._setup(monkeypatch)

        async def _run():
            async with asgi_app.quart_app.test_client() as client:
                resp = await client.post(
                    "/admin/system-knowledge",
                    json={"name": "新建知识库", "description": "描述", "visibility_scope": "public"},
                )
                return resp, await resp.json

        resp, payload = asyncio.run(_run())

        assert resp.status_code == 200
        assert payload["code"] == "success"
        assert payload["data"]["name"] == "新建知识库"
        call = service.calls[0]
        assert call[0] == "create"
        assert call[1] == "新建知识库"
        assert call[3] == "描述"
        assert call[4] == "public"

    def test_create_system_knowledge_requires_name(self, monkeypatch):
        self._setup(monkeypatch)

        async def _run():
            async with asgi_app.quart_app.test_client() as client:
                resp = await client.post("/admin/system-knowledge", json={})
                return resp, await resp.json

        resp, payload = asyncio.run(_run())

        assert resp.status_code == 400
        assert payload["code"] == "validate_error"

    def test_get_system_knowledge(self, monkeypatch):
        service = self._setup(monkeypatch)
        kb_id = uuid4()

        async def _run():
            async with asgi_app.quart_app.test_client() as client:
                resp = await client.get(f"/admin/system-knowledge/{kb_id}")
                return resp, await resp.json

        resp, payload = asyncio.run(_run())

        assert resp.status_code == 200
        assert payload["data"]["name"] == "系统知识库"
        assert service.calls[0][0] == "get"

    def test_update_system_knowledge(self, monkeypatch):
        service = self._setup(monkeypatch)
        kb_id = uuid4()

        async def _run():
            async with asgi_app.quart_app.test_client() as client:
                resp = await client.post(
                    f"/admin/system-knowledge/{kb_id}",
                    json={"name": "更新后", "enabled": False, "visibility_scope": "public"},
                )
                return resp, await resp.json

        resp, payload = asyncio.run(_run())

        assert resp.status_code == 200
        assert payload["code"] == "success"
        assert payload["data"]["name"] == "更新后"
        assert payload["data"]["enabled"] is False
        call = service.calls[0]
        assert call[0] == "update"
        assert call[1] == kb_id
        assert call[2] == "更新后"
        assert call[3] is None
        assert call[4] is False
        assert call[5] == "public"

    def test_delete_system_knowledge(self, monkeypatch):
        service = self._setup(monkeypatch)
        kb_id = uuid4()

        async def _run():
            async with asgi_app.quart_app.test_client() as client:
                resp = await client.delete(
                    f"/admin/system-knowledge/{kb_id}", json={"retention_days": 30}
                )
                return resp, await resp.json

        resp, payload = asyncio.run(_run())

        assert resp.status_code == 200
        assert payload["code"] == "success"
        assert payload["data"]["id"] == str(kb_id)
        call = service.calls[0]
        assert call[0] == "delete"
        assert call[1] == kb_id
        assert call[3] == 30

    def test_get_documents(self, monkeypatch):
        service = self._setup(monkeypatch)
        kb_id = uuid4()

        async def _run():
            async with asgi_app.quart_app.test_client() as client:
                resp = await client.get(
                    f"/admin/system-knowledge/{kb_id}/documents?current_page=1&page_size=10"
                )
                return resp, await resp.json

        resp, payload = asyncio.run(_run())

        assert resp.status_code == 200
        assert len(payload["data"]["list"]) == 1
        assert payload["data"]["list"][0]["name"] == "文档A"
        assert payload["data"]["paginator"]["page_size"] == 10
        call = service.calls[0]
        assert call[0] == "doc_list"
        assert call[2] == 1
        assert call[3] == 10

    def test_upload_document(self, monkeypatch):
        service = self._setup(monkeypatch)
        kb_id = uuid4()

        async def _run():
            async with asgi_app.quart_app.test_client() as client:
                resp = await client.post(
                    f"/admin/system-knowledge/{kb_id}/documents/upload",
                    files={
                        "file": FileStorage(
                            stream=io.BytesIO(b"content"), filename="doc.txt"
                        )
                    },
                )
                return resp, await resp.json

        resp, payload = asyncio.run(_run())

        assert resp.status_code == 200
        assert payload["data"]["name"] == "doc.txt"
        call = service.calls[0]
        assert call[0] == "doc_upload"
        assert call[2] == "doc.txt"

    def test_upload_document_requires_file(self, monkeypatch):
        self._setup(monkeypatch)

        async def _run():
            async with asgi_app.quart_app.test_client() as client:
                resp = await client.post(f"/admin/system-knowledge/{uuid4()}/documents/upload")
                return resp, await resp.json

        resp, payload = asyncio.run(_run())

        assert resp.status_code == 400
        assert payload["code"] == "validate_error"

    def test_create_text_document(self, monkeypatch):
        service = self._setup(monkeypatch)
        kb_id = uuid4()

        async def _run():
            async with asgi_app.quart_app.test_client() as client:
                resp = await client.post(
                    f"/admin/system-knowledge/{kb_id}/documents/text",
                    json={"name": "纯文本文档", "content": "正文内容"},
                )
                return resp, await resp.json

        resp, payload = asyncio.run(_run())

        assert resp.status_code == 200
        assert payload["data"]["name"] == "纯文本文档"
        call = service.calls[0]
        assert call[0] == "doc_text_create"
        assert call[2] == "纯文本文档"
        assert call[3] == "正文内容"

    def test_create_text_document_requires_content(self, monkeypatch):
        self._setup(monkeypatch)

        async def _run():
            async with asgi_app.quart_app.test_client() as client:
                resp = await client.post(
                    f"/admin/system-knowledge/{uuid4()}/documents/text",
                    json={"name": "无内容"},
                )
                return resp, await resp.json

        resp, payload = asyncio.run(_run())

        assert resp.status_code == 400
        assert payload["code"] == "validate_error"

    def test_get_document(self, monkeypatch):
        service = self._setup(monkeypatch)
        kb_id = uuid4()
        doc_id = uuid4()

        async def _run():
            async with asgi_app.quart_app.test_client() as client:
                resp = await client.get(f"/admin/system-knowledge/{kb_id}/documents/{doc_id}")
                return resp, await resp.json

        resp, payload = asyncio.run(_run())

        assert resp.status_code == 200
        assert payload["data"]["name"] == "文档A"
        call = service.calls[0]
        assert call[0] == "doc_get"
        assert call[1] == kb_id
        assert call[2] == doc_id

    def test_update_document(self, monkeypatch):
        service = self._setup(monkeypatch)
        kb_id = uuid4()
        doc_id = uuid4()

        async def _run():
            async with asgi_app.quart_app.test_client() as client:
                resp = await client.post(
                    f"/admin/system-knowledge/{kb_id}/documents/{doc_id}",
                    json={"name": "编辑后", "content": "新正文"},
                )
                return resp, await resp.json

        resp, payload = asyncio.run(_run())

        assert resp.status_code == 200
        assert payload["data"]["name"] == "编辑后"
        call = service.calls[0]
        assert call[0] == "doc_text_update"
        assert call[1] == kb_id
        assert call[2] == doc_id
        assert call[3] == "编辑后"
        assert call[4] == "新正文"

    def test_delete_document(self, monkeypatch):
        service = self._setup(monkeypatch)
        kb_id = uuid4()
        doc_id = uuid4()

        async def _run():
            async with asgi_app.quart_app.test_client() as client:
                resp = await client.delete(
                    f"/admin/system-knowledge/{kb_id}/documents/{doc_id}",
                    json={"retention_days": 7},
                )
                return resp, await resp.json

        resp, payload = asyncio.run(_run())

        assert resp.status_code == 200
        assert payload["message"] == "删除文档成功"
        call = service.calls[0]
        assert call[0] == "doc_delete"
        assert call[1] == kb_id
        assert call[2] == doc_id
        assert call[4] == 7

    def test_get_segments(self, monkeypatch):
        service = self._setup(monkeypatch)
        kb_id = uuid4()
        doc_id = uuid4()

        async def _run():
            async with asgi_app.quart_app.test_client() as client:
                resp = await client.get(
                    f"/admin/system-knowledge/{kb_id}/documents/{doc_id}/segments?current_page=1&page_size=20"
                )
                return resp, await resp.json

        resp, payload = asyncio.run(_run())

        assert resp.status_code == 200
        assert payload["data"]["list"] == []
        assert payload["data"]["paginator"]["page_size"] == 20
        call = service.calls[0]
        assert call[0] == "seg_list"
        assert call[1] == kb_id
        assert call[2] == doc_id

    def test_hit_test(self, monkeypatch):
        service = self._setup(monkeypatch)
        kb_id = uuid4()

        async def _run():
            async with asgi_app.quart_app.test_client() as client:
                resp = await client.post(
                    f"/admin/system-knowledge/{kb_id}/hit-test",
                    json={"query": "测试", "retrieval_strategy": "semantic", "k": 5},
                )
                return resp, await resp.json

        resp, payload = asyncio.run(_run())

        assert resp.status_code == 200
        assert payload["data"]["hits"] == []
        call = service.calls[0]
        assert call[0] == "hit"
        assert call[2] == "测试"
        assert call[3] == 5

    def test_hit_test_requires_query(self, monkeypatch):
        self._setup(monkeypatch)

        async def _run():
            async with asgi_app.quart_app.test_client() as client:
                resp = await client.post(
                    f"/admin/system-knowledge/{uuid4()}/hit-test", json={}
                )
                return resp, await resp.json

        resp, payload = asyncio.run(_run())

        assert resp.status_code == 400
        assert payload["code"] == "validate_error"
