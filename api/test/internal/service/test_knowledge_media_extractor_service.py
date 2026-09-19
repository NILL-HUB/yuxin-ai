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


def test_video_extraction_scene_a_batches_into_timeline_segments(tmp_path):
    """无音轨视频走场景 A：一批锚点一次批喂，产出 timeline 段而非逐帧段。"""
    service = KnowledgeMediaExtractorService(
        db=SimpleNamespace(),
        cos_service=_FakeStorage(b"video-bytes"),
        audio_service=SimpleNamespace(),
    )
    frames = _write_frames(tmp_path, 12)
    service._extract_frames_with_offsets = lambda path, out_dir: frames
    service._transcribe_video_track = lambda path, upload: ("", [])
    calls = []

    def _batch(uris, prompt):
        calls.append(len(uris))
        return '[{"anchor_index": 0, "description": "块0"}, {"anchor_index": 1, "description": "块1"}]'

    service._invoke_vision_batch = _batch  # type: ignore[assignment]
    upload = SimpleNamespace(
        id=uuid4(), key=f"2026/09/13/{uuid4()}.mp4", name="promo.mp4",
        extension="mp4", mime_type="video/mp4",
    )

    segments = service.extract(_document("video"), upload)

    timeline = [s for s in segments if s.metadata.get("source") == "vision_timeline"]
    assert len(timeline) == 2
    assert calls == [13]  # 12 帧 + 块间重叠 1 帧，全部一次批喂
    assert timeline[0].metadata["anchor_type"] == "time_slot"
    assert timeline[0].metadata["start_sec"] == 0.0
    assert timeline[0].metadata["end_sec"] == 9.0
    assert timeline[1].metadata["start_sec"] == 9.0  # 重叠帧归属下一块
    assert timeline[1].metadata["end_sec"] == 11.0
    assert timeline[0].content == "块0"


def test_video_extraction_falls_back_to_per_frame_after_batch_failures(tmp_path):
    """批喂连续失败（含重试）→ 降级为批内逐帧独立调用，仍产出片段。"""
    service = KnowledgeMediaExtractorService(
        db=SimpleNamespace(),
        cos_service=_FakeStorage(b"video-bytes"),
        audio_service=SimpleNamespace(),
    )
    frames = _write_frames(tmp_path, 3)
    service._extract_frames_with_offsets = lambda path, out_dir: frames
    service._transcribe_video_track = lambda path, upload: ("", [])
    batch_calls = {"n": 0}

    def _batch(uris, prompt):
        batch_calls["n"] += 1
        raise RuntimeError("vision down")

    service._invoke_vision_batch = _batch  # type: ignore[assignment]
    single_calls = {"n": 0}

    def _single(uri, prompt):
        single_calls["n"] += 1
        return "降级描述"

    service._invoke_vision = _single  # type: ignore[assignment]
    upload = SimpleNamespace(
        id=uuid4(), key=f"2026/09/13/{uuid4()}.mp4", name="clip.mp4",
        extension="mp4", mime_type="video/mp4",
    )

    segments = service.extract(_document("video"), upload)

    assert batch_calls["n"] == 2  # 初次 + 重试 1 次
    assert single_calls["n"] == 3
    assert len(segments) == 3
    assert segments[0].metadata["time_offset"] == 0.0  # 降级段保留逐帧定位坐标


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


def test_video_extraction_scene_a_all_blank_descriptions_raise(tmp_path):
    """场景 A 批喂返回全空描述时应抛错而不是产出空片段。"""
    service = KnowledgeMediaExtractorService(
        db=SimpleNamespace(),
        cos_service=_FakeStorage(b"video-bytes"),
        audio_service=SimpleNamespace(),
    )
    service._extract_frames_with_offsets = lambda path, out_dir: _write_frames(tmp_path, 3)
    service._transcribe_video_track = lambda path, upload: ("", [])
    service._invoke_vision_batch = lambda uris, prompt: (  # type: ignore[assignment]
        '[{"anchor_index": 0, "description": "  "}]'
    )
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


