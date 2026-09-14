from contextlib import contextmanager
from types import SimpleNamespace
from uuid import uuid4

import pytest

from internal.service.knowledge_indexing_service import KnowledgeIndexingService
from internal.service.knowledge_media_extractor_service import MediaSegment


@contextmanager
def _auto_commit():
    yield


class _QueryStub:
    """支持 filter/update/one_or_none 的查询桩。"""

    def __init__(self, one_or_none_result=None):
        self._one_or_none = one_or_none_result

    def filter(self, *_a, **_kw):
        return self

    def update(self, *_a, **_kw):
        return 1

    def one_or_none(self):
        return self._one_or_none


class _SessionStub:
    """按调用顺序返回查询桩；队列耗尽返回默认桩。"""

    def __init__(self, queries=None):
        self._queries = list(queries or [])

    def query(self, *_a, **_kw):
        if self._queries:
            return self._queries.pop(0)
        return _QueryStub()


class _FakeMediaExtractor:
    def __init__(self, segments):
        self.segments = segments
        self.calls = []

    def extract(self, document, upload_file):
        self.calls.append((document, upload_file))
        return self.segments


class _FakeVectorService:
    def __init__(self):
        self.indexed = []

    def index_segment(self, segment, knowledge_base):
        self.indexed.append(segment.content)
        return str(segment.id)


def _build_service(media_segments):
    """构造索引服务；upload_file 查询由 session 队列首个桩返回。"""
    updates = []
    created_segments = []
    extractor = _FakeMediaExtractor(media_segments)
    vector_service = _FakeVectorService()
    upload_file = SimpleNamespace(id=uuid4(), key="2026/09/14/a.mp4", name="a.mp4")
    session = _SessionStub([_QueryStub(one_or_none_result=upload_file)])

    service = KnowledgeIndexingService(
        db=SimpleNamespace(session=session, auto_commit=lambda: _auto_commit()),
        file_extractor=SimpleNamespace(),
        embeddings_service=SimpleNamespace(calculate_token_count=lambda text: len(text)),
        jieba_service=SimpleNamespace(extract_keywords=lambda text, n: ["kw"]),
        knowledge_vector_service=vector_service,
        media_extractor=extractor,
    )
    service.update = lambda instance, **kwargs: updates.append(kwargs) or instance  # type: ignore[assignment]
    service.create = lambda model, **kwargs: created_segments.append(kwargs) or SimpleNamespace(id=uuid4(), **kwargs)  # type: ignore[assignment]
    return service, extractor, vector_service, created_segments, updates


def _document(media_type="video"):
    return SimpleNamespace(
        id=uuid4(),
        media_type=media_type,
        knowledge_base_id=uuid4(),
        owner_account_id=uuid4(),
        upload_file_id=uuid4(),
        knowledge_base=SimpleNamespace(id=uuid4()),
    )


def test_media_document_creates_one_segment_per_media_segment():
    service, extractor, vector_service, created, updates = _build_service([
        MediaSegment(content="场景一：产品特写", metadata={"media_type": "video", "scene_index": 1}),
        MediaSegment(content="场景二：用户使用", metadata={"media_type": "video", "scene_index": 2}),
    ])

    service._build_media_document(_document("video"))

    assert len(created) == 2
    assert created[0]["content"] == "场景一：产品特写"
    assert created[0]["metadata_"] == {"media_type": "video", "scene_index": 1}
    assert created[0]["position"] == 1
    assert created[1]["position"] == 2
    assert vector_service.indexed == ["场景一：产品特写", "场景二：用户使用"]


def test_media_document_records_parse_profile_tier1():
    service, _extractor, _vector, _created, updates = _build_service([
        MediaSegment(content="唯一片段", metadata={}),
    ])

    service._build_media_document(_document("image"))

    profiles = [u["parse_profile"] for u in updates if "parse_profile" in u]
    assert profiles, "应写入 parse_profile"
    assert profiles[-1]["tier1"]["status"] == "completed"
    assert profiles[-1]["tier1"]["media_type"] == "image"
    assert profiles[-1]["tier1"]["segment_count"] == 1


def test_media_document_does_not_call_text_splitting():
    """多媒体不走文本切分：file_extractor 不应被调用。"""
    file_extractor_calls = []
    service, _extractor, _vector, _created, _updates = _build_service([
        MediaSegment(content="唯一片段", metadata={}),
    ])
    service.file_extractor = SimpleNamespace(
        load=lambda *a, **k: file_extractor_calls.append("load")
    )

    service._build_media_document(_document("image"))

    assert file_extractor_calls == []


def test_media_document_with_no_segments_raises():
    service, _extractor, _vector, _created, _updates = _build_service([])

    with pytest.raises(Exception):
        service._build_media_document(_document("video"))
