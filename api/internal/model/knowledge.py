from datetime import UTC, datetime

from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Index, Integer, PrimaryKeyConstraint, String, Text, UUID, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import relationship

from internal.extension.database_extension import db


def _utcnow_naive() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


class KnowledgeBase(db.Model):
    __tablename__ = "knowledge_base"
    __table_args__ = (
        PrimaryKeyConstraint("id", name="pk_knowledge_base_id"),
        Index("knowledge_base_scope_idx", "knowledge_scope"),
        Index("knowledge_base_owner_account_scope_idx", "owner_account_id", "knowledge_scope"),
        Index("knowledge_base_owner_admin_scope_idx", "owner_admin_user_id", "knowledge_scope"),
        Index("knowledge_base_target_tenant_idx", "target_tenant_id"),
        Index("knowledge_base_target_project_idx", "target_project_id"),
    )

    id = Column(UUID, nullable=False, server_default=text("uuid_generate_v4()"))
    name = Column(String(255), nullable=False, server_default=text("''::character varying"))
    description = Column(Text, nullable=False, server_default=text("''::text"))
    knowledge_scope = Column(String(64), nullable=False, server_default=text("'user_content'::character varying"))
    owner_account_id = Column(UUID, ForeignKey("account.id"), nullable=True)
    owner_admin_user_id = Column(UUID, ForeignKey("admin_user.id"), nullable=True)
    operation_context = Column(String(64), nullable=False, server_default=text("'user'::character varying"))
    visibility_scope = Column(String(64), nullable=False, server_default=text("'private'::character varying"))
    target_tenant_id = Column(UUID, nullable=True)
    target_project_id = Column(UUID, nullable=True)
    created_from = Column(String(64), nullable=False, server_default=text("'manual_upload'::character varying"))
    settings = Column(JSONB, nullable=False, server_default=text("'{}'::jsonb"))
    enabled = Column(Boolean, nullable=False, server_default=text("true"))
    updated_at = Column(DateTime, nullable=False, server_default=text("CURRENT_TIMESTAMP(0)"), server_onupdate=text("CURRENT_TIMESTAMP(0)"), default=_utcnow_naive)
    created_at = Column(DateTime, nullable=False, server_default=text("CURRENT_TIMESTAMP(0)"))

    owner_account = relationship("Account", foreign_keys=[owner_account_id], lazy="joined")
    owner_admin_user = relationship("AdminUser", foreign_keys=[owner_admin_user_id], lazy="joined")


class KnowledgeDocument(db.Model):
    __tablename__ = "knowledge_document"
    __table_args__ = (
        PrimaryKeyConstraint("id", name="pk_knowledge_document_id"),
        Index("knowledge_document_base_id_idx", "knowledge_base_id"),
        Index("knowledge_document_owner_account_idx", "owner_account_id"),
        Index("knowledge_document_source_idx", "source_type", "source_id"),
        Index("knowledge_document_status_idx", "status"),
    )

    id = Column(UUID, nullable=False, server_default=text("uuid_generate_v4()"))
    knowledge_base_id = Column(UUID, ForeignKey("knowledge_base.id"), nullable=False)
    owner_account_id = Column(UUID, ForeignKey("account.id"), nullable=True)
    name = Column(String(255), nullable=False, server_default=text("''::character varying"))
    content_type = Column(String(64), nullable=False, server_default=text("'document'::character varying"))
    source_type = Column(String(64), nullable=False, server_default=text("'manual_upload'::character varying"))
    source_id = Column(String(255), nullable=False, server_default=text("''::character varying"))
    upload_file_id = Column(UUID, nullable=True)
    metadata_ = Column("metadata", JSONB, nullable=False, server_default=text("'{}'::jsonb"))
    character_count = Column(Integer, nullable=False, server_default=text("0"))
    token_count = Column(Integer, nullable=False, server_default=text("0"))
    status = Column(String(64), nullable=False, server_default=text("'waiting'::character varying"))
    error = Column(Text, nullable=False, server_default=text("''::text"))
    updated_at = Column(DateTime, nullable=False, server_default=text("CURRENT_TIMESTAMP(0)"), server_onupdate=text("CURRENT_TIMESTAMP(0)"), default=_utcnow_naive)
    created_at = Column(DateTime, nullable=False, server_default=text("CURRENT_TIMESTAMP(0)"))

    knowledge_base = relationship("KnowledgeBase", lazy="joined")


class KnowledgeSegment(db.Model):
    __tablename__ = "knowledge_segment"
    __table_args__ = (
        PrimaryKeyConstraint("id", name="pk_knowledge_segment_id"),
        Index("knowledge_segment_base_id_idx", "knowledge_base_id"),
        Index("knowledge_segment_document_id_idx", "knowledge_document_id"),
        Index("knowledge_segment_owner_account_idx", "owner_account_id"),
        Index("knowledge_segment_status_idx", "status"),
    )

    id = Column(UUID, nullable=False, server_default=text("uuid_generate_v4()"))
    knowledge_base_id = Column(UUID, ForeignKey("knowledge_base.id"), nullable=False)
    knowledge_document_id = Column(UUID, ForeignKey("knowledge_document.id"), nullable=False)
    owner_account_id = Column(UUID, ForeignKey("account.id"), nullable=True)
    position = Column(Integer, nullable=False, server_default=text("1"))
    content = Column(Text, nullable=False, server_default=text("''::text"))
    keywords = Column(JSONB, nullable=False, server_default=text("'[]'::jsonb"))
    metadata_ = Column("metadata", JSONB, nullable=False, server_default=text("'{}'::jsonb"))
    character_count = Column(Integer, nullable=False, server_default=text("0"))
    token_count = Column(Integer, nullable=False, server_default=text("0"))
    hit_count = Column(Integer, nullable=False, server_default=text("0"))
    status = Column(String(64), nullable=False, server_default=text("'waiting'::character varying"))
    enabled = Column(Boolean, nullable=False, server_default=text("true"))
    updated_at = Column(DateTime, nullable=False, server_default=text("CURRENT_TIMESTAMP(0)"), server_onupdate=text("CURRENT_TIMESTAMP(0)"), default=_utcnow_naive)
    created_at = Column(DateTime, nullable=False, server_default=text("CURRENT_TIMESTAMP(0)"))

    knowledge_base = relationship("KnowledgeBase", lazy="joined")
    knowledge_document = relationship("KnowledgeDocument", lazy="joined")


