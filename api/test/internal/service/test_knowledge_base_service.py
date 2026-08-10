from contextlib import contextmanager
from types import SimpleNamespace
from uuid import uuid4

import pytest

from internal.exception import ForbiddenException, NotFoundException
from internal.model import ExternalDataSource, KnowledgeBase, UserMemory
from internal.service.knowledge_base_service import KnowledgeBaseService


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


def _new_service(session=None):
    return KnowledgeBaseService(
        db=_fake_db(session or _SessionStub()),
        retrieval_service=SimpleNamespace(),
        icon_generator_service=SimpleNamespace(),
    )


def test_admin_user_context_should_create_user_content_for_own_account(monkeypatch):
    account_id = uuid4()
    admin_user_id = uuid4()
    service = _new_service(_SessionStub([_QueryStub(one_or_none_result=None)]))
    created = []
    monkeypatch.setattr(service, "create", lambda model, **kwargs: created.append((model, kwargs)) or SimpleNamespace(**kwargs))

    result = service.create_user_content_base(
        name="个人资料库",
        account=SimpleNamespace(id=account_id),
        admin_user=SimpleNamespace(id=admin_user_id, account_id=account_id),
        operation_context="user",
        created_from="manual_upload",
    )

    assert result.knowledge_scope == "user_content"
    assert result.owner_account_id == account_id
    assert result.owner_admin_user_id is None
    assert result.operation_context == "user"
    assert created[0][0] is KnowledgeBase


def test_admin_config_context_should_create_system_base_with_admin_owner(monkeypatch):
    admin_user_id = uuid4()
    service = _new_service(_SessionStub([_QueryStub(one_or_none_result=None)]))
    monkeypatch.setattr(service, "create", lambda _model, **kwargs: SimpleNamespace(**kwargs))

    result = service.create_system_base(
        name="系统级操作知识",
        admin_user=SimpleNamespace(id=admin_user_id),
        created_from="admin_config",
    )

    assert result.knowledge_scope == "system"
    assert result.owner_account_id is None
    assert result.owner_admin_user_id == admin_user_id
    assert result.operation_context == "admin"
    assert result.visibility_scope == "internal"


def test_regular_user_should_not_create_system_base():
    service = _new_service()

    with pytest.raises(ForbiddenException):
        service.create_system_base(name="非法系统库", admin_user=None, created_from="manual_upload")


def test_user_should_not_read_other_user_content():
    owner_id = uuid4()
    other_id = uuid4()
    base = SimpleNamespace(id=uuid4(), knowledge_scope="user_content", owner_account_id=owner_id)
    service = _new_service()
    service.get = lambda *_args, **_kwargs: base

    with pytest.raises(NotFoundException):
        service.get_accessible_base(base.id, SimpleNamespace(id=other_id))


def test_user_should_not_read_disabled_knowledge_base():
    account_id = uuid4()
    base = SimpleNamespace(
        id=uuid4(),
        knowledge_scope="user_content",
        owner_account_id=account_id,
        enabled=False,
    )
    service = _new_service()
    service.get = lambda *_args, **_kwargs: base

    with pytest.raises(NotFoundException):
        service.get_accessible_base(base.id, SimpleNamespace(id=account_id))


def test_user_should_read_own_memory_and_content():
    account_id = uuid4()
    memory_base = SimpleNamespace(id=uuid4(), knowledge_scope="user_memory", owner_account_id=account_id)
    content_base = SimpleNamespace(id=uuid4(), knowledge_scope="user_content", owner_account_id=account_id)
    service = _new_service()

    service.get = lambda _model, base_id: memory_base if base_id == memory_base.id else content_base

    assert service.get_accessible_base(memory_base.id, SimpleNamespace(id=account_id)) is memory_base
    assert service.get_accessible_base(content_base.id, SimpleNamespace(id=account_id)) is content_base


def test_core_models_should_expose_phase1_fields():
    account_id = uuid4()
    admin_user_id = uuid4()
    base = KnowledgeBase(
        name="资料库",
        knowledge_scope="user_content",
        owner_account_id=account_id,
        owner_admin_user_id=admin_user_id,
        operation_context="admin",
        visibility_scope="private",
        target_tenant_id=uuid4(),
        target_project_id=uuid4(),
        created_from="manual_upload",
    )
    memory = UserMemory(
        owner_account_id=account_id,
        memory_type="preference",
        content="用户偏好中文回答",
        confidence=3,
        status="active",
        created_from="conversation_memory",
    )
    source = ExternalDataSource(
        owner_account_id=account_id,
        knowledge_base_id=uuid4(),
        source_type="notion",
        authorization_status="pending",
        sync_status="idle",
    )

    assert base.knowledge_scope == "user_content"
    assert memory.created_from == "conversation_memory"
    assert source.source_type == "notion"


def test_create_base_should_persist_operation_context_in_settings(monkeypatch):
    service = _new_service(_SessionStub([_QueryStub(one_or_none_result=None)]))
    created = []
    monkeypatch.setattr(
        service,
        "create",
        lambda model, **kwargs: created.append((model, kwargs)) or SimpleNamespace(**kwargs),
    )

    service.create_user_content_base(
        name="个人库",
        account=SimpleNamespace(id=uuid4()),
        operation_context="user",
    )

    kwargs = created[0][1]
    assert kwargs["operation_context"] == "user"
    assert kwargs["settings"]["operation_context"] == "user"
