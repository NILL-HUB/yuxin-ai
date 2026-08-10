from contextlib import contextmanager
from types import SimpleNamespace
from uuid import uuid4

import pytest

from internal.exception import ForbiddenException
from internal.model import KnowledgeBase
from internal.service.scoped_knowledge_service import (
    SystemKnowledgeService,
    UserContentKnowledgeService,
)


class _QueryStub:
    def __init__(self, *, one_or_none_result=None, all_result=None):
        self._one_or_none_result = one_or_none_result
        self._all_result = [] if all_result is None else all_result

    def filter(self, *_args, **_kwargs):
        return self

    def filter_by(self, **_kwargs):
        return self

    def order_by(self, *_args, **_kwargs):
        return self

    def one_or_none(self):
        return self._one_or_none_result

    def all(self):
        return self._all_result


class _SessionStub:
    def __init__(self, queries=None):
        self._queries = list(queries or [])

    def query(self, *_args, **_kwargs):
        if self._queries:
            return self._queries.pop(0)
        return _QueryStub()


@contextmanager
def _auto_commit():
    yield


def _fake_db(session):
    return SimpleNamespace(session=session, auto_commit=lambda: _auto_commit())


def test_system_knowledge_service_should_require_admin_context(monkeypatch):
    admin_user_id = uuid4()
    embedding_model_id = uuid4()
    service = SystemKnowledgeService(
        db=_fake_db(_SessionStub([_QueryStub(one_or_none_result=None)])),
        retrieval_service=SimpleNamespace(),
        icon_generator_service=SimpleNamespace(),
    )
    created = []
    monkeypatch.setattr(
        service,
        "create",
        lambda model, **kwargs: created.append((model, kwargs)) or SimpleNamespace(**kwargs),
    )
    monkeypatch.setattr(
        service,
        "auto_select_embedding_model",
        lambda: SimpleNamespace(id=embedding_model_id),
    )
    updated = []
    monkeypatch.setattr(
        service,
        "update",
        lambda kb, **kwargs: updated.append(kwargs) or kb,
    )

    result = service.create_system_knowledge(
        name="平台规则",
        admin_user=SimpleNamespace(id=admin_user_id),
        description="平台统一规则",
    )

    assert created[0][0] is KnowledgeBase
    assert result.knowledge_scope == "system"
    assert result.owner_account_id is None
    assert result.owner_admin_user_id == admin_user_id
    assert result.operation_context == "admin"
    assert updated == [{"embedding_model_id": embedding_model_id}]

    with pytest.raises(ForbiddenException):
        service.create_system_knowledge(name="非法系统知识", admin_user=None)


def test_user_content_service_should_create_home_upload_as_user_content(monkeypatch):
    account_id = uuid4()
    admin_user_id = uuid4()
    service = UserContentKnowledgeService(
        db=_fake_db(_SessionStub([_QueryStub(one_or_none_result=None)])),
        retrieval_service=SimpleNamespace(),
        icon_generator_service=SimpleNamespace(),
    )
    monkeypatch.setattr(service, "create", lambda _model, **kwargs: SimpleNamespace(**kwargs))

    result = service.create_home_upload_base(
        name="管理员个人上传",
        account=SimpleNamespace(id=account_id),
        admin_user=SimpleNamespace(id=admin_user_id, account_id=account_id),
    )

    assert result.knowledge_scope == "user_content"
    assert result.owner_account_id == account_id
    assert result.owner_admin_user_id is None
    assert result.operation_context == "user"
    assert result.created_from == "manual_upload"


def test_user_content_service_should_list_authorized_system_and_current_user_bases():
    account_id = uuid4()
    other_account_id = uuid4()
    system_base = SimpleNamespace(
        id=uuid4(), name="系统", knowledge_scope="system", owner_account_id=None, enabled=True
    )
    own_base = SimpleNamespace(
        id=uuid4(), name="我的资料", knowledge_scope="user_content", owner_account_id=account_id, enabled=True
    )
    other_base = SimpleNamespace(
        id=uuid4(), name="别人资料", knowledge_scope="user_content", owner_account_id=other_account_id, enabled=True
    )
    service = UserContentKnowledgeService(
        db=_fake_db(_SessionStub([_QueryStub(all_result=[system_base, own_base, other_base])])),
        retrieval_service=SimpleNamespace(),
        icon_generator_service=SimpleNamespace(),
    )

    result = service.list_authorized_bases(SimpleNamespace(id=account_id))

    assert [base.name for base in result] == ["系统", "我的资料"]
