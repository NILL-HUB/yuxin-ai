"""L2 按需解析的触发入口测试。

背景：`build_document_l2_task` 此前只注册进 Celery，但**没有任何派发点**，
属于「任务存在但用户/Agent 无法触发」的断链（与 P2-3 同类缺陷）。
本测试锁定触发入口：服务层派发 + 路由暴露。
"""
import asyncio
import sys
from types import ModuleType, SimpleNamespace
from uuid import uuid4

import app.http.asgi_app as asgi_app
from app.http import knowledge_mcp_routes, support
from internal.exception import NotFoundException
from internal.service.knowledge_base_service import KnowledgeBaseService


class _FakeIndexing:
    def __init__(self):
        self.sync_calls = []

    def build_document_l2(self, document_id, start_sec=None, end_sec=None):
        self.sync_calls.append(document_id)
        return {"document_id": str(document_id), "tier2": {"status": "completed"}}


def _install_fake_task(monkeypatch, *, available=True):
    """把 `internal.task.knowledge_l2_tasks` 换成桩模块。

    Celery 不可用时派发会抛异常、触发同步回退，因此需要能同时模拟两种情形；
    直接替换 `sys.modules` 中的模块，走的就是生产代码真实的 import 路径。
    """
    dispatched = {}
    module = ModuleType("internal.task.knowledge_l2_tasks")

    if available:
        class _Task:
            def delay(self, document_id, **kwargs):
                dispatched["args"] = (document_id,)
                dispatched["kwargs"] = kwargs
                return SimpleNamespace(id="task-1")

        module.build_document_l2_task = _Task()
    monkeypatch.setitem(sys.modules, "internal.task.knowledge_l2_tasks", module)
    return dispatched


def _make_service(document, *, exists=True):
    """构造仅含 L2 触发所需依赖的 `KnowledgeBaseService`。

    归属校验（知识库 / 文档）不是本用例的关注点，故桩掉 `get_user_content_base`
    与 `BaseService.get`；被测的是「校验通过后的派发行为」与「文档不存在时拒绝执行」。
    """
    service = KnowledgeBaseService.__new__(KnowledgeBaseService)
    service.db = SimpleNamespace(session=SimpleNamespace())
    indexing = _FakeIndexing()
    service._get_knowledge_indexing_service = lambda: indexing  # type: ignore[assignment]
    service.get_user_content_base = lambda kb_id, account: SimpleNamespace(id=kb_id)  # type: ignore[assignment]
    service.get = lambda model, doc_id: (document if exists else None)  # type: ignore[assignment]
    return service, indexing


def _document():
    kb_id = uuid4()
    return SimpleNamespace(
        id=uuid4(),
        knowledge_base_id=kb_id,
        media_type="video",
        name="demo.mp4",
    )


class TestTriggerDocumentL2:
    def test_dispatch_via_celery(self, monkeypatch):
        document = _document()
        service, indexing = _make_service(document)
        dispatched = _install_fake_task(monkeypatch)

        result = service.trigger_document_l2(
            document.knowledge_base_id, document.id, SimpleNamespace(id=uuid4())
        )

        assert dispatched["args"] == (str(document.id),)
        assert indexing.sync_calls == []
        assert result["document_id"] == str(document.id)

    def test_falls_back_to_sync_when_celery_unavailable(self, monkeypatch):
        document = _document()
        service, indexing = _make_service(document)
        dispatched = _install_fake_task(monkeypatch, available=False)

        result = service.trigger_document_l2(
            document.knowledge_base_id, document.id, SimpleNamespace(id=uuid4())
        )

        assert dispatched == {}
        assert indexing.sync_calls == [document.id]
        assert result["document_id"] == str(document.id)

    def test_document_of_other_base_is_rejected(self, monkeypatch):
        document = _document()
        service, indexing = _make_service(document)
        dispatched = _install_fake_task(monkeypatch)

        try:
            service.trigger_document_l2(
                uuid4(), document.id, SimpleNamespace(id=uuid4())
            )
        except NotFoundException:
            pass
        else:
            raise AssertionError("文档不属于该知识库时必须抛 NotFoundException")

        assert dispatched == {}
        assert indexing.sync_calls == []

    def test_missing_document_is_rejected(self, monkeypatch):
        document = _document()
        service, indexing = _make_service(document, exists=False)
        dispatched = _install_fake_task(monkeypatch)

        try:
            service.trigger_document_l2(
                document.knowledge_base_id, document.id, SimpleNamespace(id=uuid4())
            )
        except NotFoundException:
            pass
        else:
            raise AssertionError("文档不存在时必须抛 NotFoundException")

        assert dispatched == {}
        assert indexing.sync_calls == []


class _FakeKnowledgeBaseService:
    """只实现路由依赖的 L2 触发，便于断言派发入参。"""

    def __init__(self, raise_not_found=False):
        self.calls = []
        self.raise_not_found = raise_not_found

    def trigger_document_l2(
        self, knowledge_base_id, document_id, account, start_sec=None, end_sec=None
    ):
        self.calls.append((knowledge_base_id, document_id, account))
        if self.raise_not_found:
            raise NotFoundException("该文档不存在，请核实后重试")
        return {"document_id": str(document_id)}


def _setup_route(monkeypatch, svc):
    account = SimpleNamespace(id=uuid4())

    async def _fake_resolve_account(account_id_override=None):
        return account, None

    def _fake_get_service(cls):
        if cls is KnowledgeBaseService:
            return svc
        return None

    monkeypatch.setattr(knowledge_mcp_routes, "_resolve_account", _fake_resolve_account)
    monkeypatch.setattr(support, "_get_service", _fake_get_service)
    return account


class TestL2Route:
    def test_route_registered(self):
        knowledge_mcp_routes.register_routes(asgi_app.quart_app)
        rules = [r.rule for r in asgi_app.quart_app.url_map.iter_rules()]
        assert (
            "/space/knowledge-bases/<uuid:knowledge_base_id>/documents/<uuid:document_id>/l2"
            in rules
        )

    def test_route_dispatches_l2(self, monkeypatch):
        knowledge_mcp_routes.register_routes(asgi_app.quart_app)
        svc = _FakeKnowledgeBaseService()
        account = _setup_route(monkeypatch, svc)
        kb_id = uuid4()
        document_id = uuid4()

        async def _run():
            async with asgi_app.quart_app.test_client() as client:
                resp = await client.post(
                    f"/space/knowledge-bases/{kb_id}/documents/{document_id}/l2"
                )
                return resp, await resp.json

        resp, payload = asyncio.run(_run())
        assert resp.status_code == 200
        assert payload["message"] == "L2 深度解析已触发"
        assert svc.calls[0][0] == kb_id
        assert svc.calls[0][1] == document_id
        assert svc.calls[0][2] == account

    def test_route_surfaces_not_found(self, monkeypatch):
        knowledge_mcp_routes.register_routes(asgi_app.quart_app)
        svc = _FakeKnowledgeBaseService(raise_not_found=True)
        _setup_route(monkeypatch, svc)
        kb_id = uuid4()
        document_id = uuid4()

        async def _run():
            async with asgi_app.quart_app.test_client() as client:
                resp = await client.post(
                    f"/space/knowledge-bases/{kb_id}/documents/{document_id}/l2"
                )
                return resp, await resp.json

        resp, payload = asyncio.run(_run())
        assert payload["code"] == "not_found"
