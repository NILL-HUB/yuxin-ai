"""管理端 Agent 的会话与消息服务（设计 §10.1）。

只做会话/消息的持久化，不感知 LLM 与板块工具。

归属校验的边界：**只有** ``get_conversation`` / ``list_conversations`` 提供
归属过滤；``append_message`` / ``list_messages`` 只按 ``conversation_id`` 读写，
**不自行校验归属**——调用方必须先调 ``get_conversation``（完成校验）再落/读消息，
否则可能写入或读到他人会话。

服务层契约为 UUID：``conversation_id`` / ``admin_agent_id`` / ``admin_user_id``
均为 ``UUID``；路由层负责用 ``UUID(str(...))`` 归一化后再传入（传字符串会与 UUID 列
比较恒不相等，导致合法属主被误判为无权）。
"""
from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from injector import inject

from internal.entity.admin_agent_chat_entity import AdminAgentMessageRole
from internal.exception import ForbiddenException, NotFoundException
from internal.model import AdminAgentConversation, AdminAgentMessage
from pkg.sqlalchemy import SQLAlchemy


@inject
@dataclass
class AdminAgentConversationService:
    """管理端 Agent 会话 / 消息的持久化与归属校验。"""

    db: SQLAlchemy

    def list_conversations(
        self, *, admin_agent_id: UUID, admin_user_id: UUID
    ) -> list[AdminAgentConversation]:
        """列出某管理员在某 Agent 下的**未删除**会话。"""
        return (
            self.db.session.query(AdminAgentConversation)
            .filter_by(admin_agent_id=admin_agent_id, admin_user_id=admin_user_id, is_deleted=False)
            .order_by(AdminAgentConversation.updated_at.desc())
            .all()
        )

    def get_conversation(
        self, conversation_id: UUID, *, admin_user_id: UUID
    ) -> AdminAgentConversation:
        """按 id 读取会话并校验归属（软删会话视为不存在）。

        对齐 P1 admin 侧 403/404 契约：不存在抛 ``NotFoundException``（404），
        非属主抛 ``ForbiddenException``（403）——**接受**由此带来的可探测性
        （他人可据状态码差异推断该会话是否存在）。

        与 ``ConversationService.get_conversation`` 的差异：后者对"不存在 /
        非属主 / 已删除"统一抛 ``NotFoundException``，不泄露存在性；admin 侧为
        对齐既有 403/404 契约而保留差异，若要收敛探测面需同时改路由与前端。
        """
        conversation = (
            self.db.session.query(AdminAgentConversation)
            .filter_by(id=conversation_id, is_deleted=False)
            .one_or_none()
        )
        if conversation is None:
            raise NotFoundException("会话不存在")
        if conversation.admin_user_id != admin_user_id:
            raise ForbiddenException("无权访问该会话")
        return conversation

    def create_conversation(
        self, *, admin_agent_id: UUID, admin_user_id: UUID, title: str = ""
    ) -> AdminAgentConversation:
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
        conversation_id: UUID,
        role: str,
        content: str = "",
        tool_calls=None,
    ) -> AdminAgentMessage:
        """追加一条消息。

        **不校验归属**：调用方需先经 ``get_conversation`` 完成归属校验。
        """
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

    def list_messages(self, *, conversation_id: UUID) -> list[AdminAgentMessage]:
        """按会话读取消息，``created_at`` 升序。

        **不校验归属**：调用方需先经 ``get_conversation`` 完成归属校验。

        排序依赖 ``created_at``：经 ORM 写入时走模型的 Python ``default``
        （``_utcnow_naive``，**微秒**精度），故常规路径下同轮消息顺序稳定；
        但该列**无 tiebreaker**（未按 ``id`` 兜底），若出现同微秒写入或
        绕过 ORM 的 raw SQL（回退到 ``CURRENT_TIMESTAMP(0)`` 秒级 server_default），
        相对顺序即不保证。需要严格顺序的调用方应自行二次排序。
        """
        return (
            self.db.session.query(AdminAgentMessage)
            .filter_by(conversation_id=conversation_id)
            .order_by(AdminAgentMessage.created_at.asc())
            .all()
        )
