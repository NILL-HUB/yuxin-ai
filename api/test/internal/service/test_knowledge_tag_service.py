"""知识库标签服务测试：关联读写 + 按标签查素材。"""
from types import SimpleNamespace
from uuid import uuid4

import pytest

from internal.exception import FailException
from internal.model import KnowledgeBaseTag, KnowledgeDocumentTag
from internal.service.knowledge_tag_service import KnowledgeTagService


class _QueryStub:
    def __init__(self, *, one_or_none=None, all_result=None):
        self._one_or_none = one_or_none
        self._all = [] if all_result is None else all_result

    def filter(self, *_a, **_kw):
        return self

    def filter_by(self, **_kw):
        return self

    def group_by(self, *_a, **_kw):
        return self

    def one_or_none(self):
        return self._one_or_none

    def all(self):
        return self._all


class _SessionStub:
    def __init__(self, queries):
        self._queries = list(queries)

    def query(self, *_a, **_kw):
        return self._queries.pop(0) if self._queries else _QueryStub()


def _service(queries=None):
    svc = KnowledgeTagService.__new__(KnowledgeTagService)
    svc.db = SimpleNamespace(session=_SessionStub(queries or []))
    return svc


class TestKnowledgeTagService:
    def test_attach_base_tag_creates_link_when_absent(self, monkeypatch):
        svc = _service([_QueryStub(one_or_none=None)])
        created = []
        monkeypatch.setattr(
            svc, "create",
            lambda model, **kw: created.append((model, kw)) or SimpleNamespace(**kw),
        )

        svc.attach_base_tag(uuid4(), uuid4(), uuid4())

        assert created[0][0] is KnowledgeBaseTag
        assert created[0][1]["tag_id"]

    def test_attach_base_tag_is_idempotent(self, monkeypatch):
        existing = SimpleNamespace(id=uuid4())
        svc = _service([_QueryStub(one_or_none=existing)])
        created = []
        monkeypatch.setattr(svc, "create", lambda *a, **kw: created.append(kw))

        result = svc.attach_base_tag(uuid4(), uuid4(), uuid4())

        assert result is existing
        assert created == []

    def test_attach_document_tag_creates_link(self, monkeypatch):
        svc = _service([_QueryStub(one_or_none=None)])
        created = []
        monkeypatch.setattr(
            svc, "create",
            lambda model, **kw: created.append((model, kw)) or SimpleNamespace(**kw),
        )

        svc.attach_document_tag(uuid4(), uuid4(), uuid4())

        assert created[0][0] is KnowledgeDocumentTag

    def test_detach_document_tag_returns_false_when_absent(self):
        svc = _service([_QueryStub(one_or_none=None)])
        assert svc.detach_document_tag(uuid4(), uuid4()) is False

    def test_detach_document_tag_deletes_when_present(self, monkeypatch):
        link = SimpleNamespace(id=uuid4())
        svc = _service([_QueryStub(one_or_none=link)])
        deleted = []
        monkeypatch.setattr(svc, "delete", lambda instance: deleted.append(instance))

        assert svc.detach_document_tag(uuid4(), uuid4()) is True
        assert deleted == [link]

    def test_document_ids_for_tags_returns_intersection_when_match_all(self):
        """match_all=True 时取同时具备全部标签的文档（用分组计数实现交集）。"""
        doc_a, doc_b = uuid4(), uuid4()
        rows = [(doc_a, 2), (doc_b, 1)]
        svc = _service([_QueryStub(all_result=rows)])

        ids = svc.document_ids_for_tags([uuid4(), uuid4()], match_all=True)

        assert ids == [doc_a]

    def test_document_ids_for_tags_returns_union_when_any(self):
        doc_a, doc_b = uuid4(), uuid4()
        rows = [(doc_a, 2), (doc_b, 1)]
        svc = _service([_QueryStub(all_result=rows)])

        ids = svc.document_ids_for_tags([uuid4()], match_all=False)

        assert set(ids) == {doc_a, doc_b}

    def test_document_ids_for_tags_returns_empty_for_blank_input(self):
        svc = _service([])
        assert svc.document_ids_for_tags([], match_all=False) == []
        assert svc.document_ids_for_tags([], match_all=True) == []

    def test_list_document_tags_returns_tag_rows(self):
        tag = SimpleNamespace(id=uuid4(), name="产品A")
        svc = _service([_QueryStub(all_result=[SimpleNamespace(tag_id=uuid4())]),
                        _QueryStub(all_result=[tag])])
        assert svc.list_document_tags(uuid4()) == [tag]

    def test_list_document_tags_returns_empty_without_links(self):
        svc = _service([_QueryStub(all_result=[])])
        assert svc.list_document_tags(uuid4()) == []

    def test_attach_document_tag_rejects_when_document_not_found(self):
        """给不存在的素材打标签应报错，避免产生悬挂关联。"""
        svc = _service([_QueryStub(one_or_none=None)])
        with pytest.raises(FailException):
            svc.attach_document_tag(uuid4(), uuid4(), uuid4(), verify_document=True)

    def test_attach_document_tag_proceeds_when_document_exists(self, monkeypatch):
        doc = SimpleNamespace(id=uuid4())
        svc = _service([_QueryStub(one_or_none=doc), _QueryStub(one_or_none=None)])
        created = []
        monkeypatch.setattr(
            svc, "create",
            lambda model, **kw: created.append((model, kw)) or SimpleNamespace(**kw),
        )

        svc.attach_document_tag(uuid4(), doc.id, uuid4(), verify_document=True)

        assert created[0][0] is KnowledgeDocumentTag

    def test_resolve_tag_ids_by_names_returns_matching_ids(self):
        tag = SimpleNamespace(id=uuid4(), name="产品A")
        svc = _service([_QueryStub(all_result=[tag])])

        assert svc.resolve_tag_ids_by_names(["产品A"]) == [tag.id]

    def test_resolve_tag_ids_by_names_returns_empty_for_blank_input(self):
        svc = _service([])
        assert svc.resolve_tag_ids_by_names([]) == []
        assert svc.resolve_tag_ids_by_names(["", "  "]) == []

    def test_resolve_tag_ids_by_names_returns_empty_when_no_match(self):
        svc = _service([_QueryStub(all_result=[])])
        assert svc.resolve_tag_ids_by_names(["不存在"]) == []
