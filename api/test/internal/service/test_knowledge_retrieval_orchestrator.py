from contextlib import contextmanager
from types import SimpleNamespace
from uuid import uuid4

from langchain_core.documents import Document as LCDocument

from internal.service.knowledge_retrieval_orchestrator import KnowledgeRetrievalOrchestrator


class _IdQueryStub:
    def __init__(self, ids):
        self._ids = list(ids)

    def filter(self, *_args, **_kwargs):
        return self

    def all(self):
        return [(id_,) for id_ in self._ids]


class _SessionStub:
    def __init__(self, id_groups):
        self._groups = list(id_groups)

    def query(self, *_args, **_kwargs):
        if self._groups:
            return _IdQueryStub(self._groups.pop(0))
        return _IdQueryStub([])


@contextmanager
def _auto_commit():
    yield


def _fake_db(session):
    return SimpleNamespace(session=session, auto_commit=lambda: _auto_commit())


def _make_doc(segment_id, content):
    return LCDocument(
        page_content=content,
        metadata={"segment_id": segment_id, "knowledge_base_id": "kb"},
    )


def _build_orchestrator(session, search_fn):
    retrieval_service = SimpleNamespace(search_in_knowledge_base=search_fn)
    return KnowledgeRetrievalOrchestrator(db=_fake_db(session), retrieval_service=retrieval_service)


def test_vertical_agent_task_should_prioritize_system_then_user_content():
    account_id = uuid4()
    sys_id = uuid4()
    uc_id = uuid4()
    session = _SessionStub([[sys_id], [uc_id]])
    calls = []

    def _search(knowledge_base_ids, query, account_id, k=4):
        calls.append(list(knowledge_base_ids))
        if knowledge_base_ids == [sys_id]:
            return [_make_doc("seg-sys", "系统规则")]
        return [_make_doc("seg-uc", "用户资料")]

    orchestrator = _build_orchestrator(session, _search)

    result = orchestrator.retrieve("查询", "vertical_agent_task", SimpleNamespace(id=account_id))

    assert calls == [[sys_id], [uc_id]]
    assert [doc.metadata["knowledge_scope"] for doc in result] == ["system", "user_content"]
    assert result[0].page_content == "系统规则"


def test_agent_operation_intent_should_also_prioritize_system_scope():
    account_id = uuid4()
    sys_id = uuid4()
    session = _SessionStub([[sys_id]])
    calls = []

    def _search(knowledge_base_ids, query, account_id, k=4):
        calls.append(list(knowledge_base_ids))
        return [_make_doc("seg-sys", "系统规则")]

    orchestrator = _build_orchestrator(session, _search)

    result = orchestrator.retrieve("查询", "agent_operation", SimpleNamespace(id=account_id))

    assert calls == [[sys_id]]
    assert result[0].metadata["knowledge_scope"] == "system"


def test_preference_query_should_only_retrieve_user_memory():
    account_id = uuid4()
    um_id = uuid4()
    session = _SessionStub([[um_id]])
    calls = []

    def _search(knowledge_base_ids, query, account_id, k=4):
        calls.append(list(knowledge_base_ids))
        return [_make_doc("seg-um", "偏好中文")]

    orchestrator = _build_orchestrator(session, _search)

    result = orchestrator.retrieve("偏好", "preference_query", SimpleNamespace(id=account_id))

    assert calls == [[um_id]]
    assert [doc.metadata["knowledge_scope"] for doc in result] == ["user_memory"]


def test_general_qa_should_prioritize_user_content_then_user_memory():
    account_id = uuid4()
    uc_id = uuid4()
    um_id = uuid4()
    session = _SessionStub([[uc_id], [um_id]])
    calls = []

    def _search(knowledge_base_ids, query, account_id, k=4):
        calls.append(list(knowledge_base_ids))
        if knowledge_base_ids == [uc_id]:
            return [_make_doc("seg-uc", "资料")]
        return [_make_doc("seg-um", "记忆")]

    orchestrator = _build_orchestrator(session, _search)

    result = orchestrator.retrieve("问题", "general_qa", SimpleNamespace(id=account_id))

    assert calls == [[uc_id], [um_id]]
    assert [doc.metadata["knowledge_scope"] for doc in result] == ["user_content", "user_memory"]


def test_duplicate_segment_across_scopes_should_keep_high_priority_one():
    account_id = uuid4()
    sys_id = uuid4()
    uc_id = uuid4()
    session = _SessionStub([[sys_id], [uc_id]])

    def _search(knowledge_base_ids, query, account_id, k=4):
        if knowledge_base_ids == [sys_id]:
            return [_make_doc("seg-dup", "共享片段"), _make_doc("seg-sys", "系统专属")]
        return [_make_doc("seg-dup", "共享片段"), _make_doc("seg-uc", "用户专属")]

    orchestrator = _build_orchestrator(session, _search)

    result = orchestrator.retrieve("查询", "vertical_agent_task", SimpleNamespace(id=account_id))

    segment_ids = [doc.metadata["segment_id"] for doc in result]
    assert segment_ids == ["seg-dup", "seg-sys", "seg-uc"]
    dup_doc = next(doc for doc in result if doc.metadata["segment_id"] == "seg-dup")
    assert dup_doc.metadata["knowledge_scope"] == "system"


def test_empty_scope_should_be_skipped_without_calling_retrieval():
    account_id = uuid4()
    um_id = uuid4()
    session = _SessionStub([[], [um_id]])
    calls = []

    def _search(knowledge_base_ids, query, account_id, k=4):
        calls.append(list(knowledge_base_ids))
        return [_make_doc("seg-um", "记忆")]

    orchestrator = _build_orchestrator(session, _search)

    result = orchestrator.retrieve("问题", "general_qa", SimpleNamespace(id=account_id))

    assert calls == [[um_id]]
    assert len(result) == 1
