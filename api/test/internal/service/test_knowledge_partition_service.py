from contextlib import contextmanager
from types import SimpleNamespace
from uuid import uuid4

import pytest

from internal.exception import FailException, ValidateErrorException
from internal.service.knowledge_partition_service import KnowledgePartitionService


class _QueryStub:
    def __init__(self, *, one_or_none_result=None, all_result=None, first_result=None):
        self._one_or_none = one_or_none_result
        self._all = [] if all_result is None else all_result
        self._first = first_result

    def filter(self, *_a, **_kw):
        return self

    def filter_by(self, **_kw):
        return self

    def order_by(self, *_a, **_kw):
        return self

    def one_or_none(self):
        return self._one_or_none

    def all(self):
        return self._all

    def first(self):
        return self._first


class _SessionStub:
    def __init__(self, queries=None):
        self._queries = list(queries or [])

    def query(self, *_a, **_kw):
        if self._queries:
            return self._queries.pop(0)
        return _QueryStub()


@contextmanager
def _auto_commit():
    yield


def _new_service(session=None):
    return KnowledgePartitionService(
        db=SimpleNamespace(session=session or _SessionStub(), auto_commit=lambda: _auto_commit()),
    )


def test_top_level_partition_is_allowed(monkeypatch):
    service = _new_service(_SessionStub([_QueryStub(one_or_none_result=None)]))
    created = []
    monkeypatch.setattr(service, "create",
        lambda model, **kwargs: created.append(kwargs) or SimpleNamespace(**kwargs))

    service.create_partition(
        knowledge_base_id=uuid4(), name="产品A", partition_key="product-a", parent_id=None)

    assert created[0]["name"] == "产品A"
    assert created[0]["parent_id"] is None


def test_second_level_partition_is_allowed(monkeypatch):
    base_id = uuid4()
    parent = SimpleNamespace(id=uuid4(), parent_id=None)
    service = _new_service(_SessionStub([_QueryStub(one_or_none_result=parent)]))
    created = []
    monkeypatch.setattr(service, "create",
        lambda model, **kwargs: created.append(kwargs) or SimpleNamespace(**kwargs))

    service.create_partition(
        knowledge_base_id=base_id, name="外观", partition_key="appearance", parent_id=parent.id)

    assert created[0]["parent_id"] == parent.id


def test_third_level_partition_is_rejected():
    grandchild_parent = SimpleNamespace(id=uuid4(), parent_id=uuid4())
    service = _new_service(_SessionStub([_QueryStub(one_or_none_result=grandchild_parent)]))

    with pytest.raises(ValidateErrorException):
        service.create_partition(
            knowledge_base_id=uuid4(), name="三级", partition_key="third",
            parent_id=grandchild_parent.id)


def test_parent_not_found_is_rejected():
    service = _new_service(_SessionStub([_QueryStub(one_or_none_result=None)]))

    with pytest.raises(FailException):
        service.create_partition(
            knowledge_base_id=uuid4(), name="子类", partition_key="child", parent_id=uuid4())


def test_duplicate_partition_key_is_rejected():
    existing = SimpleNamespace(id=uuid4())
    service = _new_service(_SessionStub([_QueryStub(one_or_none_result=existing)]))

    with pytest.raises(FailException):
        service.create_partition(
            knowledge_base_id=uuid4(), name="重复", partition_key="dup", parent_id=None)


def test_list_partitions_returns_tree_ordered_rows():
    """列出某知识库的全部分区（按 sort_order 排序），供前端渲染分区树。"""
    rows = [
        SimpleNamespace(id=uuid4(), name="产品A", parent_id=None, sort_order=1),
        SimpleNamespace(id=uuid4(), name="外观", parent_id=uuid4(), sort_order=2),
    ]
    service = _new_service(_SessionStub([_QueryStub(all_result=rows)]))

    result = service.list_partitions(uuid4())

    assert result == rows


def test_delete_partition_rejects_when_children_exist():
    """有子分区时不允许删除父分区，避免产生孤儿分区。"""
    service = _new_service(_SessionStub([_QueryStub(all_result=[SimpleNamespace(id=uuid4())])]))

    with pytest.raises(FailException):
        service.delete_partition(uuid4(), uuid4())


def test_delete_partition_rejects_when_documents_exist():
    """分区下仍有素材时不允许删除，避免素材失去归属。"""
    service = _new_service(_SessionStub([
        _QueryStub(all_result=[]),
        _QueryStub(first_result=SimpleNamespace(id=uuid4())),
    ]))

    with pytest.raises(FailException):
        service.delete_partition(uuid4(), uuid4())


def test_delete_partition_succeeds_when_empty(monkeypatch):
    partition = SimpleNamespace(id=uuid4())
    service = _new_service(_SessionStub([
        _QueryStub(all_result=[]),
        _QueryStub(first_result=None),
        _QueryStub(one_or_none_result=partition),
    ]))
    deleted = []
    monkeypatch.setattr(service, "delete", lambda instance: deleted.append(instance))

    service.delete_partition(uuid4(), partition.id)

    assert deleted == [partition]
