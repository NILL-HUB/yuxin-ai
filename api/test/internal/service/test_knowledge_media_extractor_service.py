from types import SimpleNamespace
from uuid import uuid4

import pytest

from internal.service.knowledge_media_extractor_service import (
    KnowledgeMediaExtractorService,
    MediaSegment,
)


class _FakeStorage:
    """把预置字节写入目标路径，模拟对象存储下载。"""

    def __init__(self, payload: bytes):
        self.payload = payload

    def download_file(self, key, target_path):
        with open(target_path, "wb") as fh:
            fh.write(self.payload)


def _new_service(payload=b"img-bytes", vision_text="一张产品截图"):
    service = KnowledgeMediaExtractorService(
        db=SimpleNamespace(),
        cos_service=_FakeStorage(payload),
        audio_service=SimpleNamespace(),
    )
    service._invoke_vision = lambda data_uri, prompt: vision_text  # type: ignore[assignment]
    return service


def _document(media_type: str):
    return SimpleNamespace(
        id=uuid4(),
        media_type=media_type,
        knowledge_base_id=uuid4(),
        owner_account_id=uuid4(),
    )


def _upload_file(extension: str = "jpg"):
    return SimpleNamespace(
        id=uuid4(), key=f"2026/09/13/{uuid4()}.{extension}",
        name=f"sample.{extension}", extension=extension, mime_type="image/jpeg",
    )


def test_image_extraction_returns_single_segment_with_summary():
    service = _new_service(vision_text="画面为新品海报，含文字「限时五折」")

    segments = service.extract(_document("image"), _upload_file("jpg"))

    assert len(segments) == 1
    assert isinstance(segments[0], MediaSegment)
    assert "限时五折" in segments[0].content
    assert segments[0].metadata["media_type"] == "image"
    assert segments[0].metadata["vision_summary"] == segments[0].content


def test_document_media_type_returns_no_segments():
    service = _new_service()
    assert service.extract(_document("document"), _upload_file("pdf")) == []


def test_unknown_media_type_returns_no_segments():
    service = _new_service()
    assert service.extract(_document("unknown"), _upload_file("bin")) == []


def test_image_extraction_propagates_vision_failure():
    service = _new_service()
    service._invoke_vision = lambda data_uri, prompt: (_ for _ in ()).throw(RuntimeError("no model"))
    with pytest.raises(RuntimeError):
        service.extract(_document("image"), _upload_file("png"))


class _FakeAudioService:
    def __init__(self, text="这是一段会议录音的转写内容。", error=None):
        self.text = text
        self.error = error
        self.received_filename = None

    def audio_to_text(self, audio, language="", provider="", model=""):
        self.received_filename = getattr(audio, "filename", None)
        if self.error:
            raise self.error
        return self.text


def test_audio_extraction_returns_transcript_segment():
    audio_service = _FakeAudioService()
    service = KnowledgeMediaExtractorService(
        db=SimpleNamespace(),
        cos_service=_FakeStorage(b"audio-bytes"),
        audio_service=audio_service,
    )
    upload = SimpleNamespace(
        id=uuid4(), key=f"2026/09/13/{uuid4()}.mp3", name="meeting.mp3",
        extension="mp3", mime_type="audio/mpeg",
    )

    segments = service.extract(_document("audio"), upload)

    assert len(segments) == 1
    assert "会议录音" in segments[0].content
    assert segments[0].metadata["media_type"] == "audio"
    assert audio_service.received_filename == "meeting.mp3"


def test_audio_extraction_raises_when_asr_unavailable():
    service = KnowledgeMediaExtractorService(
        db=SimpleNamespace(),
        cos_service=_FakeStorage(b"audio-bytes"),
        audio_service=_FakeAudioService(error=RuntimeError("asr down")),
    )
    upload = SimpleNamespace(
        id=uuid4(), key=f"2026/09/13/{uuid4()}.wav", name="a.wav",
        extension="wav", mime_type="audio/wav",
    )

    with pytest.raises(RuntimeError):
        service.extract(_document("audio"), upload)


def test_audio_extraction_returns_empty_when_transcript_blank():
    service = KnowledgeMediaExtractorService(
        db=SimpleNamespace(),
        cos_service=_FakeStorage(b"audio-bytes"),
        audio_service=_FakeAudioService(text="   "),
    )
    upload = SimpleNamespace(
        id=uuid4(), key=f"2026/09/13/{uuid4()}.m4a", name="silent.m4a",
        extension="m4a", mime_type="audio/mp4",
    )

    assert service.extract(_document("audio"), upload) == []


