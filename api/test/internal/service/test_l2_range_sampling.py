"""L2 窗口化密抽测试。

规格 §5.4：L2 不重扫全片——由 L1 命中帧的 time_offset 推导窗口，
只在窗口内按 0.5 秒/帧密抽。本测试锁定该行为与「窗口内新帧落库」。
"""
from contextlib import contextmanager
from types import SimpleNamespace
from uuid import uuid4

from internal.core.vision.vision_invoke import ExtractedFrame
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

    def all(self):
        return self._all

    def one_or_none(self):
        return self._one_or_none


class _SessionStub:
    """按 model 返回桩查询：KnowledgeSegment 恒返回给定片段，其余返回空。

    `_enhance_l2` 与 `_next_segment_position` 都会查 KnowledgeSegment，
    故这里必须对同一批片段**可重复读取**（不能像队列那样消费一次就空）。
    """

    def __init__(self, segments=None, upload_rows=None):
        self._segments = list(segments or [])
        self._upload_rows = list(upload_rows or [])

    def query(self, model, *_a, **_kw):
        name = getattr(model, "__name__", "")
        if name == "UploadFile":
            return _QueryStub(all_result=self._upload_rows)
        return _QueryStub(all_result=self._segments)


def _document(duration_sec=600.0):
    return SimpleNamespace(
        id=uuid4(),
        media_type="video",
        knowledge_base_id=uuid4(),
        owner_account_id=uuid4(),
        upload_file_id=uuid4(),
        parse_profile={"tier1": {"status": "completed"}},
        knowledge_base=SimpleNamespace(id=uuid4(), embedding_model_id=uuid4()),
    )


def _l1_frame_segment(frame_url, time_offset, scene_index=1):
    return SimpleNamespace(
        id=uuid4(),
        content="L1 粗描述",
        position=scene_index,
        metadata_={
            "media_type": "video",
            "frame_url": frame_url,
            "scene_index": scene_index,
            "frame_count": 6,
            "time_offset": time_offset,
        },
    )


def _build_service(segments, upload_rows=None):
    created = []

    service = KnowledgeIndexingService(
        db=SimpleNamespace(
            session=_SessionStub(segments=segments, upload_rows=upload_rows),
            auto_commit=lambda: _auto_commit(),
        ),
        file_extractor=SimpleNamespace(),
        embeddings_service=SimpleNamespace(calculate_token_count=lambda text: len(text)),
        jieba_service=SimpleNamespace(extract_keywords=lambda text, n: ["kw"]),
        knowledge_vector_service=SimpleNamespace(
            index_segment=lambda *a, **kw: "id", remove_segment=lambda *a: None
        ),
        media_extractor=SimpleNamespace(
            _extract_frames_in_range=lambda video_path, out_dir, *, start_sec, duration_sec: []
        ),
        visual_embedding_service=None,
        cos_service=SimpleNamespace(download_file=lambda key, path: None),
    )
    service.update = lambda instance, **kwargs: instance
    service.create = lambda model, **kwargs: created.append(kwargs) or SimpleNamespace(
        id=uuid4(), **kwargs
    )
    service.delete = lambda instance: None
    service._resolve_document_duration = lambda document: 600.0
    service._delete_frame_object = lambda key, backend: None
    service._release_frame_quota = lambda account_id, size: None
    return service, created


