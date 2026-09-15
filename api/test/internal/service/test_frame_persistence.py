"""关键帧留存测试（设计稿 §3.4：视觉向量的前置能力）。

覆盖：
1. `extract_video_frames_to_dir` 抽帧到指定目录并返回真实存在的文件路径，目录不被删除；
2. `_persist_frame` 走 `cos_service.upload_bytes` + `upload_file_service.create_upload_file`；
3. 帧留存成功后帧片段 metadata 带 `frame_url`；留存失败只降级为 `frame_url=""`，不中断解析。
"""
import os
from types import SimpleNamespace
from uuid import uuid4

import pytest

from internal.core.vision import vision_invoke
from internal.core.vision.vision_invoke import ExtractedFrame
from internal.service.knowledge_media_extractor_service import KnowledgeMediaExtractorService


class _FakeStorage:
    """模拟对象存储：下载写字节，上传返回带 key 的产物记录。"""

    def __init__(self, payload: bytes = b"video-bytes", upload_error: Exception | None = None):
        self._payload = payload
        self._upload_error = upload_error
        self.uploaded: list[tuple[str, bytes]] = []

    def download_file(self, key, target_path):
        with open(target_path, "wb") as fh:
            fh.write(self._payload)

    def upload_bytes(self, filename, content, **_kwargs):
        if self._upload_error is not None:
            raise self._upload_error
        self.uploaded.append((filename, content))
        return SimpleNamespace(key=f"frames/{filename}", size=len(content))


class _FakeUploadFileService:
    """记录 create_upload_file 入参，便于断言字段完整性。"""

    def __init__(self):
        self.calls: list[dict] = []

    def create_upload_file(self, **kwargs):
        self.calls.append(kwargs)
        return SimpleNamespace(id=uuid4(), **kwargs)


def _service(storage: _FakeStorage | None = None):
    upload_file_service = _FakeUploadFileService()
    service = KnowledgeMediaExtractorService(
        db=SimpleNamespace(),
        cos_service=storage or _FakeStorage(),
        audio_service=SimpleNamespace(audio_to_text=lambda _fs, **_kw: ""),
        upload_file_service=upload_file_service,
    )
    return service, upload_file_service


def _upload(name: str = "clip.mp4"):
    return SimpleNamespace(
        id=uuid4(),
        key=f"2026/09/15/{uuid4()}.mp4",
        name=name,
        extension="mp4",
        mime_type="video/mp4",
    )


def _write_frame(tmp_path, index: int = 1) -> str:
    path = tmp_path / f"frame_{index:03d}.jpg"
    path.write_bytes(b"\xff\xd8\xff\xe0frame-bytes")
    return str(path)


def _silence_audio(service, monkeypatch, tmp_path):
    """屏蔽音轨分支，让用例聚焦帧留存。"""
    audio = tmp_path / "track.wav"
    audio.write_bytes(b"RIFF....WAVE")
    monkeypatch.setattr(service, "_extract_audio_track", lambda _v: str(audio))
    monkeypatch.setattr(service, "_transcribe_audio_file", lambda _p: "")