def test_video_extraction_scene_b_injects_speech_and_window(tmp_path):
    """有 ASR cues 走场景 B：锚点窗口 = cue 区间，speech_text 注入。"""
    cues = [
        {"start": 0.0, "end": 5.0, "text": "第一句台词。"},
        {"start": 5.5, "end": 9.0, "text": "第二句台词。"},
    ]
    service = KnowledgeMediaExtractorService(
        db=SimpleNamespace(),
        cos_service=_FakeStorage(b"video-bytes"),
        audio_service=SimpleNamespace(),
    )
    service._extract_frames_with_offsets = lambda path, out_dir: _write_frames(tmp_path, 6)
    service._transcribe_video_track = lambda path, upload: ("两句台词", cues)
    service._invoke_vision_batch = lambda uris, prompt: (  # type: ignore[assignment]
        '[{"anchor_index": 0, "description": "画面A"}, {"anchor_index": 1, "description": "画面B"}]'
    )
    upload = SimpleNamespace(
        id=uuid4(), key=f"2026/09/13/{uuid4()}.mp4", name="talk.mp4",
        extension="mp4", mime_type="video/mp4",
    )

    segments = service.extract(_document("video"), upload)

    timeline = [s for s in segments if s.metadata.get("source") == "vision_timeline"]
    assert len(timeline) == 2
    assert timeline[0].metadata["anchor_type"] == "speech_sentence"
    assert timeline[0].metadata["start_sec"] == 0.0
    assert timeline[0].metadata["end_sec"] == 5.0
    assert timeline[0].metadata["speech_text"] == "第一句台词。"
    assert timeline[0].metadata["anchor_text"] == "第一句台词。"
    assert timeline[0].content == "画面A"
    assert timeline[1].metadata["speech_text"] == "第二句台词。"


def test_video_extraction_batch_retries_once_then_succeeds(tmp_path):
    """批喂首次失败重试一次成功，不降级。"""
    service = KnowledgeMediaExtractorService(
        db=SimpleNamespace(),
        cos_service=_FakeStorage(b"video-bytes"),
        audio_service=SimpleNamespace(),
    )
    service._extract_frames_with_offsets = lambda path, out_dir: _write_frames(tmp_path, 2)
    service._transcribe_video_track = lambda path, upload: ("", [])
    calls = {"n": 0}

    def _batch(uris, prompt):
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("transient")
        return '[{"anchor_index": 0, "description": "重试成功"}]'

    service._invoke_vision_batch = _batch  # type: ignore[assignment]
    upload = SimpleNamespace(
        id=uuid4(), key=f"2026/09/13/{uuid4()}.mp4", name="r.mp4",
        extension="mp4", mime_type="video/mp4",
    )

    segments = service.extract(_document("video"), upload)

    assert calls["n"] == 2
    timeline = [s for s in segments if s.metadata.get("source") == "vision_timeline"]
    assert timeline[0].content == "重试成功"


def test_video_extraction_scene_b_blank_description_falls_back_to_speech(tmp_path):
    """场景 B 模型未给描述时保留仅台词段落（可检索）。"""
    cues = [{"start": 0.0, "end": 3.0, "text": "只有台词。"}]
    service = KnowledgeMediaExtractorService(
        db=SimpleNamespace(),
        cos_service=_FakeStorage(b"video-bytes"),
        audio_service=SimpleNamespace(),
    )
    service._extract_frames_with_offsets = lambda path, out_dir: _write_frames(tmp_path, 2)
    service._transcribe_video_track = lambda path, upload: ("只有台词。", cues)
    service._invoke_vision_batch = lambda uris, prompt: (  # type: ignore[assignment]
        '[{"anchor_index": 0, "description": "  "}]'
    )
    upload = SimpleNamespace(
        id=uuid4(), key=f"2026/09/13/{uuid4()}.mp4", name="speech.mp4",
        extension="mp4", mime_type="video/mp4",
    )

    segments = service.extract(_document("video"), upload)

    timeline = [s for s in segments if s.metadata.get("source") == "vision_timeline"]
    assert len(timeline) == 1
    assert timeline[0].content == "只有台词。"
    assert timeline[0].metadata["speech_text"] == "只有台词。"


def test_video_extraction_scene_a_empty_description_skips_anchor(tmp_path):
    """场景 A 某锚点描述为空时跳过该条，其余照常产出。"""
    service = KnowledgeMediaExtractorService(
        db=SimpleNamespace(),
        cos_service=_FakeStorage(b"video-bytes"),
        audio_service=SimpleNamespace(),
    )
    service._extract_frames_with_offsets = lambda path, out_dir: _write_frames(tmp_path, 12)
    service._transcribe_video_track = lambda path, upload: ("", [])
    service._invoke_vision_batch = lambda uris, prompt: (  # type: ignore[assignment]
        '[{"anchor_index": 0, "description": "有效"}, {"anchor_index": 1, "description": "  "}]'
    )
    upload = SimpleNamespace(
        id=uuid4(), key=f"2026/09/13/{uuid4()}.mp4", name="mixed.mp4",
        extension="mp4", mime_type="video/mp4",
    )

    segments = service.extract(_document("video"), upload)

    timeline = [s for s in segments if s.metadata.get("source") == "vision_timeline"]
    assert len(timeline) == 1
    assert timeline[0].content == "有效"
