from contextlib import contextmanager
from types import SimpleNamespace
from unittest.mock import Mock
from uuid import uuid4

from internal.model import MemoryCandidate
from internal.service.long_term_memory_service import (
    LongTermMemoryService,
    MemoryCandidateExtractor,
    MemoryExtractionResult,
    MemoryFact,
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


def _build_mock_lms(*, invoke_return=None, invoke_side_effect=None):
    mock_structured = Mock()
    if invoke_side_effect is not None:
        mock_structured.invoke.side_effect = invoke_side_effect
    else:
        mock_structured.invoke.return_value = invoke_return
    mock_llm = Mock()
    mock_llm.with_structured_output.return_value = mock_structured
    mock_lms = Mock()
    mock_lms.get_cheap_chat_model.return_value = mock_llm
    return mock_lms


def test_memory_fact_pydantic_model_accepts_valid_fields():
    fact = MemoryFact(
        memory_type="preference",
        content="用户偏好使用中文回答",
        candidate_key="preference:lang:zh",
        confidence=4,
    )

    assert fact.memory_type == "preference"
    assert fact.content == "用户偏好使用中文回答"
    assert fact.candidate_key == "preference:lang:zh"
    assert fact.confidence == 4


def test_memory_extraction_result_defaults_to_empty_facts():
    result = MemoryExtractionResult()

    assert result.facts == []


def test_memory_extraction_result_accepts_multiple_facts():
    facts = [
        MemoryFact(memory_type="profile", content="前端工程师", candidate_key="profile:job:fe", confidence=4),
        MemoryFact(memory_type="project", content="电商系统", candidate_key="project:name:ecom", confidence=3),
    ]
    result = MemoryExtractionResult(facts=facts)

    assert len(result.facts) == 2
    assert result.facts[0].memory_type == "profile"
    assert result.facts[1].memory_type == "project"


def test_extractor_returns_empty_list_when_get_cheap_chat_model_raises():
    mock_lms = Mock()
    mock_lms.get_cheap_chat_model.side_effect = RuntimeError("LLM down")
    extractor = MemoryCandidateExtractor(language_model_service=mock_lms)

    result = extractor.extract("我喜欢Python", "很好")

    assert result == []


def test_extractor_returns_empty_list_when_invoke_raises():
    mock_lms = _build_mock_lms(invoke_side_effect=RuntimeError("invoke failed"))
    extractor = MemoryCandidateExtractor(language_model_service=mock_lms)

    result = extractor.extract("query", "response")

    assert result == []


def test_extractor_returns_facts_from_llm_structured_output():
    extraction = MemoryExtractionResult(facts=[
        MemoryFact(memory_type="preference", content="喜欢Python", candidate_key="preference:lang:python", confidence=4),
        MemoryFact(memory_type="profile", content="前端工程师", candidate_key="profile:job:fe", confidence=3),
    ])
    mock_lms = _build_mock_lms(invoke_return=extraction)
    extractor = MemoryCandidateExtractor(language_model_service=mock_lms)

    result = extractor.extract("我用Python写代码", "好的，了解")

    assert len(result) == 2
    assert result[0]["memory_type"] == "preference"
    assert result[0]["candidate_key"] == "preference:lang:python"
    assert result[0]["confidence"] == 4
    assert result[1]["memory_type"] == "profile"


def test_extract_and_store_creates_candidates_from_extracted_facts():
    account_id = uuid4()
    account = SimpleNamespace(id=account_id)
    conversation_id = uuid4()
    facts = [
        {"memory_type": "preference", "content": "喜欢Python", "candidate_key": "preference:lang:python", "confidence": 4},
        {"memory_type": "profile", "content": "前端工程师", "candidate_key": "profile:job:fe", "confidence": 3},
    ]
    mock_extractor = SimpleNamespace(extract=lambda q, r: facts)
    candidate = SimpleNamespace(id=uuid4(), status="pending", occurrences=1, confidence=3)
    mock_tracker = SimpleNamespace(
        track=lambda acc, fact, conv_id=None: {"should_prompt": False, "candidate": candidate}
    )
    service = LongTermMemoryService(
        db=_fake_db(_SessionStub()),
        memory_candidate_extractor=mock_extractor,
        memory_confidence_tracker=mock_tracker,
    )

    results = service.extract_and_store(account, "我用Python", "好的", conversation_id=conversation_id)

    assert len(results) == 2
    assert results[0]["candidate_key"] == "preference:lang:python"
    assert results[0]["memory_type"] == "preference"
    assert results[0]["created"] is True
    assert results[0]["should_prompt"] is False
    assert results[1]["candidate_key"] == "profile:job:fe"


def test_extract_and_store_returns_empty_list_when_no_facts_extracted():
    account_id = uuid4()
    account = SimpleNamespace(id=account_id)
    mock_extractor = SimpleNamespace(extract=lambda q, r: [])
    mock_tracker = SimpleNamespace(
        track=lambda acc, fact, conv_id=None: {"should_prompt": False, "candidate": None}
    )
    service = LongTermMemoryService(
        db=_fake_db(_SessionStub()),
        memory_candidate_extractor=mock_extractor,
        memory_confidence_tracker=mock_tracker,
    )

    results = service.extract_and_store(account, "今天天气不错", "是的", conversation_id=uuid4())

    assert results == []


def test_extract_and_store_propagates_should_prompt_from_tracker():
    account_id = uuid4()
    account = SimpleNamespace(id=account_id)
    facts = [
        {"memory_type": "preference", "content": "喜欢Python", "candidate_key": "preference:lang:python", "confidence": 4},
    ]
    mock_extractor = SimpleNamespace(extract=lambda q, r: facts)
    candidate = SimpleNamespace(id=uuid4(), status="pending", occurrences=3, confidence=4)
    mock_tracker = SimpleNamespace(
        track=lambda acc, fact, conv_id=None: {"should_prompt": True, "candidate": candidate}
    )
    service = LongTermMemoryService(
        db=_fake_db(_SessionStub()),
        memory_candidate_extractor=mock_extractor,
        memory_confidence_tracker=mock_tracker,
    )

    results = service.extract_and_store(account, "我用Python", "好的")

    assert len(results) == 1
    assert results[0]["should_prompt"] is True
    assert results[0]["created"] is False