def test_video_extraction_returns_segment_per_frame():
    service = KnowledgeMediaExtractorService(
        db=SimpleNamespace(),
        cos_service=_FakeStorage(b"video-bytes"),
        audio_service=SimpleNamespace(),
    )
    service._extract_frames = lambda path: ["data:frame-1", "data:frame-2"]
    seen_prompts = []

    def _vision(data_uri, prompt):
        seen_prompts.append((data_uri, prompt))
        return f"画面描述-{data_uri}"

    service._invoke_vision = _vision

    upload = SimpleNamespace(
        id=uuid4(), key=f"2026/09/13/{uuid4()}.mp4", name="promo.mp4",
        extension="mp4", mime_type="video/mp4",
    )

    segments = service.extract(_document("video"), upload)

    assert len(segments) == 2
    assert segments[0].content == "画面描述-data:frame-1"
    assert segments[0].metadata["media_type"] == "video"
    assert segments[0].metadata["scene_index"] == 1
    assert segments[0].metadata["frame_count"] == 2
    assert segments[1].metadata["scene_index"] == 2
    assert len(seen_prompts) == 2


def test_video_extraction_skips_frames_that_fail_analysis():
    service = KnowledgeMediaExtractorService(
        db=SimpleNamespace(),
        cos_service=_FakeStorage(b"video-bytes"),
        audio_service=SimpleNamespace(),
    )
    service._extract_frames = lambda path: ["data:ok", "data:bad"]

    def _vision(data_uri, prompt):
        if data_uri == "data:bad":
            raise RuntimeError("vision failed")
        return "可用画面描述"

    service._invoke_vision = _vision
    upload = SimpleNamespace(
        id=uuid4(), key=f"2026/09/13/{uuid4()}.mov", name="clip.mov",
        extension="mov", mime_type="video/quicktime",
    )

    segments = service.extract(_document("video"), upload)

    assert len(segments) == 1
    assert segments[0].content == "可用画面描述"
    assert segments[0].metadata["scene_index"] == 1


def test_video_extraction_raises_when_no_frames_extracted():
    service = KnowledgeMediaExtractorService(
        db=SimpleNamespace(),
        cos_service=_FakeStorage(b"video-bytes"),
        audio_service=SimpleNamespace(),
    )
    service._extract_frames = lambda path: []
    upload = SimpleNamespace(
        id=uuid4(), key=f"2026/09/13/{uuid4()}.mkv", name="broken.mkv",
        extension="mkv", mime_type="video/x-matroska",
    )

    with pytest.raises(RuntimeError):
        service.extract(_document("video"), upload)


def test_image_extraction_returns_empty_when_summary_blank():
    """视觉模型返回空白描述时不应产出空内容片段。"""
    service = _new_service(vision_text="   ")
    assert service.extract(_document("image"), _upload_file("jpg")) == []


def test_video_extraction_raises_when_all_descriptions_blank():
    """帧非空但所有帧描述均为空白时，应抛错而不是产出空片段。"""
    service = KnowledgeMediaExtractorService(
        db=SimpleNamespace(),
        cos_service=_FakeStorage(b"video-bytes"),
        audio_service=SimpleNamespace(),
    )
    service._extract_frames = lambda path: ["data:a", "data:b"]
    service._invoke_vision = lambda data_uri, prompt: "   "
    upload = SimpleNamespace(
        id=uuid4(), key=f"2026/09/13/{uuid4()}.mp4", name="blank.mp4",
        extension="mp4", mime_type="video/mp4",
    )

    with pytest.raises(RuntimeError):
        service.extract(_document("video"), upload)


def test_audio_extraction_uses_fallback_filename_when_name_absent():
    """name 与 key 均缺失时 filename 应有兜底，不应为空串。"""
    audio_service = _FakeAudioService()
    service = KnowledgeMediaExtractorService(
        db=SimpleNamespace(),
        cos_service=_FakeStorage(b"audio-bytes"),
        audio_service=audio_service,
    )
    upload = SimpleNamespace(
        id=uuid4(), key="", name="", extension="mp3", mime_type="audio/mpeg",
    )

    service.extract(_document("audio"), upload)

    assert audio_service.received_filename == "material.audio"
