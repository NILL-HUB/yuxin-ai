import os
import tempfile
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
