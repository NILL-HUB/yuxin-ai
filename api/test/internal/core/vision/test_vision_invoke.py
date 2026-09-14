import base64
import os
import tempfile

import pytest

from internal.core.vision.vision_invoke import path_to_data_uri


def test_path_to_data_uri_encodes_file_bytes():
    with tempfile.TemporaryDirectory() as temp_dir:
        path = os.path.join(temp_dir, "sample.jpg")
        with open(path, "wb") as fh:
            fh.write(b"\xff\xd8\xff\xe0hello")

        data_uri = path_to_data_uri(path)

    assert data_uri.startswith("data:image/jpeg;base64,")
    encoded = data_uri.split(",", 1)[1]
    assert base64.b64decode(encoded) == b"\xff\xd8\xff\xe0hello"


def test_path_to_data_uri_rejects_oversized_file(monkeypatch):
    import internal.core.vision.vision_invoke as module

    monkeypatch.setattr(module, "_MAX_IMAGE_BYTES", 4)
    with tempfile.TemporaryDirectory() as temp_dir:
        path = os.path.join(temp_dir, "big.jpg")
        with open(path, "wb") as fh:
            fh.write(b"12345")

        with pytest.raises(ValueError):
            path_to_data_uri(path)


def test_path_to_data_uri_rejects_missing_file():
    with pytest.raises(ValueError):
        path_to_data_uri("/nonexistent/path/does-not-exist.jpg")


def test_path_to_data_uri_accepts_empty_file():
    """空文件小于上限，应正常编码（不抛错）。"""
    with tempfile.TemporaryDirectory() as temp_dir:
        path = os.path.join(temp_dir, "empty.jpg")
        with open(path, "wb") as fh:
            pass
        assert path_to_data_uri(path) == "data:image/jpeg;base64,"


def test_extract_video_frames_normalizes_zero_frame_count(monkeypatch):
    """frame_count=0 应被归一化为至少 1，不应抛除零错误。"""
    import internal.core.vision.vision_invoke as module

    captured = {}

    def _fake_ffmpeg(video_path, frame_count):
        captured["frame_count"] = frame_count
        return ["data:fake"]

    monkeypatch.setattr(module, "_ffmpeg_available", lambda: True)
    monkeypatch.setattr(module, "_extract_frames_ffmpeg", _fake_ffmpeg)

    assert module.extract_video_frames("video.mp4", 0) == ["data:fake"]
    assert captured["frame_count"] == 1


def test_invoke_vision_model_raises_without_model(monkeypatch):
    """未配置视觉模型时应抛 RuntimeError。"""
    import internal.core.vision.vision_invoke as module
    from internal.service.language_model_service import LanguageModelService

    monkeypatch.setattr(
        LanguageModelService, "get_feature_model", classmethod(lambda cls, _key: None)
    )
    with pytest.raises(RuntimeError):
        module.invoke_vision_model("data:image/jpeg;base64,AAAA", "describe")
