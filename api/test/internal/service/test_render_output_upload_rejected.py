"""成品库禁止手动上传测试（设计 §4.1）。

成品库由系统写入渲染产物；用户手动上传会污染「成品」语义。
三条上传入口都必须挡住：upload_document / create_document_from_upload_file /
assert_upload_allowed（分片上传在合并前预校验走这条）。
"""
from types import SimpleNamespace
from uuid import uuid4

import pytest

from internal.entity.knowledge_entity import KnowledgeCreatedFrom
from internal.exception import ForbiddenException
from internal.service.knowledge_base_service import KnowledgeBaseService


def _service(base):
    service = KnowledgeBaseService.__new__(KnowledgeBaseService)
    service.get_accessible_base = lambda kb_id, account: base
    return service


def _render_base():
    return SimpleNamespace(
        id=uuid4(),
        base_type="video",
        created_from=KnowledgeCreatedFrom.RENDER_OUTPUT.value,
    )


def _normal_base():
    return SimpleNamespace(
        id=uuid4(),
        base_type="video",
        created_from=KnowledgeCreatedFrom.MANUAL_UPLOAD.value,
    )


def test_upload_document_rejected_for_render_base():
    service = _service(_render_base())

    with pytest.raises(ForbiddenException):
        service.upload_document(uuid4(), SimpleNamespace(filename="a.mp4"), SimpleNamespace(id=uuid4()))


def test_create_document_from_upload_file_rejected():
    service = _service(_render_base())
    upload_file = SimpleNamespace(id=uuid4(), extension="mp4", name="a.mp4")

    with pytest.raises(ForbiddenException):
        service.create_document_from_upload_file(
            knowledge_base_id=uuid4(), upload_file=upload_file, account=SimpleNamespace(id=uuid4())
        )


def test_assert_upload_allowed_rejected():
    service = _service(_render_base())

    with pytest.raises(ForbiddenException):
        service.assert_upload_allowed(uuid4(), "mp4", SimpleNamespace(id=uuid4()))


def test_normal_base_still_allows_video_upload():
    """回归保护：普通视频库不受影响（否则会误伤全部上传）。"""
    service = _service(_normal_base())

    result = service.assert_upload_allowed(uuid4(), "mp4", SimpleNamespace(id=uuid4()))

    assert result is not None
