from contextlib import contextmanager
from types import SimpleNamespace
from uuid import uuid4

import pytest

from internal.exception import ValidateErrorException
from internal.service.knowledge_base_service import KnowledgeBaseService


class _QueryStub:
    def __init__(self, *, one_or_none_result=None):
        self._one_or_none = one_or_none_result

    def filter(self, *_a, **_kw):
        return self

    def filter_by(self, **_kw):
        return self

    def one_or_none(self):
        return self._one_or_none


class _SessionStub:
    def __init__(self, queries=None):
        self._queries = list(queries or [])

    def query(self, *_a, **_kw):
        if self._queries:
            return self._queries.pop(0)
        return _QueryStub()


@contextmanager
def _auto_commit():
    yield


def _new_service(session=None):
    return KnowledgeBaseService(
        db=SimpleNamespace(session=session or _SessionStub(), auto_commit=lambda: _auto_commit()),
        retrieval_service=SimpleNamespace(),
        icon_generator_service=SimpleNamespace(),
    )


def test_invalid_base_type_is_rejected():
    service = _new_service(_SessionStub([_QueryStub()]))
    with pytest.raises(ValidateErrorException):
        service.create_user_content_base(
            name="非法库", account=SimpleNamespace(id=uuid4()), base_type="nonexistent")


def test_invalid_partition_mode_is_rejected():
    service = _new_service(_SessionStub([_QueryStub()]))
    with pytest.raises(ValidateErrorException):
        service.create_user_content_base(
            name="非法库", account=SimpleNamespace(id=uuid4()), partition_mode="weekly")


def test_valid_base_type_and_mode_are_persisted(monkeypatch):
    service = _new_service(_SessionStub([_QueryStub()]))
    monkeypatch.setattr(service, "create",
        lambda model, **kwargs: SimpleNamespace(**kwargs))

    result = service.create_user_content_base(
        name="视频素材库", account=SimpleNamespace(id=uuid4()),
        base_type="video", partition_mode="date_month")

    assert result.base_type == "video"
    assert result.partition_mode == "date_month"


def test_create_base_with_req_passes_base_type_and_partition_mode(monkeypatch):
    """创建请求必须把板块类型与分区模式透传到服务层，否则用户建不出专用库。"""
    service = _new_service(_SessionStub([_QueryStub()]))
    captured = {}

    def _fake_create_user_content_base(**kwargs):
        captured.update(kwargs)
        return SimpleNamespace(id=uuid4(), settings={})

    monkeypatch.setattr(service, "create_user_content_base", _fake_create_user_content_base)
    monkeypatch.setattr(service, "auto_select_embedding_model",
                        lambda: SimpleNamespace(id=uuid4()))
    monkeypatch.setattr(service, "update", lambda instance, **kwargs: instance)

    from internal.schema.knowledge_base_schema import CreateKnowledgeBaseReq
    from werkzeug.datastructures import MultiDict

    req = CreateKnowledgeBaseReq(MultiDict({
        "name": "图片库", "description": "d", "icon": "",
        "base_type": "image", "partition_mode": "custom",
    }))
    req.icon.data = ""

    service.create_user_content_base_with_req(req, SimpleNamespace(id=uuid4()))

    assert captured["base_type"] == "image"
    assert captured["partition_mode"] == "custom"


def test_create_base_with_req_defaults_to_mixed_and_none(monkeypatch):
    """未显式指定时回退 mixed / none，保持既有行为不变。"""
    service = _new_service(_SessionStub([_QueryStub()]))
    captured = {}
    monkeypatch.setattr(
        service, "create_user_content_base",
        lambda **kwargs: captured.update(kwargs) or SimpleNamespace(id=uuid4(), settings={}),
    )
    monkeypatch.setattr(service, "auto_select_embedding_model",
                        lambda: SimpleNamespace(id=uuid4()))
    monkeypatch.setattr(service, "update", lambda instance, **kwargs: instance)

    from internal.schema.knowledge_base_schema import CreateKnowledgeBaseReq
    from werkzeug.datastructures import MultiDict

    req = CreateKnowledgeBaseReq(MultiDict({"name": "通用库"}))
    req.icon.data = ""

    service.create_user_content_base_with_req(req, SimpleNamespace(id=uuid4()))

    assert captured["base_type"] == "mixed"
    assert captured["partition_mode"] == "none"


def test_create_req_rejects_invalid_base_type():
    from internal.schema.knowledge_base_schema import CreateKnowledgeBaseReq
    from werkzeug.datastructures import MultiDict

    req = CreateKnowledgeBaseReq(MultiDict({"name": "x", "base_type": "hologram"}))
    assert not req.validate()


def test_create_req_rejects_invalid_partition_mode():
    from internal.schema.knowledge_base_schema import CreateKnowledgeBaseReq
    from werkzeug.datastructures import MultiDict

    req = CreateKnowledgeBaseReq(MultiDict({"name": "x", "partition_mode": "weekly"}))
    assert not req.validate()