class TestExtractVideoFramesToDir:
    """`vision_invoke.extract_video_frames_to_dir` 的行为约束。"""

    def test_returns_real_paths_and_keeps_directory(self, monkeypatch, tmp_path):
        captured = {}

        def _fake_ffmpeg(video_path, frame_count, out_dir):
            captured["out_dir"] = out_dir
            paths = []
            for index in range(1, frame_count + 1):
                path = os.path.join(out_dir, f"frame_{index:03d}.jpg")
                with open(path, "wb") as fh:
                    fh.write(b"\xff\xd8\xff\xe0x")
                paths.append(path)
            return paths

        monkeypatch.setattr(vision_invoke, "_ffmpeg_available", lambda: True)
        monkeypatch.setattr(vision_invoke, "_extract_frames_to_dir_ffmpeg", _fake_ffmpeg)
        out_dir = tmp_path / "frames"

        paths = vision_invoke.extract_video_frames_to_dir("in.mp4", str(out_dir), frame_count=2)

        assert len(paths) == 2
        assert all(os.path.isfile(path) for path in paths)
        assert captured["out_dir"] == str(out_dir)
        assert os.path.isdir(out_dir), "返回的路径必须仍然存在（目录由调用方负责）"
        assert not all(path.startswith("data:") for path in paths), "应返回文件路径而非 data URI"

    def test_returns_file_paths_not_data_uris(self, monkeypatch, tmp_path):
        def _fake_ffmpeg(video_path, frame_count, out_dir):
            path = os.path.join(out_dir, "frame_001.jpg")
            with open(path, "wb") as fh:
                fh.write(b"\xff\xd8\xff\xe0x")
            return [path]

        monkeypatch.setattr(vision_invoke, "_ffmpeg_available", lambda: True)
        monkeypatch.setattr(vision_invoke, "_extract_frames_to_dir_ffmpeg", _fake_ffmpeg)

        paths = vision_invoke.extract_video_frames_to_dir("in.mp4", str(tmp_path / "f"))

        assert paths and paths[0].endswith("frame_001.jpg")

    def test_normalizes_zero_frame_count(self, monkeypatch, tmp_path):
        captured = {}

        def _fake_ffmpeg(video_path, frame_count, out_dir):
            captured["frame_count"] = frame_count
            return []

        monkeypatch.setattr(vision_invoke, "_ffmpeg_available", lambda: True)
        monkeypatch.setattr(vision_invoke, "_extract_frames_to_dir_ffmpeg", _fake_ffmpeg)

        vision_invoke.extract_video_frames_to_dir("in.mp4", str(tmp_path / "f"), frame_count=0)

        assert captured["frame_count"] == 1

    def test_raises_when_ffmpeg_unavailable(self, monkeypatch, tmp_path):
        monkeypatch.setattr(vision_invoke, "_ffmpeg_available", lambda: False)

        def _no_ffmpeg():
            raise RuntimeError("ffmpeg 不可用")

        monkeypatch.setattr(vision_invoke, "_resolve_ffmpeg_exe", _no_ffmpeg)

        with pytest.raises(RuntimeError):
            vision_invoke.extract_video_frames_to_dir("in.mp4", str(tmp_path / "f"))


class TestPersistFrame:
    """`_persist_frame` 必须同时完成对象存储上传与 UploadFile 记录创建。"""

    def test_uploads_bytes_and_creates_upload_file_record(self, tmp_path):
        storage = _FakeStorage()
        service, upload_file_service = _service(storage)
        frame = _write_frame(tmp_path)
        account_id, document_id = uuid4(), uuid4()

        result = service._persist_frame(frame, account_id=account_id, document_id=document_id)

        assert result.key == "frames/frame_001.jpg"
        assert storage.uploaded == [("frame_001.jpg", b"\xff\xd8\xff\xe0frame-bytes")]
        assert len(upload_file_service.calls) == 1
        record = upload_file_service.calls[0]
        assert record["account_id"] == account_id
        assert record["name"] == "frame_001.jpg"
        assert record["key"] == "frames/frame_001.jpg"
        assert record["size"] == len(b"\xff\xd8\xff\xe0frame-bytes")
        assert record["extension"] == "jpg"
        assert record["mime_type"] == "image/jpeg"
        assert record["storage_backend"] == "local"
        assert len(record["hash"]) == 64, "hash 应为 sha3_256 十六进制摘要"

    def test_raises_when_upload_fails(self, tmp_path):
        storage = _FakeStorage(upload_error=RuntimeError("storage down"))
        service, _upload_file_service = _service(storage)

        with pytest.raises(RuntimeError):
            service._persist_frame(
                _write_frame(tmp_path), account_id=uuid4(), document_id=uuid4()
            )


