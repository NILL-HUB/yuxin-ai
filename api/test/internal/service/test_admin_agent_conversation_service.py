"""管理端 Agent 会话服务测试：归属隔离 + 消息追加/读取顺序。

归属隔离是安全边界：非创建者**不可**读写他人 Agent 的会话
（与 `AdminAgentService.get_agent` 同口径，设计 §2「仅创建者可用」）。
"""
from types import SimpleNamespace
from uuid import uuid4

import pytest

from internal.exception import ForbiddenException, NotFoundException
from internal.service.admin_agent_conversation_service import (
    AdminAgentConversationService,
)


class _Query:
    def __init__(self, rows):
        self._rows = list(rows)

    def filter_by(self, **kwargs):
        self._kwargs = kwargs
        return self

    def filter(self, *args, **kwargs):
        return self

    def order_by(self, *args, **kwargs):
        return self

    def one_or_none(self):
        return self._rows[0] if self._rows else None

    def all(self):
        return list(self._rows)


class _Session:
    def __init__(self, rows):
        self._rows = rows
        self.added = []

    def query(self, model):
        return _Query(self._rows)

    def add(self, obj):
        self.added.append(obj)


class _AutoCommit:
    def __enter__(self):
        return None

    def __exit__(self, *exc):
        return False


def _service(rows):
    service = AdminAgentConversationService.__new__(AdminAgentConversationService)
    session = _Session(rows)
    service.db = SimpleNamespace(session=session, auto_commit=lambda: _AutoCommit())
    service.session = session
    return service


def test_get_conversation_rejects_foreign_admin():
    owner = uuid4()
    conv = SimpleNamespace(id=uuid4(), admin_agent_id=uuid4(), admin_user_id=owner)
    service = _service([conv])

    with pytest.raises(ForbiddenException):
        service.get_conversation(conv.id, admin_user_id=uuid4())

    assert service.get_conversation(conv.id, admin_user_id=owner) is conv


def test_missing_conversation_raises_not_found():
    service = _service([])

    with pytest.raises(NotFoundException):
        service.get_conversation(uuid4(), admin_user_id=uuid4())


def test_create_conversation_persists_owner_and_title():
    admin_id = uuid4()
    agent_id = uuid4()
    service = _service([])

    conversation = service.create_conversation(
        admin_agent_id=agent_id, admin_user_id=admin_id, title="看看现状"
    )

    assert conversation.admin_agent_id == agent_id
    assert conversation.admin_user_id == admin_id
    assert conversation.title == "看看现状"
    assert len(service.session.added) == 1, "必须落库"


def test_append_message_persists_role_and_tool_calls():
    service = _service([])

    message = service.append_message(
        conversation_id=uuid4(),
        role="assistant",
        content="好的",
        tool_calls=[{"name": "admin_builtin_tool", "args": {"action": "list"}}],
    )

    assert message.role == "assistant"
    assert message.content == "好的"
    assert message.tool_calls[0]["name"] == "admin_builtin_tool"
    assert len(service.session.added) == 1


def test_append_message_rejects_illegal_role():
    service = _service([])

    with pytest.raises(ValueError):
        service.append_message(conversation_id=uuid4(), role="robot", content="x")
