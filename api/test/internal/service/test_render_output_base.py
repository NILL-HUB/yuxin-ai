"""成品库幂等创建测试。

设计 §4.2：首次需要写成品时幂等创建（get_or_create），不给从未出片的用户平白建库；
并发创建靠部分唯一索引兜底，因此 get_or_create 必须在 IntegrityError 后重查而不是抛错。
"""
from types import SimpleNamespace
from uuid import uuid4

import pytest

from internal.entity.knowledge_entity import (
    KnowledgeBaseType,
    KnowledgeCreatedFrom,
    KnowledgeScope,
)
from internal.service.knowledge_base_service import (
    RENDER_OUTPUT_BASE_NAME,
    KnowledgeBaseService,
)


class _Query:
    def __init__(self, results):
        self._results = list(results)

    def filter_by(self, **kwargs):
        self._kwargs = kwargs
        return self

    def one_or_none(self):
        return self._results[0] if self._results else None

    def one(self):
        if not self._results:
            raise AssertionError("one() 被调用但无结果，应改为重查逻辑")
        return self._results[0]


class _Session:
    def __init__(self, results):
        self._results = results
        self.rollbacks = 0

    def query(self, model):
        return _Query(self._results)

    def rollback(self):
        self.rollbacks += 1


class _DB:
    def __init__(self, results):
        self.session = _Session(results)


def _service(results, created=None, raise_integrity=False):
    service = KnowledgeBaseService.__new__(KnowledgeBaseService)
    service.db = _DB(results)

    def _create(model, **kwargs):
        if raise_integrity:
            from sqlalchemy.exc import IntegrityError

            raise IntegrityError("stmt", {}, Exception("duplicate key"))
        if created is not None:
            created.update(kwargs)
        return SimpleNamespace(id=uuid4(), **kwargs)

    service.create = _create
    service.auto_select_embedding_model = lambda: SimpleNamespace(id=uuid4())
    service.update = lambda model, **kwargs: model
    return service


def test_existing_base_is_reused():
    existing = SimpleNamespace(id=uuid4(), created_from="render_output")
    service = _service([existing])
    account = SimpleNamespace(id=uuid4())

    result = service.get_or_create_render_output_base(account)

    assert result is existing, "已存在成品库时必须复用，不能重复建"


def test_missing_base_is_created_with_marker():
    created = {}
    service = _service([], created=created)
    account = SimpleNamespace(id=uuid4())

    service.get_or_create_render_output_base(account)

    assert created["name"] == RENDER_OUTPUT_BASE_NAME
    assert created["created_from"] == KnowledgeCreatedFrom.RENDER_OUTPUT.value
    assert created["knowledge_scope"] == KnowledgeScope.USER_CONTENT.value
    assert created["base_type"] == KnowledgeBaseType.VIDEO.value
    assert created["owner_account_id"] == account.id


def test_existing_base_query_filters_by_render_output_marker():
    """必须按 created_from 查，不能按名称查——用户可能已手建同名库。"""
    service = _service([])
    captured = {}

    class _RecordingQuery(_Query):
        def filter_by(self, **kwargs):
            captured.update(kwargs)
            return self

    service.db.session.query = lambda model: _RecordingQuery([])

    service.get_or_create_render_output_base(SimpleNamespace(id=uuid4()))

    assert captured.get("created_from") == KnowledgeCreatedFrom.RENDER_OUTPUT.value


def test_concurrent_create_conflict_is_recovered():
    """并发下另一请求已建库 -> IntegrityError -> 重查返回既有库。"""
    existing = SimpleNamespace(id=uuid4(), created_from="render_output")
    service = _service([], raise_integrity=True)

    calls = {"n": 0}

    def _query(model):
        calls["n"] += 1
        # 第一次查（创建前）为空；冲突重查时返回既有库
        return _Query([existing] if calls["n"] > 1 else [])

    service.db.session.query = _query

    result = service.get_or_create_render_output_base(SimpleNamespace(id=uuid4()))

    assert result is existing
    assert service.db.session.rollbacks == 1, "冲突后必须 rollback 再重查"
