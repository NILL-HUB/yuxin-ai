from contextlib import contextmanager
from types import SimpleNamespace
from uuid import uuid4

from internal.model import MemoryCandidate, UserMemory
from internal.service.long_term_memory_service import (
    LongTermMemoryService,
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


def _extracted_fact(**overrides):
    base = {
        "candidate_key": "language_preference:zh",
        "memory_type": "preference",
        "content": "用户偏好使用中文回答",
        "confidence": 3,
    }
    base.update(overrides)
    return base


def test_tracker_should_not_prompt_until_three_high_confidence_occurrences():
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
        memory_type="preference",
        source_conversation_id=None,
        extracted_at=None,
    )
    service = MemoryConfidenceTracker(
        db=_fake_db(_SessionStub([_QueryStub(one_or_none_result=candidate)]))
    )

    result = service.track(SimpleNamespace(id=account_id), _extracted_fact(confidence=3))

    assert candidate.occurrences == 3
    assert result["should_prompt"] is True
    assert result["candidate"] is candidate


def test_tracker_should_create_pending_candidate_for_first_occurrence(monkeypatch):
    account_id = uuid4()
    service = MemoryConfidenceTracker(db=_fake_db(_SessionStub([_QueryStub(one_or_none_result=None)])))
    created = []
    monkeypatch.setattr(service, "create", lambda model, **kwargs: created.append((model, kwargs)) or SimpleNamespace(**kwargs))

    result = service.track(SimpleNamespace(id=account_id), _extracted_fact())

    assert created[0][0] is MemoryCandidate
    assert created[0][1]["occurrences"] == 1
    assert created[0][1]["memory_type"] == "preference"
    assert result["should_prompt"] is False


def test_tracker_should_record_conversation_id_and_extracted_at_on_create(monkeypatch):
    account_id = uuid4()
    conversation_id = uuid4()
    service = MemoryConfidenceTracker(db=_fake_db(_SessionStub([_QueryStub(one_or_none_result=None)])))
    created = []
    monkeypatch.setattr(service, "create", lambda model, **kwargs: created.append((model, kwargs)) or SimpleNamespace(**kwargs))

    service.track(SimpleNamespace(id=account_id), _extracted_fact(), conversation_id=conversation_id)

    assert created[0][1]["source_conversation_id"] == conversation_id
    assert created[0][1]["extracted_at"] is not None


def test_tracker_should_update_conversation_id_on_existing_candidate():
    account_id = uuid4()
    conversation_id = uuid4()
    candidate = SimpleNamespace(
        id=uuid4(),
        owner_account_id=account_id,
        candidate_key="language_preference:zh",
        content="用户偏好使用中文回答",
        confidence=3,
        occurrences=2,
        status="pending",
        metadata_={},
        memory_type="preference",
        source_conversation_id=None,
        extracted_at=None,
    )
    service = MemoryConfidenceTracker(
        db=_fake_db(_SessionStub([_QueryStub(one_or_none_result=candidate)]))
    )

    service.track(SimpleNamespace(id=account_id), _extracted_fact(), conversation_id=conversation_id)

    assert candidate.source_conversation_id == conversation_id
    assert candidate.extracted_at is not None


def test_tracker_should_not_prompt_for_ignored_candidate():
    account_id = uuid4()
    candidate = SimpleNamespace(
        id=uuid4(),
        owner_account_id=account_id,
        candidate_key="language_preference:zh",
        content="用户偏好使用中文回答",
        confidence=3,
        occurrences=5,
        status="confirmed",
        metadata_={},
        memory_type="preference",
        source_conversation_id=None,
        extracted_at=None,
    )
    service = MemoryConfidenceTracker(
        db=_fake_db(_SessionStub([_QueryStub(one_or_none_result=candidate)]))
    )

    result = service.track(SimpleNamespace(id=account_id), _extracted_fact())

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
    session = _SessionStub([_QueryStub(one_or_none_result=None)])
    shared_db = _fake_db(session)
    mock_extractor = SimpleNamespace(
        extract=lambda q, r: [_extracted_fact(candidate_key="preference:lang:python", content="喜欢Python", confidence=4)]
    )
    tracker = MemoryConfidenceTracker(db=shared_db)
    created = []

    def _create(model, **kwargs):
        obj = SimpleNamespace(**kwargs)
        obj.id = uuid4()
        created.append((model, kwargs))
        return obj

    monkeypatch.setattr(tracker, "create", _create)
    service = LongTermMemoryService(
        db=shared_db,
        memory_candidate_extractor=mock_extractor,
        memory_confidence_tracker=tracker,
    )

    results = service.extract_and_store(SimpleNamespace(id=account_id), "我用Python", "好的")

    assert len(results) == 1
    assert results[0]["status"] == "pending"
    assert results[0]["created"] is True
    assert created[0][0] is MemoryCandidate
    assert all(model is not UserMemory for model, _ in created)


def test_extract_and_store_should_return_empty_list_when_no_memory_extracted():
    account_id = uuid4()
    mock_extractor = SimpleNamespace(extract=lambda q, r: [])
    mock_tracker = SimpleNamespace(
        track=lambda acc, fact, conv_id=None: {"should_prompt": False, "candidate": None}
    )
    service = LongTermMemoryService(
        db=_fake_db(_SessionStub()),
        memory_candidate_extractor=mock_extractor,
        memory_confidence_tracker=mock_tracker,
    )

    results = service.extract_and_store(SimpleNamespace(id=account_id), "今天天气不错", "是的")

    assert results == []


def test_extract_and_store_should_increment_existing_candidate_occurrences():
    account_id = uuid4()
    candidate = SimpleNamespace(
        id=uuid4(),
        owner_account_id=account_id,
        candidate_key="preference:lang:python",
        content="喜欢Python",
        confidence=3,
        occurrences=2,
        status="pending",
        metadata_={},
        memory_type="preference",
        source_conversation_id=None,
        extracted_at=None,
    )
    session = _SessionStub([_QueryStub(one_or_none_result=candidate)])
    shared_db = _fake_db(session)
    mock_extractor = SimpleNamespace(
        extract=lambda q, r: [_extracted_fact(candidate_key="preference:lang:python", content="喜欢Python", confidence=4)]
    )
    tracker = MemoryConfidenceTracker(db=shared_db)
    service = LongTermMemoryService(
        db=shared_db,
        memory_candidate_extractor=mock_extractor,
        memory_confidence_tracker=tracker,
    )

    results = service.extract_and_store(SimpleNamespace(id=account_id), "我用Python", "好的")

    assert candidate.occurrences == 3
    assert len(results) == 1
    assert results[0]["created"] is False
    assert results[0]["candidate_id"] == candidate.id
