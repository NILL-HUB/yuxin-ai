"""解析链路写入视觉向量测试。

覆盖两个关键点：
1. 带 frame_url 的视频帧片段要建立视觉向量索引；
2. 必须在解析时把 account_id/document_id 传给媒体提取器，否则关键帧
   根本不会被留存（frame_url 恒为空），视觉向量链路静默失效。
"""
from contextlib import contextmanager
from types import SimpleNamespace
from uuid import uuid4

from internal.service.knowledge_media_extractor_service import MediaSegment
from internal.service.knowledge_indexing_service import KnowledgeIndexingService


@contextmanager
def _auto_commit():
    yield


class _QueryStub:
    def __init__(self, one_or_none_result=None, all_result=None):
        self._one_or_none = one_or_none_result
        self._all = [] if all_result is None else all_result

    def filter(self, *_a, **_kw):
        return self

    def filter_by(self, **_kw):
        return self

    def update(self, *_a, **_kw):
        return 1

    def delete(self, *_a, **_kw):
        return 1

    def all(self):
        return self._all

    def one_or_none(self):
        return self._one_or_none


class _SessionStub:
    def __init__(self, queries=None):
        self._queries = list(queries or [])

    def query(self, *_a, **_kw):
        return self._queries.pop(0) if self._queries else _QueryStub()


class _FakeMediaExtractor:
    def __init__(self, segments):
        self.segments = segments
        self.calls = []

    def extract(self, document, upload_file, account_id=None, document_id=None):
        self.calls.append(
            {"document": document, "upload_file": upload_file,
             "account_id": account_id, "document_id": document_id}
        )
        return self.segments


class _FakeVisualService:
    def __init__(self, embedding=None):
        self._embedding = embedding if embedding is not None else [0.1, 0.2]
        self.deleted = []
        self.indexed = []

    def delete_by_document(self, document_id):
        self.deleted.append(document_id)

    def embed_image(self, data_uri):
        return list(self._embedding)

    def index_frame(self, **kwargs):
        self.indexed.append(kwargs)
        return str(kwargs["segment_id"])


class _FakeStorage:
    def __init__(self, fail=False):
        self.fail = fail
        self.downloaded = []

    def download_file(self, key, path):
        if self.fail:
            raise RuntimeError("storage down")
        self.downloaded.append(key)
        with open(path, "wb") as fh:
            fh.write(b"\xff\xd8\xff\xe0jpeg")


def _build_service(media_segments, visual_service=None, storage=None):
    extractor = _FakeMediaExtractor(media_segments)
    upload_file = SimpleNamespace(id=uuid4(), key="2026/09/15/a.mp4", name="a.mp4")
    service = KnowledgeIndexingService(
        db=SimpleNamespace(session=_SessionStub([_QueryStub(one_or_none_result=upload_file)]),
                          auto_commit=lambda: _auto_commit()),
        file_extractor=SimpleNamespace(),
        embeddings_service=SimpleNamespace(calculate_token_count=lambda text: len(text)),
        jieba_service=SimpleNamespace(extract_keywords=lambda text, n: ["kw"]),
        knowledge_vector_service=SimpleNamespace(index_segment=lambda *a, **kw: "id",
                                                remove_segment=lambda *a: None),
        media_extractor=extractor,
        visual_embedding_service=visual_service,
        cos_service=storage,
    )
    service.update = lambda instance, **kwargs: instance
    service.create = lambda model, **kwargs: SimpleNamespace(id=uuid4(), **kwargs)
    return service, extractor


def _document(media_type="video"):
    return SimpleNamespace(
        id=uuid4(),
        media_type=media_type,
        knowledge_base_id=uuid4(),
        owner_account_id=uuid4(),
        upload_file_id=uuid4(),
        knowledge_base=SimpleNamespace(id=uuid4(), embedding_model_id=uuid4()),
    )


def _frame_segment(frame_url="frames/f1.jpg", scene_index=1):
    return MediaSegment(
        content="画面描述",
        metadata={"media_type": "video", "frame_url": frame_url, "scene_index": scene_index},
    )


