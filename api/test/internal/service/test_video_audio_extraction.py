"""视频音轨 ASR 抽取测试。

覆盖三件事：
1. `extract_video_audio` 生成的 ffmpeg 命令必须含 ASR 友好参数（`-vn` / `-ac 1` / `-ar 16000`）；
2. `_extract_video` 在音轨转写成功时把转写片段排在逐帧描述之前；
3. 音轨抽取/转写失败只降级告警，且音轨临时文件必须被清理。
"""
import os
import subprocess
from types import SimpleNamespace
from uuid import uuid4

import pytest

from internal.core.vision import vision_invoke
from internal.core.vision.vision_invoke import ExtractedFrame
from internal.service.knowledge_media_extractor_service import KnowledgeMediaExtractorService


class _FakeStorage:
    """把预置字节写入目标路径，模拟对象存储下载。"""

    def __init__(self, payload: bytes = b"video-bytes"):
        self._payload = payload

    def download_file(self, key, target_path):
        with open(target_path, "wb") as fh:
            fh.write(self._payload)


class _FakeAudioService:
    """ASR 桩：记录收到的 FileStorage，便于断言包装是否发生。"""

    def __init__(self, text: str = "视频里说的话", error: Exception | None = None):
        self.text = text
        self.error = error
        self.received = None

    def audio_to_text(self, audio, **_kwargs):
        self.received = audio
        if self.error is not None:
            raise self.error
        return self.text


def _service(audio_text: str = "视频里说的话", audio_error: Exception | None = None):
    return KnowledgeMediaExtractorService(
        db=SimpleNamespace(),
        cos_service=_FakeStorage(),
        audio_service=_FakeAudioService(audio_text, audio_error),
    )


def _upload(name: str = "clip.mp4"):
    return SimpleNamespace(
        id=uuid4(),
        key=f"2026/09/15/{uuid4()}.mp4",
        name=name,
        extension="mp4",
        mime_type="video/mp4",
    )


def _write_frame(tmp_path, index: int = 1) -> str:
    """写一个真实存在的帧文件（`path_to_data_uri` 要求文件存在）。"""
    path = tmp_path / f"frame_{index:03d}.jpg"
    path.write_bytes(b"\xff\xd8\xff\xe0frame-bytes")
    return str(path)


def _write_audio(tmp_path, name: str = "track.wav") -> str:
    path = tmp_path / name
    path.write_bytes(b"RIFF....WAVEfmt ")
    return str(path)


def _no_ffmpeg():
    raise RuntimeError("ffmpeg 不可用")


class TestExtractVideoAudio:
    """`vision_invoke.extract_video_audio` 的行为约束。"""

    def test_command_contains_asr_flags_and_returns_target(self, monkeypatch, tmp_path):
        calls = []

        def _fake_run(cmd, **_kwargs):
            calls.append(cmd)
            with open(cmd[-1], "wb") as fh:
                fh.write(b"RIFF....WAVE")
            return subprocess.CompletedProcess(cmd, 0, b"", b"")

        monkeypatch.setattr(vision_invoke, "subprocess", SimpleNamespace(run=_fake_run))
        monkeypatch.setattr(vision_invoke, "_ffmpeg_available", lambda: True)
        target = str(tmp_path / "audio.wav")

        result = vision_invoke.extract_video_audio("in.mp4", target)

        assert result == target
        assert os.path.isfile(target)
        assert calls, "应调用 ffmpeg 抽取音轨"
        cmd = calls[0]
        assert "-vn" in cmd, "抽音轨必须丢弃视频流"
        assert cmd[cmd.index("-ac") + 1] == "1", "抽音轨必须转单声道"
        assert cmd[cmd.index("-ar") + 1] == "16000", "抽音轨必须用 16k 采样率"

    def test_raises_when_ffmpeg_unavailable(self, monkeypatch, tmp_path):
        monkeypatch.setattr(vision_invoke, "_ffmpeg_available", lambda: False)
        monkeypatch.setattr(vision_invoke, "_resolve_ffmpeg_exe", _no_ffmpeg)

        with pytest.raises(RuntimeError):
            vision_invoke.extract_video_audio("in.mp4", str(tmp_path / "a.wav"))

    def test_raises_when_no_file_produced(self, monkeypatch, tmp_path):
        """ffmpeg 退出码为 0 但未产出文件时不得静默成功。"""

        def _fake_run(cmd, **_kwargs):
            return subprocess.CompletedProcess(cmd, 0, b"", b"")

        monkeypatch.setattr(vision_invoke, "subprocess", SimpleNamespace(run=_fake_run))
        monkeypatch.setattr(vision_invoke, "_ffmpeg_available", lambda: True)

        with pytest.raises(RuntimeError):
            vision_invoke.extract_video_audio("in.mp4", str(tmp_path / "missing.wav"))


