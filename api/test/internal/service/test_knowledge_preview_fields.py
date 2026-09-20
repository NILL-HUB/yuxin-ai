"""知识库文档/分段预览字段注入单测（frame_url 缩略图 / playback_url 播放直链 / 时间线元数据）。"""
from types import SimpleNamespace
from uuid import uuid4

from internal.service.knowledge_base_service import KnowledgeBaseService


class _ChainStub:
    """支持 filter/order_by/distinct/all 链式调用的查询桩。"""

    def __init__(self, rows=None):
        self._rows = [] if rows is None else rows

    def filter(self, *_a, **_k):
        return self

    def order_by(self, *_a, **_k):
        return self

    def distinct(self, *_a, **_k):
        return self

    def all(self):
        return self._rows


class _SessionStub:
    def __init__(self, queries=None):
        self._queries = list(queries or [])

    def query(self, *_a, **_k):
        if self._queries:
            return self._queries.pop(0)
        return _ChainStub()


class _CosStub:
    def get_file_url(self, key):
        return f"https://cos/{key}"


def _new_service(session=None, cos=None):
    service = KnowledgeBaseService(
        db=SimpleNamespace(session=session or _SessionStub()),
        retrieval_service=SimpleNamespace(),
        icon_generator_service=SimpleNamespace(),
    )
    service._get_cos_service = lambda: cos or _CosStub()
    return service


def _doc(**overrides):
    base = dict(id=uuid4(), name="clip.mp4", media_type="video", upload_file_id=uuid4())
    base.update(overrides)
    return SimpleNamespace(**base)


def test_enrich_documents_injects_frame_and_playback_urls():
    """视频文档：frame_url 来自首个带帧的分段（签名后），playback_url 来自 upload_file.key（签名后）。"""
    video_doc = _doc()
    frame_query = _ChainStub([(video_doc.id, "2026/09/13/frame-1.jpg")])
    upload_query = _ChainStub(
        [SimpleNamespace(id=video_doc.upload_file_id, key="2026/09/13/out.mp4")]
    )
    service = _new_service(_SessionStub([frame_query, upload_query]))

    service._enrich_document_previews([video_doc])

    assert getattr(video_doc, "frame_url") == "https://cos/2026/09/13/frame-1.jpg"
    assert getattr(video_doc, "playback_url") == "https://cos/2026/09/13/out.mp4"


def test_enrich_documents_leaves_empty_when_no_frame_or_not_video():
    """无帧分段 / 非视频文档：frame_url 与 playback_url 均为空串，不抛错。"""
    video_doc = _doc()
    image_doc = _doc(media_type="image", upload_file_id=None)
    service = _new_service(
        _SessionStub([_ChainStub(), _ChainStub()]),  # 帧查询空 + 上传文件查询空
    )

    service._enrich_document_previews([video_doc, image_doc])

    assert getattr(video_doc, "frame_url") == ""
    assert getattr(image_doc, "frame_url") == ""
    assert getattr(video_doc, "playback_url") == ""
    assert getattr(image_doc, "playback_url") == ""


def test_enrich_documents_noop_for_empty_list():
    """空列表直接返回，不发起任何查询。"""
    service = _new_service(_SessionStub([]))
    service._enrich_document_previews([])


def test_enrich_segments_exposes_timeline_metadata():
    """时间线段落：frame_url 签名后注入，start/end/source/speech_text 从 metadata 透出。"""
    segment = SimpleNamespace(
        id=uuid4(),
        metadata_={
            "source": "vision_timeline",
            "start_sec": 3.2,
            "end_sec": 8.7,
            "frame_url": "2026/09/13/rep.jpg",
            "speech_text": "第一句台词。",
        },
    )
    service = _new_service(_SessionStub([]))

    service._enrich_segment_previews([segment])

    assert getattr(segment, "frame_url") == "https://cos/2026/09/13/rep.jpg"
    assert getattr(segment, "start_sec") == 3.2
    assert getattr(segment, "end_sec") == 8.7
    assert getattr(segment, "source") == "vision_timeline"
    assert getattr(segment, "speech_text") == "第一句台词。"


def test_enrich_segments_defaults_when_metadata_missing():
    """无 metadata 的分段：所有预览字段回退默认值，不抛错。"""
    segment = SimpleNamespace(id=uuid4(), metadata_={})
    service = _new_service(_SessionStub([]))

    service._enrich_segment_previews([segment])

    assert getattr(segment, "frame_url") == ""
    assert getattr(segment, "start_sec") == 0.0
    assert getattr(segment, "end_sec") == 0.0
    assert getattr(segment, "source") == ""
    assert getattr(segment, "speech_text") == ""


def test_documents_schema_dumps_preview_fields():
    """文档列表 schema 应透出 frame_url / playback_url。"""
    from datetime import datetime, timezone

    from internal.schema.knowledge_base_schema import GetKnowledgeDocumentsWithPageResp

    doc = SimpleNamespace(
        id=uuid4(),
        name="clip.mp4",
        media_type="video",
        content_type="video/mp4",
        parse_profile={},
        character_count=0,
        segment_count=1,
        status="completed",
        error="",
        updated_at=datetime.now(timezone.utc),
        created_at=datetime.now(timezone.utc),
        frame_url="https://cos/rep.jpg",
        playback_url="https://cos/out.mp4",
    )

    payload = GetKnowledgeDocumentsWithPageResp().dump(doc)

    assert payload["frame_url"] == "https://cos/rep.jpg"
    assert payload["playback_url"] == "https://cos/out.mp4"
