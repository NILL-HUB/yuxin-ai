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
        # 预置 Agent 的幂等键：同一管理员下同一 builtin_key 至多一条。
        # 为什么是**部分**唯一索引：自建 Agent 的 builtin_key 为 NULL，
        # 全表唯一会让"多个 NULL"在 PostgreSQL 下虽可行、但语义含糊，
        # 且日后若改用其他方言会踩 NULL 唯一陷阱。
        Index(
            "admin_agent_owner_builtin_uniq",
            "owner_admin_user_id",
            "builtin_key",
            unique=True,
            postgresql_where=text("builtin_key IS NOT NULL"),
        ),
    )

    id = Column(UUID, nullable=False, server_default=text("uuid_generate_v4()"))
    owner_admin_user_id = Column(UUID, nullable=False)
    name = Column(String(255), nullable=False, server_default=text("''::character varying"))
    description = Column(Text, nullable=False, server_default=text("''::text"))
    # 绑定的提示词 key（FK → prompt_template.key），为空时用内置默认
    prompt_key = Column(String(128), nullable=True)
    # 预置（内置）Agent 的稳定标识；自建 Agent 为 NULL
    builtin_key = Column(String(64), nullable=True)
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
