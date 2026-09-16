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


class TestReparseReleasesStaleFrames:
    """重解析必须清理上一轮的帧文件记录与对象，否则每轮都留下永不释放的孤儿。

    可达入口：`ScopedKnowledgeService.update_text_document_for_admin` 复用同一
    document.id 重建索引；Celery `build_document_task` 还会 `max_retries=2` 重试，
    故不清理会持续放大（帧已计入配额，等于持续泄漏）。
    """

    def test_reparse_deletes_stale_frame_records(self):
        """旧帧记录（按上一轮 segment 的 frame_url 关联）必须在新一轮解析前被删除。"""
        from internal.model import UploadFile

        deleted_records = []
        deleted_objects = []
        released = []

        old_row = UploadFile(
            account_id=uuid4(), name="old1.jpg", key="frames/old1.jpg", size=10,
            extension="jpg", mime_type="image/jpeg", hash="h", storage_backend="local",
        )

        class _AnyQuery:
            def filter(self, *_a, **_kw):
                return self

            def filter_by(self, **_kw):
                return self

            def all(self):
                return [old_row]

            def one_or_none(self):
                return None

            def delete(self, **_kw):
                deleted_records.append(True)
                return 1

        service, _ = _build_service([], _FakeVisualService(), _FakeStorage())
        service.db = SimpleNamespace(
            session=SimpleNamespace(query=lambda model, *a, **k: _AnyQuery()),
            auto_commit=lambda: _auto_commit(),
        )
        service.update = lambda instance, **kwargs: instance
        service.create = lambda model, **kwargs: SimpleNamespace(id=uuid4(), **kwargs)
        service.delete = lambda instance: deleted_records.append(True)
        service._delete_frame_object = lambda key, backend: deleted_objects.append(key)
        service._release_frame_quota = lambda account_id, size: released.append((account_id, size))

        service._release_stale_frames(
            _document(),
            [SimpleNamespace(metadata_={"frame_url": "frames/old1.jpg"})],
        )

        assert deleted_objects == ["frames/old1.jpg"], "旧帧底层对象必须删除"
        assert released == [(old_row.account_id, 10)], "旧帧配额必须释放"
        assert deleted_records, "旧帧 UploadFile 记录必须删除"


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


class TestFrameManifestCarriesTimeOffset:
    """parse_profile.frames 必须带 time_offset，供「改细节」定位与 L2 扩抽。

    缺该字段时帧清单只能排序、无法把命中的帧换算成视频时间轴位置，
    即「改细节」无从定位到具体片段。
    """

    def test_frame_segment_includes_time_offset(self):
        segment = SimpleNamespace(
            id=uuid4(),
            metadata_={
                "media_type": "video",
                "frame_url": "2026/09/16/frame_001.jpg",
                "scene_index": 1,
                "time_offset": 7.5,
            },
        )

        frame = KnowledgeIndexingService._segment_frame(segment)

        assert frame["time_offset"] == 7.5

    def test_frame_segment_defaults_time_offset_to_zero(self):
        """旧数据无 time_offset 时不得抛错，退化为 0.0。"""
        segment = SimpleNamespace(
            id=uuid4(),
            metadata_={"media_type": "video", "frame_url": "frames/f1.jpg", "scene_index": 1},
        )

        assert KnowledgeIndexingService._segment_frame(segment)["time_offset"] == 0.0

    def test_frame_segment_returns_none_without_frame_url(self):
        segment = SimpleNamespace(
            id=uuid4(),
            metadata_={"media_type": "video", "frame_url": "", "time_offset": 1.0},
        )

        assert KnowledgeIndexingService._segment_frame(segment) is None

    def test_parse_profile_manifest_carries_time_offset(self):
        visual = _FakeVisualService()
        doc = _document()
        segment = _frame_segment()
        segment.metadata = {**segment.metadata, "time_offset": 12.5}
        service, _ = _build_service([segment], visual, _FakeStorage())
        captured = {}
        service._finalize_segments = (
            lambda document, segment_ids, parse_profile=None: captured.update(parse_profile)
        )

        service._build_media_document(doc)

        assert captured["frames"][0]["time_offset"] == 12.5
