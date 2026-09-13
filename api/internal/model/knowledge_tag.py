"""知识库标签关联模型。

复用既有 Tag 模型（api/internal/model/tag.py），仅新增知识库/素材两级的
关联表，对齐既有 AppTag / WorkflowTag 的模式。
"""
from datetime import UTC, datetime

from sqlalchemy import (
    Column,
    DateTime,
    ForeignKey,
    Index,
    PrimaryKeyConstraint,
    UUID,
    UniqueConstraint,
    text,
)

from pkg.sqlalchemy import Base


def _utcnow_naive() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


class KnowledgeBaseTag(Base):
    """知识库（板块）标签关联。"""

    __tablename__ = "knowledge_base_tag"
    __table_args__ = (
        PrimaryKeyConstraint("id", name="pk_knowledge_base_tag_id"),
        UniqueConstraint("knowledge_base_id", "tag_id", name="uq_knowledge_base_tag_pair"),
        Index("knowledge_base_tag_base_idx", "knowledge_base_id"),
        Index("knowledge_base_tag_tag_idx", "tag_id"),
        Index("knowledge_base_tag_account_idx", "account_id"),
    )

    id = Column(UUID, nullable=False, server_default=text("uuid_generate_v4()"))
    account_id = Column(UUID, nullable=False)
    knowledge_base_id = Column(UUID, ForeignKey("knowledge_base.id"), nullable=False)
    tag_id = Column(UUID, ForeignKey("tag.id"), nullable=False)
    updated_at = Column(
        DateTime,
        nullable=False,
        server_default=text("CURRENT_TIMESTAMP(0)"),
        server_onupdate=text("CURRENT_TIMESTAMP(0)"),
        default=_utcnow_naive,
    )
    created_at = Column(DateTime, nullable=False, server_default=text("CURRENT_TIMESTAMP(0)"))


class KnowledgeDocumentTag(Base):
    """素材（文档）标签关联。"""

    __tablename__ = "knowledge_document_tag"
    __table_args__ = (
        PrimaryKeyConstraint("id", name="pk_knowledge_document_tag_id"),
        UniqueConstraint("knowledge_document_id", "tag_id", name="uq_knowledge_document_tag_pair"),
        Index("knowledge_document_tag_document_idx", "knowledge_document_id"),
        Index("knowledge_document_tag_tag_idx", "tag_id"),
        Index("knowledge_document_tag_account_idx", "account_id"),
    )

    id = Column(UUID, nullable=False, server_default=text("uuid_generate_v4()"))
    account_id = Column(UUID, nullable=False)
    knowledge_document_id = Column(UUID, ForeignKey("knowledge_document.id"), nullable=False)
    tag_id = Column(UUID, ForeignKey("tag.id"), nullable=False)
    updated_at = Column(
        DateTime,
        nullable=False,
        server_default=text("CURRENT_TIMESTAMP(0)"),
        server_onupdate=text("CURRENT_TIMESTAMP(0)"),
        default=_utcnow_naive,
    )
    created_at = Column(DateTime, nullable=False, server_default=text("CURRENT_TIMESTAMP(0)"))
