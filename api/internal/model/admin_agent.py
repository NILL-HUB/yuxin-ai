"""管理端 Agent 定义模型（设计 §10.1）。

与用户端 Agent（``app`` 表）完全独立：
- 归属 ``admin_user``，不归属 ``account``；
- 权限走三重交集（``granted_permissions``）；
- 自动化级别独立于权限（``automation_policy``）。
"""
from datetime import UTC, datetime

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    ForeignKeyConstraint,
    Index,
    PrimaryKeyConstraint,
    String,
    Text,
    UUID,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB

from pkg.sqlalchemy import Base


def _utcnow_naive() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


class AdminAgent(Base):
    __tablename__ = "admin_agent"
    __table_args__ = (
        PrimaryKeyConstraint("id", name="pk_admin_agent_id"),
        ForeignKeyConstraint(
            ["owner_admin_user_id"],
            ["admin_user.id"],
            name="fk_admin_agent_owner_admin_user_id_admin_user",
            ondelete="CASCADE",
        ),
        Index("admin_agent_owner_admin_user_id_idx", "owner_admin_user_id"),
        Index("admin_agent_enabled_idx", "enabled"),
    )

    id = Column(UUID, nullable=False, server_default=text("uuid_generate_v4()"))
    owner_admin_user_id = Column(UUID, nullable=False)
    name = Column(String(255), nullable=False, server_default=text("''::character varying"))
    description = Column(Text, nullable=False, server_default=text("''::text"))
    # 绑定的提示词 key（FK → prompt_template.key），为空时用内置默认
    prompt_key = Column(String(128), nullable=True)
    # 管理员显式下放给本 Agent 的权限子集（字符串数组）
    granted_permissions = Column(JSONB, nullable=False, server_default=text("'[]'::jsonb"))
    # 板块 → supervised / autonomous / blocked（§5.1）
    automation_policy = Column(JSONB, nullable=False, server_default=text("'{}'::jsonb"))
    # 预算闸门配置（§6.3），P4 落地，此处先建列
    budget_config = Column(JSONB, nullable=False, server_default=text("'{}'::jsonb"))
    enabled = Column(Boolean, nullable=False, server_default=text("true"))
    updated_at = Column(
        DateTime,
        nullable=False,
        server_default=text("CURRENT_TIMESTAMP(0)"),
        server_onupdate=text("CURRENT_TIMESTAMP(0)"),
        default=_utcnow_naive,
    )
    created_at = Column(
        DateTime,
        nullable=False,
        server_default=text("CURRENT_TIMESTAMP(0)"),
        default=_utcnow_naive,
    )
