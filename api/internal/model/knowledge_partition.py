"""知识库分区模型（两级树）。

一个知识库下的素材可归入分区；分区支持两级（大类 / 子类），
由服务层强制校验层级深度，parent_id 为空表示顶层分区。
"""
from datetime import UTC, datetime

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    PrimaryKeyConstraint,
    String,
    Text,
    UUID,
    UniqueConstraint,
    text,
)

from pkg.sqlalchemy import Base


def _utcnow_naive() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


class KnowledgePartition(Base):
    __tablename__ = "knowledge_partition"
    __table_args__ = (
        PrimaryKeyConstraint("id", name="pk_knowledge_partition_id"),
        UniqueConstraint("knowledge_base_id", "partition_key", name="uq_knowledge_partition_base_key"),
        Index("knowledge_partition_parent_id_idx", "parent_id"),
        Index("knowledge_partition_sort_idx", "knowledge_base_id", "sort_order"),
    )

    id = Column(UUID, nullable=False, server_default=text("uuid_generate_v4()"))
    knowledge_base_id = Column(UUID, ForeignKey("knowledge_base.id", ondelete="CASCADE"), nullable=False)
    name = Column(String(255), nullable=False, server_default=text("''::character varying"))
    # partition_key：分区业务键，日期模式为 2026-09 / 2026-09-12，自定义模式为 slug
    partition_key = Column(String(128), nullable=False, server_default=text("''::character varying"))
    # parent_id 为空表示顶层分区；两级树由服务层校验
    parent_id = Column(UUID, ForeignKey("knowledge_partition.id", ondelete="CASCADE"), nullable=True)
    description = Column(Text, nullable=False, server_default=text("''::text"))
    sort_order = Column(Integer, nullable=False, server_default=text("0"))
    enabled = Column(Boolean, nullable=False, server_default=text("true"))
    # 分区权限首版不做，字段预留：默认继承板块可见性
    visibility_scope = Column(String(64), nullable=False, server_default=text("'private'::character varying"))
    updated_at = Column(
        DateTime,
        nullable=False,
        server_default=text("CURRENT_TIMESTAMP(0)"),
        server_onupdate=text("CURRENT_TIMESTAMP(0)"),
        default=_utcnow_naive,
    )
    created_at = Column(DateTime, nullable=False, server_default=text("CURRENT_TIMESTAMP(0)"))
