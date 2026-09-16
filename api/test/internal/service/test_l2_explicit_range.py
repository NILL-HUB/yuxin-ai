"""L2 显式区间透传测试（规格 §2「A+B」：自动推导 + 支持显式指定）。

`start_sec` + `end_sec` 均给出时按显式区间密抽；缺省时由 L1 命中帧自动推导窗口。
本测试锁定「路由/服务 → 任务」这条透传链不丢参数。
"""
from types import SimpleNamespace
from uuid import uuid4

import pytest

from internal.service.knowledge_base_service import KnowledgeBaseService


class _Task:
    def __init__(self):
        self.calls = []

    def delay(self, *args, **kwargs):
        self.calls.append({"args": args, "kwargs": kwargs})


def _service(monkeypatch):
    service = KnowledgeBaseService.__new__(KnowledgeBaseService)
    service.get_user_content_base = lambda kb_id, account: SimpleNamespace(id=kb_id)
    document = SimpleNamespace(id=uuid4(), knowledge_base_id=uuid4())
    service.get = lambda model, doc_id: document
    task = _Task()
    import internal.task.knowledge_l2_tasks as module
    monkeypatch.setattr(module, "build_document_l2_task", task)
    return service, document, task


def test_explicit_range_is_forwarded_to_task(monkeypatch):
    service, document, task = _service(monkeypatch)
    account = SimpleNamespace(id=uuid4())

    service.trigger_document_l2(
        document.knowledge_base_id, document.id, account,
        start_sec=120.0, end_sec=140.0,
    )

    assert task.calls, "必须派发任务"
    assert task.calls[0]["kwargs"]["start_sec"] == 120.0
    assert task.calls[0]["kwargs"]["end_sec"] == 140.0


def test_without_explicit_range_kwargs_are_none(monkeypatch):
    service, document, task = _service(monkeypatch)
    account = SimpleNamespace(id=uuid4())

    service.trigger_document_l2(document.knowledge_base_id, document.id, account)

    assert task.calls[0]["kwargs"]["start_sec"] is None
    assert task.calls[0]["kwargs"]["end_sec"] is None


def test_build_document_l2_accepts_range_kwargs():
    """服务方法必须接受区间关键字参数（否则任务侧透传会 TypeError）。"""
    import inspect

    from internal.service.knowledge_indexing_service import KnowledgeIndexingService

    params = inspect.signature(KnowledgeIndexingService.build_document_l2).parameters
    assert "start_sec" in params
    assert "end_sec" in params
