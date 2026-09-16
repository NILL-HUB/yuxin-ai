"""管理端 Agent 的会话与消息服务（设计 §10.1）。

只做会话/消息的持久化与归属校验，不感知 LLM 与板块工具。
"""
from __future__ import annotations

import logging

from internal.entity.admin_agent_chat_entity import AdminAgentMessageRole
from internal.exception import ForbiddenException, NotFoundException
from internal.model import AdminAgentConversation, AdminAgentMessage
from pkg.sqlalchemy import SQLAlchemy

logger = logging.getLogger(__name__)


class AdminAgentConversationService:
    """刻意不用 @inject @dataclass：只持有 db，便于测试直接构造。"""

    def __init__(self, db: SQLAlchemy):
        self.db = db

    def list_conversations(self, *, admin_agent_id, admin_user_id) -> list[AdminAgentConversation]:
        return (
            self.db.session.query(AdminAgentConversation)
            .filter_by(admin_agent_id=admin_agent_id, admin_user_id=admin_user_id, is_deleted=False)
            .order_by(AdminAgentConversation.updated_at.desc())
            .all()
        )

    def get_conversation(self, conversation_id, *, admin_user_id) -> AdminAgentConversation:
        conversation = (
            self.db.session.query(AdminAgentConversation)
            .filter_by(id=conversation_id)
            .one_or_none()
        )
        if conversation is None:
            raise NotFoundException("会话不存在")
        if conversation.admin_user_id != admin_user_id:
            # 与 AdminAgentService.get_agent 同口径：非属主一律视为不存在，
            # 避免通过"报错差异"探测他人 Agent 的会话是否存在。
            raise ForbiddenException("无权访问该会话")
        return conversation

    def create_conversation(self, *, admin_agent_id, admin_user_id, title: str = "") -> AdminAgentConversation:
        with self.db.auto_commit():
            conversation = AdminAgentConversation(
                admin_agent_id=admin_agent_id,
                admin_user_id=admin_user_id,
                title=(title or "")[:255],
            )
            self.db.session.add(conversation)
        return conversation

    def append_message(
        self,
        *,
        conversation_id,
        role: str,
        content: str = "",
        tool_calls=None,
    ) -> AdminAgentMessage:
        AdminAgentMessageRole(role)  # 非法 role 直接报错，不落库
        with self.db.auto_commit():
            message = AdminAgentMessage(
                conversation_id=conversation_id,
                role=role,
                content=content or "",
                tool_calls=list(tool_calls or []),
            )
            self.db.session.add(message)
        return message

    def list_messages(self, *, conversation_id) -> list[AdminAgentMessage]:
        return (
            self.db.session.query(AdminAgentMessage)
            .filter_by(conversation_id=conversation_id)
            .order_by(AdminAgentMessage.created_at.asc())
            .all()
        )