class TestVideoTranscriptSegments:
    """`_extract_video` 中的音轨转写片段。"""

    def test_transcript_segment_precedes_frame_segments(self, monkeypatch, tmp_path):
        service = _service()
        frame = _write_frame(tmp_path)
        audio = _write_audio(tmp_path)
        monkeypatch.setattr(
            service, "_extract_frames_with_offsets",
            lambda _v, _d: [ExtractedFrame(path=frame, time_offset=0.0)],
        )
        monkeypatch.setattr(service, "_invoke_vision", lambda _uri, _prompt: "画面描述")
        monkeypatch.setattr(service, "_extract_audio_track", lambda _v: audio)
        monkeypatch.setattr(service, "_transcribe_audio_file", lambda _p: "视频里说的话")

        segments = service._extract_video(_upload())

        assert [s.content for s in segments] == ["视频里说的话", "画面描述"]
        assert segments[0].metadata["media_type"] == "video"
        assert segments[0].metadata["source"] == "audio_transcript"
        assert segments[1].metadata["scene_index"] == 1
        assert segments[1].metadata["frame_count"] == 1

    def test_blank_transcript_produces_no_segment(self, monkeypatch, tmp_path):
        service = _service()
        frame = _write_frame(tmp_path)
        monkeypatch.setattr(
            service, "_extract_frames_with_offsets",
            lambda _v, _d: [ExtractedFrame(path=frame, time_offset=0.0)],
        )
        monkeypatch.setattr(service, "_invoke_vision", lambda _uri, _prompt: "画面描述")
        monkeypatch.setattr(service, "_extract_audio_track", lambda _v: _write_audio(tmp_path))
        monkeypatch.setattr(service, "_transcribe_audio_file", lambda _p: "   ")

        segments = service._extract_video(_upload())

        assert [s.content for s in segments] == ["画面描述"]

    def test_audio_track_failure_keeps_frame_segments(self, monkeypatch, tmp_path):
        """音轨抽取抛异常时视频解析仍必须成功（帧描述是有效产物）。"""
        service = _service()
        frame = _write_frame(tmp_path)
        monkeypatch.setattr(
            service, "_extract_frames_with_offsets",
            lambda _v, _d: [ExtractedFrame(path=frame, time_offset=0.0)],
        )
        monkeypatch.setattr(service, "_invoke_vision", lambda _uri, _prompt: "画面描述")

        def _boom(_video_path):
            raise RuntimeError("no audio stream")

        monkeypatch.setattr(service, "_extract_audio_track", _boom)

        segments = service._extract_video(_upload())

        assert [s.content for s in segments] == ["画面描述"]

    def test_asr_failure_keeps_frame_segments(self, monkeypatch, tmp_path):
        """音轨抽成功但 ASR 失败时同样只降级，不得中断解析。"""
        service = _service()
        frame = _write_frame(tmp_path)
        monkeypatch.setattr(
            service, "_extract_frames_with_offsets",
            lambda _v, _d: [ExtractedFrame(path=frame, time_offset=0.0)],
        )
        monkeypatch.setattr(service, "_invoke_vision", lambda _uri, _prompt: "画面描述")
        monkeypatch.setattr(service, "_extract_audio_track", lambda _v: _write_audio(tmp_path))

        def _boom(_audio_path):
            raise RuntimeError("asr down")

        monkeypatch.setattr(service, "_transcribe_audio_file", _boom)

        segments = service._extract_video(_upload())

        assert [s.content for s in segments] == ["画面描述"]

    def test_audio_track_file_is_removed(self, monkeypatch, tmp_path):
        """音轨临时文件必须清理，避免临时目录堆积音频。"""
        service = _service()
        frame = _write_frame(tmp_path)
        audio = _write_audio(tmp_path)
        monkeypatch.setattr(
            service, "_extract_frames_with_offsets",
            lambda _v, _d: [ExtractedFrame(path=frame, time_offset=0.0)],
        )
        monkeypatch.setattr(service, "_invoke_vision", lambda _uri, _prompt: "画面描述")
        monkeypatch.setattr(service, "_extract_audio_track", lambda _v: audio)
        monkeypatch.setattr(service, "_transcribe_audio_file", lambda _p: "视频里说的话")

        service._extract_video(_upload())

        assert not os.path.exists(audio), "音轨临时文件应在解析后被删除"

    def test_audio_track_file_is_removed_even_when_asr_fails(self, monkeypatch, tmp_path):
        service = _service()
        frame = _write_frame(tmp_path)
        audio = _write_audio(tmp_path)
        monkeypatch.setattr(
            service, "_extract_frames_with_offsets",
            lambda _v, _d: [ExtractedFrame(path=frame, time_offset=0.0)],
        )
        monkeypatch.setattr(service, "_invoke_vision", lambda _uri, _prompt: "画面描述")
        monkeypatch.setattr(service, "_extract_audio_track", lambda _v: audio)

        def _boom(_audio_path):
            raise RuntimeError("asr down")

        monkeypatch.setattr(service, "_transcribe_audio_file", _boom)

        service._extract_video(_upload())

        assert not os.path.exists(audio)

    def test_transcribe_audio_file_wraps_file_storage(self, tmp_path):
        """`_transcribe_audio_file` 必须把本地音轨包装成 FileStorage 再交给 ASR。"""
        audio = _write_audio(tmp_path)
        service = _service()

        transcript = service._transcribe_audio_file(audio)

        assert transcript == "视频里说的话"
        received = service.audio_service.received
        assert received is not None
        assert received.filename == "track.wav"
        assert received.read() == b"RIFF....WAVEfmt "

    def test_audio_track_path_is_created_next_to_video(self, monkeypatch, tmp_path):
        """抽音轨的目标文件应落在视频同目录（即 `_extract_video` 的临时目录）内。"""
        import internal.service.knowledge_media_extractor_service as module

        service = _service()
        video = tmp_path / "video.mp4"
        video.write_bytes(b"video-bytes")
        captured = {}

        def _fake_extract(video_path, target_path):
            captured["video_path"] = video_path
            captured["target"] = target_path
            with open(target_path, "wb") as fh:
                fh.write(b"RIFF....WAVE")
            return target_path

        monkeypatch.setattr(module, "extract_video_audio", _fake_extract)

        result = service._extract_audio_track(str(video))

        assert captured["video_path"] == str(video)
        assert result == captured["target"]
        assert os.path.isfile(result)
        assert os.path.dirname(result) == str(tmp_path), "音轨应落在视频所在临时目录内"
