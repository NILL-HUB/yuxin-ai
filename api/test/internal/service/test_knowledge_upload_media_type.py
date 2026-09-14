from types import SimpleNamespace

import pytest

from internal.exception import ValidateErrorException
from internal.service.knowledge_base_service import KnowledgeBaseService


def _service():
    return KnowledgeBaseService(
        db=SimpleNamespace(),
        retrieval_service=SimpleNamespace(),
        icon_generator_service=SimpleNamespace(),
    )


def test_media_type_allowed_for_matching_base_type():
    service = _service()
    base = SimpleNamespace(base_type="video")
    service._assert_media_type_allowed(base, "mp4")


def test_media_type_rejected_for_mismatched_base_type():
    service = _service()
    base = SimpleNamespace(base_type="video")
    with pytest.raises(ValidateErrorException):
        service._assert_media_type_allowed(base, "pdf")


def test_mixed_base_type_allows_any_media_type():
    service = _service()
    base = SimpleNamespace(base_type="mixed")
    service._assert_media_type_allowed(base, "mp4")
    service._assert_media_type_allowed(base, "pdf")


def test_missing_base_type_falls_back_to_mixed():
    service = _service()
    base = SimpleNamespace(base_type=None)
    service._assert_media_type_allowed(base, "mp3")


def test_empty_extension_is_allowed():
    """无扩展名（历史数据）不拦截，交由后续流程处理。"""
    service = _service()
    base = SimpleNamespace(base_type="video")
    service._assert_media_type_allowed(base, "")