class TestFrameUrlMetadata:
    """`_extract_video` 把留存结果的 key 写入帧片段 metadata。"""

    def test_frame_segments_carry_frame_url(self, monkeypatch, tmp_path):
        service, _upload_file_service = _service()
        frame = _write_frame(tmp_path)
        monkeypatch.setattr(
            service, "_extract_frames_with_offsets",
            lambda _v, _d: [ExtractedFrame(path=frame, time_offset=0.0)],
        )
        monkeypatch.setattr(service, "_invoke_vision", lambda _uri, _prompt: "画面描述")
        _silence_audio(service, monkeypatch, tmp_path)

        segments = service._extract_video(
            _upload(), account_id=uuid4(), document_id=uuid4()
        )

        assert segments[0].content == "画面描述"
        assert segments[0].metadata["frame_url"] == "frames/frame_001.jpg"
        assert segments[0].metadata["scene_index"] == 1

    def test_vision_receives_data_uri_from_persisted_frame(self, monkeypatch, tmp_path):
        """帧文件在临时目录内，视觉调用必须收到 data URI（而非已失效的路径）。"""
        service, _upload_file_service = _service()
        frame = _write_frame(tmp_path)
        monkeypatch.setattr(
            service, "_extract_frames_with_offsets",
            lambda _v, _d: [ExtractedFrame(path=frame, time_offset=0.0)],
        )
        _silence_audio(service, monkeypatch, tmp_path)
        seen: list[str] = []

        def _vision(data_uri, _prompt):
            seen.append(data_uri)
            return "画面描述"

        monkeypatch.setattr(service, "_invoke_vision", _vision)

        service._extract_video(_upload(), account_id=uuid4(), document_id=uuid4())

        assert seen and seen[0].startswith("data:image/jpeg;base64,")

    def test_frame_upload_failure_keeps_segment_with_empty_frame_url(self, monkeypatch, tmp_path):
        storage = _FakeStorage(upload_error=RuntimeError("storage down"))
        service, _upload_file_service = _service(storage)
        frame = _write_frame(tmp_path)
        monkeypatch.setattr(
            service, "_extract_frames_with_offsets",
            lambda _v, _d: [ExtractedFrame(path=frame, time_offset=0.0)],
        )
        monkeypatch.setattr(service, "_invoke_vision", lambda _uri, _prompt: "画面描述")
        _silence_audio(service, monkeypatch, tmp_path)

        segments = service._extract_video(
            _upload(), account_id=uuid4(), document_id=uuid4()
        )

        assert segments[0].content == "画面描述"
        assert segments[0].metadata["frame_url"] == ""

    def test_skips_persistence_when_account_or_document_missing(self, monkeypatch, tmp_path):
        """account_id / document_id 缺失时跳过留存（向后兼容旧调用方式）。"""
        storage = _FakeStorage()
        service, upload_file_service = _service(storage)
        frame = _write_frame(tmp_path)
        monkeypatch.setattr(
            service, "_extract_frames_with_offsets",
            lambda _v, _d: [ExtractedFrame(path=frame, time_offset=0.0)],
        )
        monkeypatch.setattr(service, "_invoke_vision", lambda _uri, _prompt: "画面描述")
        _silence_audio(service, monkeypatch, tmp_path)

        segments = service._extract_video(_upload())

        assert segments[0].metadata["frame_url"] == ""
        assert storage.uploaded == []
        assert upload_file_service.calls == []

    def test_uses_frame_count_from_frames_dir(self, monkeypatch, tmp_path):
        service, _upload_file_service = _service()
        frames = [
            ExtractedFrame(path=_write_frame(tmp_path, 1), time_offset=0.0),
            ExtractedFrame(path=_write_frame(tmp_path, 2), time_offset=5.0),
        ]
        monkeypatch.setattr(service, "_extract_frames_with_offsets", lambda _v, _d: frames)
        monkeypatch.setattr(service, "_invoke_vision", lambda _uri, _prompt: "画面描述")
        _silence_audio(service, monkeypatch, tmp_path)

        segments = service._extract_video(
            _upload(), account_id=uuid4(), document_id=uuid4()
        )

        assert len(segments) == 2
        assert [s.metadata["frame_count"] for s in segments] == [2, 2]
        assert [s.metadata["scene_index"] for s in segments] == [1, 2]

    def test_raises_when_frames_empty(self, monkeypatch, tmp_path):
        service, _upload_file_service = _service()
        monkeypatch.setattr(service, "_extract_frames_with_offsets", lambda _v, _d: [])
        monkeypatch.setattr(service, "_extract_audio_track", lambda _v: str(tmp_path / "a.wav"))
        monkeypatch.setattr(service, "_transcribe_audio_file", lambda _p: "视频里说的话")

        with pytest.raises(RuntimeError):
            service._extract_video(_upload(), account_id=uuid4(), document_id=uuid4())


class TestExtractFramesWithOffsetsDelegation:
    """`_extract_frames_with_offsets` 是可替换方法，应转调 vision_invoke 的新函数。"""

    def test_delegates_to_vision_invoke(self, monkeypatch, tmp_path):
        import internal.service.knowledge_media_extractor_service as module

        captured = {}

        def _fake(video_path, out_dir):
            captured["video_path"] = video_path
            captured["out_dir"] = out_dir
            return [ExtractedFrame(path="/tmp/frame_001.jpg", time_offset=1.0)]

        monkeypatch.setattr(module, "extract_video_frames_with_offsets", _fake)
        service, _upload_file_service = _service()

        result = service._extract_frames_with_offsets("in.mp4", str(tmp_path))

        assert [frame.path for frame in result] == ["/tmp/frame_001.jpg"]
        assert [frame.time_offset for frame in result] == [1.0]
        assert captured == {"video_path": "in.mp4", "out_dir": str(tmp_path)}
