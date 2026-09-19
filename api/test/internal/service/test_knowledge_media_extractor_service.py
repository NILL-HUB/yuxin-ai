from types import SimpleNamespace
from uuid import uuid4

import pytest

from internal.core.vision.vision_invoke import ExtractedFrame
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


def _write_frames(tmp_path, count: int) -> list[ExtractedFrame]:
    """写 count 个真实帧文件；抽帧现返回帧文件路径与时间偏移。"""
    frames = []
    for index in range(1, count + 1):
        path = tmp_path / f"frame_{index:03d}.jpg"
        path.write_bytes(b"\xff\xd8\xff\xe0frame")
        frames.append(ExtractedFrame(path=str(path), time_offset=float(index - 1)))
    return frames


def _raise_no_audio(_video_path):
    """音轨分支桩：默认视为视频无音轨，让用例聚焦帧逻辑。"""
    raise RuntimeError("no audio stream")


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
    def __init__(self, text="这是一段会议录音的转写内容。", error=None, segments=None):
        self.text = text
        self.error = error
        self.segments = segments if segments is not None else []
        self.received_filename = None
        self.timestamp_calls = 0
        self.plain_calls = 0

    def audio_to_text(self, audio, language="", provider="", model=""):
        self.plain_calls += 1
        self.received_filename = getattr(audio, "filename", None)
        if self.error:
            raise self.error
        return self.text

    def audio_to_text_with_segments(self, audio, language="", provider="", model=""):
        self.timestamp_calls += 1
        self.received_filename = getattr(audio, "filename", None)
        if self.error:
            raise self.error
        return self.text, self.segments


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


def test_audio_extraction_persists_asr_timeline():
    """时间轴必须落进 metadata：它是后续「自动加字幕」的唯一时间码来源。"""
    cues = [{"start": 0.04, "end": 3.48, "text": "今天天气很好。"}]
    service = KnowledgeMediaExtractorService(
        db=SimpleNamespace(),
        cos_service=_FakeStorage(b"audio-bytes"),
        audio_service=_FakeAudioService(segments=cues),
    )
    upload = SimpleNamespace(
        id=uuid4(), key=f"2026/09/13/{uuid4()}.mp3", name="meeting.mp3",
        extension="mp3", mime_type="audio/mpeg",
    )

    segments = service.extract(_document("audio"), upload)

    assert segments[0].metadata["transcript_segments"] == cues


def test_audio_extraction_omits_timeline_key_when_absent():
    """无可信时间轴时不应写入空列表（避免下游误判为「已留存」）。"""
    service = KnowledgeMediaExtractorService(
        db=SimpleNamespace(),
        cos_service=_FakeStorage(b"audio-bytes"),
        audio_service=_FakeAudioService(segments=[]),
    )
    upload = SimpleNamespace(
        id=uuid4(), key=f"2026/09/13/{uuid4()}.mp3", name="a.mp3",
        extension="mp3", mime_type="audio/mpeg",
    )

    segments = service.extract(_document("audio"), upload)

    assert "transcript_segments" not in segments[0].metadata


def test_asr_falls_back_to_plain_text_when_timestamp_api_fails():
    """带时间轴接口不可用时不能丢掉转写结果（降级为纯文本，而非整段失败）。"""

    class _FlakyAsr:
        def __init__(self):
            self.plain_calls = 0

        def audio_to_text_with_segments(self, audio, language="", provider="", model=""):
            raise RuntimeError("verbose_json unsupported")

        def audio_to_text(self, audio, language="", provider="", model=""):
            self.plain_calls += 1
            return "降级文本"

    asr = _FlakyAsr()
    service = KnowledgeMediaExtractorService(
        db=SimpleNamespace(),
        cos_service=_FakeStorage(b"audio-bytes"),
        audio_service=asr,
    )
    upload = SimpleNamespace(
        id=uuid4(), key=f"2026/09/13/{uuid4()}.mp3", name="a.mp3",
        extension="mp3", mime_type="audio/mpeg",
    )

    segments = service.extract(_document("audio"), upload)

    assert segments[0].content == "降级文本"
    assert asr.plain_calls == 1
    assert "transcript_segments" not in segments[0].metadata


def test_asr_does_not_rerun_plain_call_when_timeline_succeeds():
    """时间轴路径成功时不得重复调用一次纯文本接口（会双倍消耗 ASR）。"""
    audio_service = _FakeAudioService(segments=[{"start": 0, "end": 1, "text": "x"}])
    service = KnowledgeMediaExtractorService(
        db=SimpleNamespace(),
        cos_service=_FakeStorage(b"audio-bytes"),
        audio_service=audio_service,
    )
    upload = SimpleNamespace(
        id=uuid4(), key=f"2026/09/13/{uuid4()}.mp3", name="a.mp3",
        extension="mp3", mime_type="audio/mpeg",
    )

    service.extract(_document("audio"), upload)

    assert audio_service.timestamp_calls == 1
    assert audio_service.plain_calls == 0


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


def test_video_extraction_returns_segment_per_frame(tmp_path):
    service = KnowledgeMediaExtractorService(
        db=SimpleNamespace(),
        cos_service=_FakeStorage(b"video-bytes"),
        audio_service=SimpleNamespace(),
    )
    frames = _write_frames(tmp_path, 2)
    service._extract_frames_with_offsets = lambda path, out_dir: frames
    service._extract_audio_track = _raise_no_audio
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
    assert segments[0].content.startswith("画面描述-data:image/jpeg;base64,")
    assert segments[0].metadata["media_type"] == "video"
    assert segments[0].metadata["scene_index"] == 1
    assert segments[0].metadata["frame_count"] == 2
    assert segments[0].metadata["frame_url"] == ""
    assert segments[1].metadata["scene_index"] == 2
    assert len(seen_prompts) == 2


def test_video_extraction_skips_frames_that_fail_analysis(tmp_path):
    service = KnowledgeMediaExtractorService(
        db=SimpleNamespace(),
        cos_service=_FakeStorage(b"video-bytes"),
        audio_service=SimpleNamespace(),
    )
    frames = _write_frames(tmp_path, 2)
    service._extract_frames_with_offsets = lambda path, out_dir: frames
    service._extract_audio_track = _raise_no_audio
    calls = {"count": 0}

    def _vision(data_uri, prompt):
        calls["count"] += 1
        if calls["count"] == 2:
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
    service._extract_frames_with_offsets = lambda path, out_dir: []
    service._extract_audio_track = _raise_no_audio
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


def test_video_extraction_raises_when_all_descriptions_blank(tmp_path):
    """帧非空但所有帧描述均为空白时，应抛错而不是产出空片段。"""
    service = KnowledgeMediaExtractorService(
        db=SimpleNamespace(),
        cos_service=_FakeStorage(b"video-bytes"),
        audio_service=SimpleNamespace(),
    )
    service._extract_frames_with_offsets = lambda path, out_dir: _write_frames(tmp_path, 2)
    service._extract_audio_track = _raise_no_audio
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
