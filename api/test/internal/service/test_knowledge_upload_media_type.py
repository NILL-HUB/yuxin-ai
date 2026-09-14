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


def test_upload_document_rejects_before_storing_file(monkeypatch):
    """板块类型不匹配时应在落盘前拒绝，不产生孤儿文件/配额占用。"""
    from uuid import uuid4

    upload_calls = []
    service = _service()
    service.get_accessible_base = lambda _id, _account: SimpleNamespace(
        id=uuid4(), base_type="video"
    )
    cos_service = SimpleNamespace(
        upload_file=lambda **kwargs: upload_calls.append(kwargs)
    )
    service._get_cos_service = lambda: cos_service

    incoming = SimpleNamespace(filename="report.pdf")
    account = SimpleNamespace(id=uuid4())

    with pytest.raises(ValidateErrorException):
        service.upload_document(uuid4(), incoming, account)

    assert upload_calls == [], "被拒绝的文件不应执行上传"
