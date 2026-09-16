"""渲染成品入库测试。

成品由系统写入成品库：走 store_render_output（不经用户上传校验），
需落 COS、建 KnowledgeDocument、并触发索引（否则成品不可检索 = 白存）。
"""
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest

from internal.entity.knowledge_entity import KnowledgeCreatedFrom
from internal.service.knowledge_base_service import KnowledgeBaseService


class _Cos:
    def __init__(self):
        self.calls = []

    def upload_bytes(self, *, filename, content, account_id, mime_type="", allow_overflow=False):
        self.calls.append(
            {
                "filename": filename,
                "size": len(content),
                "mime_type": mime_type,
                "allow_overflow": allow_overflow,
            }
        )
        return SimpleNamespace(id=uuid4(), name=filename, extension="mp4")


def _service(base, cos, indexing):
    service = KnowledgeBaseService.__new__(KnowledgeBaseService)
    service.get_or_create_render_output_base = lambda account: base
    service._get_cos_service = lambda: cos
    service._get_knowledge_indexing_service = lambda: indexing
    created = {}

    def _create(model, **kwargs):
        created.update(kwargs)
        return SimpleNamespace(id=uuid4(), **kwargs)

    service.create = _create
    service.created_payload = created
    return service


def test_render_output_is_stored_and_indexed(tmp_path):
    video = tmp_path / "out.mp4"
    video.write_bytes(b"x" * 1024)
    base = SimpleNamespace(id=uuid4(), created_from=KnowledgeCreatedFrom.RENDER_OUTPUT.value)
    cos, indexing = _Cos(), SimpleNamespace(calls=[])
    indexing.build_document = lambda doc_id, account: indexing.calls.append(doc_id)
    service = _service(base, cos, indexing)
    account = SimpleNamespace(id=uuid4())

    document = service.store_render_output(
        account=account, video_path=video, name="我的短片"
    )

    assert cos.calls and cos.calls[0]["size"] == 1024
    assert cos.calls[0]["mime_type"] == "video/mp4"
    assert cos.calls[0]["allow_overflow"] is True, "成品入库必须走宽让配额（设计 §6.3）"
    assert service.created_payload["knowledge_base_id"] == base.id
    assert service.created_payload["media_type"] == "video"
    assert service.created_payload["source_type"] == KnowledgeCreatedFrom.RENDER_OUTPUT.value
    assert indexing.calls == [document.id], "必须触发索引，否则成品不可检索"


def test_missing_video_file_rejected(tmp_path):
    service = _service(SimpleNamespace(id=uuid4()), _Cos(), SimpleNamespace())
    account = SimpleNamespace(id=uuid4())

    with pytest.raises(Exception):
        service.store_render_output(
            account=account, video_path=tmp_path / "nope.mp4", name="x"
        )
