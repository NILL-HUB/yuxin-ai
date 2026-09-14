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


def test_video_extraction_not_implemented_yet():
    service = _new_service()
    with pytest.raises(NotImplementedError):
        service.extract(_document("video"), _upload_file("mp4"))


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
