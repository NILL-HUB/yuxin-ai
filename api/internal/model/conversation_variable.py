from datetime import UTC, datetime
from sqlalchemy import (
    Column,
    UUID,
    String,
    DateTime,
    ForeignKeyConstraint,
    PrimaryKeyConstraint,
    Index,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB

from internal.extension.database_extension import db


def _utcnow_naive() -> datetime:
    """返回无时区的 UTC 时间，兼容数据库 DateTime 列且避免 utcnow 退化警告。"""
    return datetime.now(UTC).replace(tzinfo=None)


class ConversationVariable(db.Model):
    """会话变量持久化表，存储跨轮次共享的变量。

    用于 Plan B 的 VariablePool 持久化层：
    - Workflow 应用类型在执行工作流时产生会话变量
    - 变量在会话内持久化，跨轮次可读写
    - 支持 string/int/float/boolean/json 五种类型
    """
    __tablename__ = "conversation_variable"
    __table_args__ = (
        PrimaryKeyConstraint("id", name="pk_conversation_variable_id"),
        ForeignKeyConstraint(
            ["conversation_id"], ["conversation.id"],
            name="fk_conversation_variable_conversation_id_conversation",
            ondelete="CASCADE",
        ),
        Index("conversation_variable_conversation_id_idx", "conversation_id"),
        Index("conversation_variable_name_idx", "conversation_id", "name", unique=True),
    )

    id = Column(UUID, nullable=False, server_default=text("uuid_generate_v4()"))
    conversation_id = Column(UUID, nullable=False)  # 关联会话id
    name = Column(String(255), nullable=False)  # 变量名
    value_type = Column(String(32), nullable=False, server_default=text("'string'::character varying"))  # 值类型
    value = Column(JSONB, nullable=False, server_default=text("'null'::jsonb"))  # 值（JSONB 存储）
    updated_at = Column(
        DateTime,
        nullable=False,
        server_default=text("CURRENT_TIMESTAMP(0)"),
        server_onupdate=text("CURRENT_TIMESTAMP(0)"),
        default=_utcnow_naive,
    )
    created_at = Column(DateTime, nullable=False, default=_utcnow_naive, server_default=text("CURRENT_TIMESTAMP(0)"))