class TestVisualIndexing:
    def test_frame_segments_get_visual_vectors(self):
        visual = _FakeVisualService()
        doc = _document()
        service, _extractor = _build_service([_frame_segment()], visual, _FakeStorage())

        service._index_visual_vectors(doc, [SimpleNamespace(
            id=uuid4(), metadata_={"media_type": "video", "frame_url": "frames/f1.jpg",
                                   "scene_index": 3},
        )])

        assert len(visual.indexed) == 1
        assert visual.indexed[0]["frame_url"] == "frames/f1.jpg"
        assert visual.indexed[0]["scene_index"] == 3
        assert visual.indexed[0]["knowledge_document_id"] is doc.id
        assert visual.indexed[0]["knowledge_base_id"] is doc.knowledge_base_id
        assert visual.indexed[0]["account_id"] == doc.owner_account_id

    def test_segments_without_frame_url_are_skipped(self):
        visual = _FakeVisualService()
        service, _ = _build_service([], visual, _FakeStorage())

        service._index_visual_vectors(_document(), [SimpleNamespace(
            id=uuid4(), metadata_={"media_type": "video", "frame_url": ""},
        )])

        assert visual.indexed == []

    def test_non_video_segments_are_skipped(self):
        visual = _FakeVisualService()
        service, _ = _build_service([], visual, _FakeStorage())

        service._index_visual_vectors(_document(), [SimpleNamespace(
            id=uuid4(), metadata_={"media_type": "document", "frame_url": "x"},
        )])

        assert visual.indexed == []

    def test_rebuild_clears_previous_visual_vectors(self):
        """重解析必须清理旧视觉向量，否则会累积重复行。"""
        visual = _FakeVisualService()
        doc = _document()
        service, _ = _build_service([], visual, _FakeStorage())

        service._index_visual_vectors(doc, [])

        assert visual.deleted == [doc.id]

    def test_frame_download_failure_does_not_break_indexing(self):
        visual = _FakeVisualService()
        service, _ = _build_service([], visual, _FakeStorage(fail=True))

        service._index_visual_vectors(_document(), [SimpleNamespace(
            id=uuid4(), metadata_={"media_type": "video", "frame_url": "frames/f1.jpg"},
        )])

        assert visual.indexed == []

    def test_embedding_failure_skips_frame(self):
        """编码失败不得写入错误向量。"""
        visual = _FakeVisualService(embedding=[])
        service, _ = _build_service([], visual, _FakeStorage())

        service._index_visual_vectors(_document(), [SimpleNamespace(
            id=uuid4(), metadata_={"media_type": "video", "frame_url": "frames/f1.jpg"},
        )])

        assert visual.indexed == []

    def test_missing_visual_service_is_noop(self):
        """未注入视觉服务时不得报错（向后兼容）。"""
        service, _ = _build_service([], None, None)

        service._index_visual_vectors(_document(), [SimpleNamespace(
            id=uuid4(), metadata_={"media_type": "video", "frame_url": "frames/f1.jpg"},
        )])

    def test_parse_records_frames_in_parse_profile(self):
        """parse_profile 必须记录帧清单，供后续「改细节」定位与视觉向量后补。"""
        visual = _FakeVisualService()
        doc = _document()
        service, _ = _build_service([_frame_segment()], visual, _FakeStorage())
        captured = {}
        service._finalize_segments = (
            lambda document, segment_ids, parse_profile=None: captured.update(parse_profile)
        )

        service._build_media_document(doc)

        assert captured["tier1"]["video_frame_count"] == 1
        assert captured["frames"][0]["frame_url"] == "frames/f1.jpg"


class TestMediaExtractionReceivesOwnership:
    def test_extract_receives_account_and_document_id(self):
        """必须把 account_id/document_id 传下去，否则帧不会被留存（frame_url 恒空），
        视觉向量链路会静默失效。
        """
        visual = _FakeVisualService()
        doc = _document()
        service, extractor = _build_service([_frame_segment()], visual, _FakeStorage())

        service._build_media_document(doc)

        call = extractor.calls[0]
        assert call["account_id"] == doc.owner_account_id
        assert call["document_id"] == doc.id
