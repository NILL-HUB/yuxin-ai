"""管理端 Agent 会话服务测试：归属隔离 + 过滤 / 排序真实生效。

归属隔离是安全边界：非创建者**不可**读写他人 Agent 的会话
（与 `AdminAgentService.get_agent` 同口径，设计 §2「仅创建者可用」）。

注意：query 替身会**真实应用 `filter_by` 条件与 `order_by` 排序**，而不是
"忽略参数直接 `return self`"的空壳——否则删掉 `is_deleted=False` 过滤、
漏掉 owner 条件或把升序写反，测试依然全绿（假通过）。
"""
from datetime import datetime
from types import SimpleNamespace
from uuid import uuid4

import pytest
from sqlalchemy.sql import operators

from internal.exception import ForbiddenException, NotFoundException
from internal.service.admin_agent_conversation_service import (
    AdminAgentConversationService,
)


class _Query:
    """会真实应用 `filter_by` 条件与 `order_by` 排序的 query 替身。"""

    def __init__(self, rows):
        self._rows = list(rows)
        self.filter_by_kwargs = None
        self.order_by_calls = 0

    def filter_by(self, **kwargs):
        self.filter_by_kwargs = dict(kwargs)
        self._rows = [
            row
            for row in self._rows
            if all(getattr(row, key, None) == value for key, value in kwargs.items())
        ]
        return self

    def filter(self, *args, **kwargs):
        return self

    def order_by(self, *criteria):
        self.order_by_calls += 1
        for criterion in criteria:
            key = getattr(getattr(criterion, "element", None), "key", None)
            if key is None:
                continue
            reverse = getattr(criterion, "modifier", None) is operators.desc_op
            self._rows.sort(key=lambda row: getattr(row, key), reverse=reverse)
        return self

    def one_or_none(self):
        return self._rows[0] if self._rows else None

    def all(self):
        return list(self._rows)


class _Session:
    def __init__(self, rows):
        self._rows = rows
        self.added = []
        self.last_query = None

    def query(self, model):
        self.last_query = _Query(self._rows)
        return self.last_query

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


def _conversation(admin_user_id, admin_agent_id, *, is_deleted=False, updated_at=None):
    return SimpleNamespace(
        id=uuid4(),
        admin_agent_id=admin_agent_id,
        admin_user_id=admin_user_id,
        is_deleted=is_deleted,
        updated_at=updated_at or datetime(2026, 1, 1),
    )


def _message(conversation_id, created_at):
    return SimpleNamespace(
        id=uuid4(),
        conversation_id=conversation_id,
        role="user",
        content="",
        created_at=created_at,
    )


class TestGetConversation:
    def test_rejects_foreign_admin(self):
        owner = uuid4()
        conv = _conversation(owner, uuid4())
        service = _service([conv])

        with pytest.raises(ForbiddenException):
            service.get_conversation(conv.id, admin_user_id=uuid4())

        assert service.get_conversation(conv.id, admin_user_id=owner) is conv

    def test_missing_conversation_raises_not_found(self):
        service = _service([])

        with pytest.raises(NotFoundException):
            service.get_conversation(uuid4(), admin_user_id=uuid4())

    def test_hides_soft_deleted_conversation(self):
        """软删会话视为不存在：过滤必须带 is_deleted=False（与 list 同口径）。"""
        owner = uuid4()
        conv = _conversation(owner, uuid4(), is_deleted=True)
        service = _service([conv])

        with pytest.raises(NotFoundException):
            service.get_conversation(conv.id, admin_user_id=owner)

        assert service.session.last_query.filter_by_kwargs == {
            "id": conv.id,
            "is_deleted": False,
        }


class TestCreateConversation:
    def test_persists_owner_and_title(self):
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


class TestListConversations:
    def test_filters_by_owner_agent_and_not_deleted(self):
        """过滤条件必须同时含 owner / agent / is_deleted，且按 updated_at 排序。"""
        owner = uuid4()
        agent = uuid4()
        mine = _conversation(owner, agent)
        service = _service(
            [
                mine,
                _conversation(uuid4(), agent),               # 他人 owner
                _conversation(owner, agent, is_deleted=True),  # 已软删
                _conversation(owner, uuid4()),               # 同 owner 的其他 Agent
            ]
        )

        result = service.list_conversations(admin_agent_id=agent, admin_user_id=owner)

        assert result == [mine], "他人 owner / 已软删 / 其他 Agent 的会话都不得返回"
        assert service.session.last_query.filter_by_kwargs == {
            "admin_agent_id": agent,
            "admin_user_id": owner,
            "is_deleted": False,
        }
        assert service.session.last_query.order_by_calls == 1, "必须显式排序"


class TestAppendMessage:
    def test_persists_role_and_tool_calls(self):
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

    def test_rejects_illegal_role(self):
        service = _service([])

        with pytest.raises(ValueError):
            service.append_message(conversation_id=uuid4(), role="robot", content="x")


class TestListMessages:
    def test_orders_by_created_at_ascending(self):
        conversation_id = uuid4()
        second = _message(conversation_id, datetime(2026, 1, 1, 10, 0, 1))
        first = _message(conversation_id, datetime(2026, 1, 1, 10, 0, 0))
        third = _message(conversation_id, datetime(2026, 1, 1, 10, 0, 2))
        service = _service([second, first, third])

        result = service.list_messages(conversation_id=conversation_id)

        assert result == [first, second, third]
        assert service.session.last_query.filter_by_kwargs == {
            "conversation_id": conversation_id
        }
        assert service.session.last_query.order_by_calls == 1