class TestL2WindowSampling:
    def test_uses_l1_offsets_to_derive_windows(self):
        """命中帧的 time_offset 决定窗口位置——窗口内才抽帧。"""
        calls = []

        def _extract(video_path, out_dir, *, start_sec, duration_sec):
            calls.append((start_sec, duration_sec))
            return [ExtractedFrame(path="/tmp/f1.jpg", time_offset=start_sec + 1.0)]

        service, _created = _build_service(
            [_l1_frame_segment("frames/l1.jpg", time_offset=100.0)]
        )
        service.media_extractor = SimpleNamespace(_extract_frames_in_range=_extract)
        service._download_document_video = lambda document: "/tmp/v.mp4"
        service._persist_window_frame = lambda frame, document: "frames/w1.jpg"
        service._invoke_l2_vision = lambda data_uri: "窗口内详述"
        service._load_frame_data_uri = lambda key: "data:image/jpeg;base64,AAA"

        service._enhance_l2(_document())

        assert len(calls) == 1
        start_sec, duration_sec = calls[0]
        assert start_sec == 90.0, "100s 命中扩窗 ±10s -> 起点 90s"
        assert duration_sec == 20.0

    def test_creates_segment_per_window_frame(self):
        """窗口内每帧都建新 Segment（带 time_offset），不与 L1 片段混淆。"""
        service, created = _build_service(
            [_l1_frame_segment("frames/l1.jpg", time_offset=100.0)]
        )
        service.media_extractor = SimpleNamespace(
            _extract_frames_in_range=lambda video_path, out_dir, *, start_sec, duration_sec: [
                ExtractedFrame(path="/tmp/f1.jpg", time_offset=91.0),
                ExtractedFrame(path="/tmp/f2.jpg", time_offset=91.5),
            ]
        )
        service._download_document_video = lambda document: "/tmp/v.mp4"
        service._persist_window_frame = lambda frame, document: "frames/w1.jpg"
        service._invoke_l2_vision = lambda data_uri: "窗口内详述"
        service._load_frame_data_uri = lambda key: "data:image/jpeg;base64,AAA"

        service._enhance_l2(_document())

        assert len(created) == 2
        assert created[0]["metadata_"]["tier2_window"] is True
        assert created[0]["metadata_"]["time_offset"] == 91.0
        assert created[0]["metadata_"]["scene_index"] == 1
        assert created[1]["metadata_"]["scene_index"] == 2

    def test_window_frames_are_indexed(self):
        """窗口帧必须同时写文本向量与视觉向量。

        只建 Segment 不索引，用户永远检索不到这些片段——L2 就白跑了。
        """
        indexed_text = []
        indexed_visual = []

        service, _created = _build_service(
            [_l1_frame_segment("frames/l1.jpg", time_offset=100.0)]
        )
        service.knowledge_vector_service = SimpleNamespace(
            index_segment=lambda segment, kb: indexed_text.append(segment.id),
            remove_segment=lambda *a: None,
        )
        service._index_visual_vectors = lambda document, segments: indexed_visual.extend(
            s.id for s in segments
        )
        service.media_extractor = SimpleNamespace(
            _extract_frames_in_range=lambda video_path, out_dir, *, start_sec, duration_sec: [
                ExtractedFrame(path="/tmp/f1.jpg", time_offset=91.0),
            ]
        )
        service._download_document_video = lambda document: "/tmp/v.mp4"
        service._persist_window_frame = lambda frame, document: "frames/w1.jpg"
        service._invoke_l2_vision = lambda data_uri: "窗口内详述"
        service._load_frame_data_uri = lambda key: "data:image/jpeg;base64,AAA"

        service._enhance_l2(_document())

        assert len(indexed_text) == 1, "文本向量必须写入（否则文本检索不到）"
        assert len(indexed_visual) == 1, "视觉向量必须写入（否则画面检索不到）"

    def test_window_segment_position_follows_existing(self):
        """L2 新片段序号接在既有片段之后，避免与 L1 片段 position 冲突。"""
        service, created = _build_service(
            [
                _l1_frame_segment("frames/l1.jpg", time_offset=100.0, scene_index=1),
                _l1_frame_segment("frames/l1b.jpg", time_offset=200.0, scene_index=2),
            ]
        )
        service.media_extractor = SimpleNamespace(
            _extract_frames_in_range=lambda video_path, out_dir, *, start_sec, duration_sec: [
                ExtractedFrame(path="/tmp/f1.jpg", time_offset=91.0),
            ]
        )
        service._download_document_video = lambda document: "/tmp/v.mp4"
        service._persist_window_frame = lambda frame, document: "frames/w1.jpg"
        service._invoke_l2_vision = lambda data_uri: "窗口内详述"
        service._load_frame_data_uri = lambda key: "data:image/jpeg;base64,AAA"

        service._enhance_l2(_document())

        assert created, "应有新片段"
        assert created[0]["position"] == 3, "既有 position 最大为 2，新片段应为 3"

    def test_no_hits_means_no_extraction(self):
        """没有 L1 命中帧就不抽任何帧（L2 是按需，不是全片重扫）。"""
        calls = []
        service, created = _build_service([])
        service.media_extractor = SimpleNamespace(
            _extract_frames_in_range=lambda *a, **kw: calls.append(1) or []
        )
        service._download_document_video = lambda document: "/tmp/v.mp4"

        result = service._enhance_l2(_document())

        assert calls == []
        assert created == []
        assert result["window_frames"] == 0

    def test_l2_frames_do_not_drive_window_derivation(self):
        """上一轮的 L2 窗口帧不得参与窗口推导（否则窗口逐轮自我放大）。"""
        calls = []

        def _extract(video_path, out_dir, *, start_sec, duration_sec):
            calls.append((start_sec, duration_sec))
            return [ExtractedFrame(path="/tmp/f1.jpg", time_offset=start_sec + 1.0)]

        l1 = _l1_frame_segment("frames/l1.jpg", time_offset=100.0, scene_index=1)
        l2 = _l1_frame_segment("frames/l2old.jpg", time_offset=500.0, scene_index=2)
        l2.metadata_["tier2_window"] = True

        service, _created = _build_service([l1, l2])
        service.media_extractor = SimpleNamespace(_extract_frames_in_range=_extract)
        service._download_document_video = lambda document: "/tmp/v.mp4"
        service._persist_window_frame = lambda frame, document: "frames/w1.jpg"
        service._invoke_l2_vision = lambda data_uri: "详述"
        service._load_frame_data_uri = lambda key: "data:image/jpeg;base64,AAA"

        service._enhance_l2(_document())

        assert len(calls) == 1, "只应由 L1 命中（100s）导出一个窗口，l2 的 500s 不参与"
        assert calls[0][0] == 90.0

    def test_previous_l2_windows_are_cleared(self):
        """重复触发 L2 时必须清掉上一轮窗口片段与帧（否则累积重复 + 帧泄漏）。"""
        deleted_records = []
        deleted_objects = []
        released = []

        l1 = _l1_frame_segment("frames/l1.jpg", time_offset=100.0, scene_index=1)
        old_l2 = _l1_frame_segment("frames/old_l2.jpg", time_offset=95.0, scene_index=2)
        old_l2.metadata_["tier2_window"] = True

        old_frame_row = SimpleNamespace(
            key="frames/old_l2.jpg", size=10, account_id=uuid4(), storage_backend="local"
        )

        service, _created = _build_service([l1, old_l2], upload_rows=[old_frame_row])
        service.media_extractor = SimpleNamespace(
            _extract_frames_in_range=lambda *a, **kw: []
        )
        service._download_document_video = lambda document: "/tmp/v.mp4"
        # 片段与帧记录都经 self.delete(...) 删除，统一记录被删对象
        service.delete = lambda instance: deleted_records.append(instance)
        service._delete_frame_object = lambda key, backend: deleted_objects.append(key)
        service._release_frame_quota = lambda account_id, size: released.append((account_id, size))

        service._enhance_l2(_document())

        assert any(s is old_l2 for s in deleted_records), "旧 L2 片段必须删除"
        assert any(row is old_frame_row for row in deleted_records), "旧 L2 帧记录必须删除"
        assert deleted_objects == ["frames/old_l2.jpg"], "旧 L2 帧对象必须删除"
        assert released == [(old_frame_row.account_id, 10)], "旧 L2 帧配额必须释放"

    def test_non_video_is_skipped(self):
        service, _created = _build_service([])
        document = _document()
        document.media_type = "image"

        result = service._enhance_l2(document)

        assert result["media_type"] == "image"

    def test_frame_vision_failure_does_not_abort_other_frames(self):
        """单帧视觉失败只跳过该帧，不影响同窗口其他帧。"""
        service, created = _build_service(
            [_l1_frame_segment("frames/l1.jpg", time_offset=100.0)]
        )
        service.media_extractor = SimpleNamespace(
            _extract_frames_in_range=lambda video_path, out_dir, *, start_sec, duration_sec: [
                ExtractedFrame(path="/tmp/f1.jpg", time_offset=91.0),
                ExtractedFrame(path="/tmp/f2.jpg", time_offset=91.5),
            ]
        )
        service._download_document_video = lambda document: "/tmp/v.mp4"
        service._persist_window_frame = lambda frame, document: "frames/w1.jpg"
        service._load_frame_data_uri = lambda key: "data:image/jpeg;base64,AAA"

        def _vision(data_uri):
            if data_uri.endswith("AAA"):
                raise RuntimeError("vision down")
            return "ok"

        service._invoke_l2_vision = _vision

        service._enhance_l2(_document())

        assert created == []

    def test_window_frame_without_persist_is_skipped(self):
        """留存失败（key 为空）时不建 Segment——否则 frame_url 空会让视觉索引失效。"""
        service, created = _build_service(
            [_l1_frame_segment("frames/l1.jpg", time_offset=100.0)]
        )
        service.media_extractor = SimpleNamespace(
            _extract_frames_in_range=lambda video_path, out_dir, *, start_sec, duration_sec: [
                ExtractedFrame(path="/tmp/f1.jpg", time_offset=91.0),
            ]
        )
        service._download_document_video = lambda document: "/tmp/v.mp4"
        service._persist_window_frame = lambda frame, document: ""
        service._invoke_l2_vision = lambda data_uri: "详述"

        service._enhance_l2(_document())

        assert created == []
