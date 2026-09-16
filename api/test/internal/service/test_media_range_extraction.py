"""媒体提取器的区间抽帧入口（供 L2 复用）。

做成独立方法（而非直接调 vision_invoke）：L2 的单测需要替换抽帧行为，
不必依赖真实 ffmpeg。
"""
from types import SimpleNamespace

from internal.core.vision.vision_invoke import ExtractedFrame
from internal.service.knowledge_media_extractor_service import (
    KnowledgeMediaExtractorService,
)


def _service():
    return KnowledgeMediaExtractorService(
        db=SimpleNamespace(),
        cos_service=SimpleNamespace(),
        audio_service=SimpleNamespace(),
        upload_file_service=SimpleNamespace(),
    )


def test_delegates_to_vision_invoke_range(monkeypatch, tmp_path):
    captured = {}

    def _fake(video_path, out_dir, start_sec, duration_sec):
        captured["video_path"] = video_path
        captured["out_dir"] = out_dir
        captured["start_sec"] = start_sec
        captured["duration_sec"] = duration_sec
        return [ExtractedFrame(path="/tmp/f1.jpg", time_offset=21.0)]

    import internal.service.knowledge_media_extractor_service as module
    monkeypatch.setattr(module, "extract_video_frames_in_range", _fake)

    frames = _service()._extract_frames_in_range(
        "in.mp4", str(tmp_path), start_sec=20.0, duration_sec=10.0
    )

    assert [frame.time_offset for frame in frames] == [21.0]
    assert captured["start_sec"] == 20.0
    assert captured["duration_sec"] == 10.0
    assert captured["out_dir"] == str(tmp_path)
