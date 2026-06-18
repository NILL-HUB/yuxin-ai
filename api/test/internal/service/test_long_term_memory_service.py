from contextlib import contextmanager
from types import SimpleNamespace
from uuid import uuid4

from internal.model import MemoryCandidate, UserMemory
from internal.service.long_term_memory_service import (
    LongTermMemoryService,
    MemoryCandidateExtractor,
    MemoryConfidenceTracker,
    UserMemoryConfirmationService,
)


class _QueryStub:
    def __init__(self, *, one_or_none_result=None):
        self._one_or_none_result = one_or_none_result

    def filter(self, *_args, **_kwargs):
        return self

    def filter_by(self, **_kwargs):
        return self

    def one_or_none(self):
        return self._one_or_none_result


class _SessionStub:
    def __init__(self, queries=None):
        self._queries = list(queries or [])

    def query(self, *_args, **_kwargs):
        if self._queries:
            return self._queries.pop(0)
        return _QueryStub()


@contextmanager
def _auto_commit():
    yield


def _fake_db(session):
    return SimpleNamespace(session=session, auto_commit=lambda: _auto_commit())


def test_extractor_should_extract_language_preference_candidate():
    result = MemoryCandidateExtractor().extract("以后请一直用中文回答我")

    assert result == {
        "candidate_key": "language_preference:zh",
        "memory_type": "preference",
        "content": "用户偏好使用中文回答",
        "confidence": 3,
    }


def test_tracker_should_not_prompt_until_three_high_confidence_occurrences(monkeypatch):
    account_id = uuid4()
    candidate = SimpleNamespace(
        id=uuid4(),
        owner_account_id=account_id,
        candidate_key="language_preference:zh",
        content="用户偏好使用中文回答",
        confidence=3,
        occurrences=2,
        status="pending",
        metadata_={},
    )
    service = MemoryConfidenceTracker(
        db=_fake_db(_SessionStub([_QueryStub(one_or_none_result=candidate)]))
    )

    result = service.track(
        SimpleNamespace(id=account_id), MemoryCandidateExtractor().extract("请用中文回答")
    )

    assert candidate.occurrences == 3
    assert result["should_prompt"] is True
    assert result["candidate"] is candidate


def test_tracker_should_create_pending_candidate_for_first_occurrence(monkeypatch):
    account_id = uuid4()
    service = MemoryConfidenceTracker(db=_fake_db(_SessionStub([_QueryStub(one_or_none_result=None)])))
    created = []
    monkeypatch.setattr(service, "create", lambda model, **kwargs: created.append((model, kwargs)) or SimpleNamespace(**kwargs))

    result = service.track(SimpleNamespace(id=account_id), MemoryCandidateExtractor().extract("请用中文回答"))

    assert created[0][0] is MemoryCandidate
    assert created[0][1]["occurrences"] == 1
    assert result["should_prompt"] is False


def test_confirmation_should_save_candidate_to_user_memory(monkeypatch):
    account_id = uuid4()
    candidate = SimpleNamespace(
        id=uuid4(),
        owner_account_id=account_id,
        memory_type="preference",
        content="用户偏好使用中文回答",
        confidence=3,
        status="pending",
        metadata_={},
    )
    service = UserMemoryConfirmationService(
        db=_fake_db(_SessionStub([_QueryStub(one_or_none_result=candidate)]))
    )
    created = []
    monkeypatch.setattr(
        service,
        "create",
        lambda model, **kwargs: created.append((model, kwargs)) or SimpleNamespace(**kwargs),
    )

    result = service.confirm(
        candidate.id, SimpleNamespace(id=account_id), policy="manual_confirm"
    )

    assert created[0][0] is UserMemory
    assert candidate.status == "confirmed"
    assert result.status == "active"


def test_confirmation_should_ignore_candidate_without_writing_memory(monkeypatch):
    account_id = uuid4()
    candidate = SimpleNamespace(id=uuid4(), owner_account_id=account_id, status="pending", metadata_={})
    service = UserMemoryConfirmationService(db=_fake_db(_SessionStub([_QueryStub(one_or_none_result=candidate)])))
    monkeypatch.setattr(service, "create", lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError()))

    result = service.ignore(candidate.id, SimpleNamespace(id=account_id), never_remind=True)

    assert result.status == "ignored"
    assert result.metadata_["never_remind"] is True


def test_extract_and_store_should_create_pending_candidate_without_user_memory(monkeypatch):
    account_id = uuid4()
    service = LongTermMemoryService(db=_fake_db(_SessionStub([_QueryStub(one_or_none_result=None)])))
    created = []

    def _create(model, **kwargs):
        obj = SimpleNamespace(**kwargs)
        obj.id = uuid4()
        created.append((model, kwargs))
        return obj

    monkeypatch.setattr(service, "create", _create)

    result = service.extract_and_store(SimpleNamespace(id=account_id), "请用中文回答")

    assert result is not None
    assert result["status"] == "pending"
    assert result["created"] is True
    assert created[0][0] is MemoryCandidate
    assert created[0][1]["status"] == "pending"
    assert all(model is not UserMemory for model, _ in created)


def test_extract_and_store_should_return_none_when_no_memory_extracted(monkeypatch):
    account_id = uuid4()
    service = LongTermMemoryService(db=_fake_db(_SessionStub()))
    created = []
    monkeypatch.setattr(service, "create", lambda *_a, **_k: created.append(("nope",)) or SimpleNamespace())

    result = service.extract_and_store(SimpleNamespace(id=account_id), "今天天气不错")

    assert result is None
    assert created == []


def test_extract_and_store_should_increment_existing_candidate_occurrences(monkeypatch):
    account_id = uuid4()
    candidate = SimpleNamespace(
        id=uuid4(),
        owner_account_id=account_id,
        candidate_key="language_preference:zh",
        content="用户偏好使用中文回答",
        confidence=3,
        occurrences=2,
        status="pending",
        metadata_={},
    )
    service = LongTermMemoryService(db=_fake_db(_SessionStub([_QueryStub(one_or_none_result=candidate)])))
    monkeypatch.setattr(
        service,
        "create",
        lambda *_a, **_k: (_ for _ in ()).throw(AssertionError("不应创建新记录")),
    )

    result = service.extract_and_store(SimpleNamespace(id=account_id), "请用中文回答")

    assert candidate.occurrences == 3
    assert result["created"] is False
    assert result["status"] == "pending"
    assert result["candidate_id"] == candidate.id