class UserMemory(db.Model):
    __tablename__ = "user_memory"
    __table_args__ = (
        PrimaryKeyConstraint("id", name="pk_user_memory_id"),
        Index("user_memory_owner_type_idx", "owner_account_id", "memory_type"),
        Index("user_memory_status_idx", "status"),
    )

    id = Column(UUID, nullable=False, server_default=text("uuid_generate_v4()"))
    owner_account_id = Column(UUID, ForeignKey("account.id"), nullable=False)
    memory_type = Column(String(64), nullable=False, server_default=text("'preference'::character varying"))
    content = Column(Text, nullable=False, server_default=text("''::text"))
    confidence = Column(Integer, nullable=False, server_default=text("0"))
    status = Column(String(64), nullable=False, server_default=text("'active'::character varying"))
    created_from = Column(String(64), nullable=False, server_default=text("'conversation_memory'::character varying"))
    metadata_ = Column("metadata", JSONB, nullable=False, server_default=text("'{}'::jsonb"))
    embedding_node_id = Column(String(255), nullable=True)
    scope = Column(String(64), nullable=False, server_default=text("'global'::character varying"))
    source_conversation_ids = Column(JSONB, nullable=False, server_default=text("'[]'::jsonb"))
    last_used_at = Column(DateTime, nullable=True)
    updated_at = Column(DateTime, nullable=False, server_default=text("CURRENT_TIMESTAMP(0)"), server_onupdate=text("CURRENT_TIMESTAMP(0)"), default=_utcnow_naive)
    created_at = Column(DateTime, nullable=False, server_default=text("CURRENT_TIMESTAMP(0)"))


class MemoryCandidate(db.Model):
    __tablename__ = "memory_candidate"
    __table_args__ = (
        PrimaryKeyConstraint("id", name="pk_memory_candidate_id"),
        Index("memory_candidate_owner_key_idx", "owner_account_id", "candidate_key"),
        Index("memory_candidate_status_idx", "status"),
    )

    id = Column(UUID, nullable=False, server_default=text("uuid_generate_v4()"))
    owner_account_id = Column(UUID, ForeignKey("account.id"), nullable=False)
    candidate_key = Column(String(255), nullable=False, server_default=text("''::character varying"))
    content = Column(Text, nullable=False, server_default=text("''::text"))
    confidence = Column(Integer, nullable=False, server_default=text("0"))
    occurrences = Column(Integer, nullable=False, server_default=text("1"))
    status = Column(String(64), nullable=False, server_default=text("'pending'::character varying"))
    memory_type = Column(String(64), nullable=False, server_default=text("'preference'::character varying"))
    source_conversation_id = Column(UUID, nullable=True)
    extracted_at = Column(DateTime, nullable=True)
    metadata_ = Column("metadata", JSONB, nullable=False, server_default=text("'{}'::jsonb"))
    updated_at = Column(DateTime, nullable=False, server_default=text("CURRENT_TIMESTAMP(0)"), server_onupdate=text("CURRENT_TIMESTAMP(0)"), default=_utcnow_naive)
    created_at = Column(DateTime, nullable=False, server_default=text("CURRENT_TIMESTAMP(0)"))


class ExternalDataSource(db.Model):
    __tablename__ = "external_data_source"
    __table_args__ = (
        PrimaryKeyConstraint("id", name="pk_external_data_source_id"),
        Index("external_data_source_owner_type_idx", "owner_account_id", "source_type"),
        Index("external_data_source_base_id_idx", "knowledge_base_id"),
        Index("external_data_source_auth_status_idx", "authorization_status"),
        Index("external_data_source_sync_status_idx", "sync_status"),
    )

    id = Column(UUID, nullable=False, server_default=text("uuid_generate_v4()"))
    owner_account_id = Column(UUID, ForeignKey("account.id"), nullable=True)
    owner_admin_user_id = Column(UUID, ForeignKey("admin_user.id"), nullable=True)
    knowledge_base_id = Column(UUID, ForeignKey("knowledge_base.id"), nullable=True)
    source_type = Column(String(64), nullable=False)
    source_name = Column(String(255), nullable=False, server_default=text("''::character varying"))
    authorization_status = Column(String(64), nullable=False, server_default=text("'pending'::character varying"))
    sync_status = Column(String(64), nullable=False, server_default=text("'idle'::character varying"))
    sync_cursor = Column(String(1024), nullable=False, server_default=text("''::character varying"))
    last_synced_at = Column(DateTime, nullable=True)
    last_error = Column(Text, nullable=False, server_default=text("''::text"))
    config = Column(JSONB, nullable=False, server_default=text("'{}'::jsonb"))
    updated_at = Column(DateTime, nullable=False, server_default=text("CURRENT_TIMESTAMP(0)"), server_onupdate=text("CURRENT_TIMESTAMP(0)"), default=_utcnow_naive)
    created_at = Column(DateTime, nullable=False, server_default=text("CURRENT_TIMESTAMP(0)"))

    knowledge_base = relationship("KnowledgeBase", lazy="joined")
