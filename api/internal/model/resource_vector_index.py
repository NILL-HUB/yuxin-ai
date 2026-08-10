"""资源向量索引表。

统一存储模型/MCP工具/Skill/内置工具/API工具的向量索引，
供指挥官（选模型）和 Agent（选工具）做语义检索。

设计要点：
- 统一表 + resource_type 区分，避免为每种资源重复建表
- 固定 Vector(1024) 维度（系统默认 bge-m3），换 embedding 模型时重建索引
- 数据量小（几百条），顺序扫描 cosine distance 足够快，不需要 HNSW
- content_hash 增量更新，避免无意义的重向量
- sub_pool 字段支持按子池过滤检索（指挥官任务分类过滤）
"""
import uuid
from datetime import UTC, datetime

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Index,
    PrimaryKeyConstraint,
    String,
    Text,
    UniqueConstraint,
    UUID,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from pgvector.sqlalchemy import Vector

from pkg.sqlalchemy import Base


def _utcnow_naive() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


# 向量维度，与系统默认 embedding 模型一致（当前为 OpenAI text-embedding-3-small 1536 维）
# 换 embedding 模型时需修改此值 + 迁移脚本 + 重建索引
RESOURCE_VECTOR_DIMENSION = 1536

# 资源类型枚举
RESOURCE_TYPE_MODEL = "model"
RESOURCE_TYPE_MCP_TOOL = "mcp_tool"
RESOURCE_TYPE_SKILL = "skill"
RESOURCE_TYPE_BUILTIN_TOOL = "builtin_tool"
RESOURCE_TYPE_API_TOOL = "api_tool"


class ResourceVectorIndex(Base):
    """资源向量索引：统一存储各类资源的语义向量，供指挥官和 Agent 检索。"""
    __tablename__ = "resource_vector_index"
    __table_args__ = (
        PrimaryKeyConstraint("id", name="pk_resource_vector_index_id"),
        UniqueConstraint("resource_type", "resource_id", name="uq_resource_vector_index_type_id"),
        Index("resource_vector_index_type_idx", "resource_type"),
        Index("resource_vector_index_sub_pool_idx", "sub_pool"),
        Index("resource_vector_index_enabled_idx", "enabled"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, nullable=False)
    # 资源类型：model / mcp_tool / skill / builtin_tool / api_tool
    resource_type = Column(String(32), nullable=False)
    # 对应资源表的 id（UUID 字符串）
    resource_id = Column(String(64), nullable=False)
    # 资源名称（冗余，检索结果直接返回，避免二次查表）
    resource_name = Column(String(255), nullable=False, server_default=text("''::character varying"))
    # 描述（冗余，检索结果展示）
    description = Column(Text, nullable=False, server_default=text("''::text"))
    # 能力标签（冗余 JSONB，检索结果直接返回）
    capabilities = Column(JSONB, nullable=False, server_default=text("'[]'::jsonb"))
    # 子池名（general/coding/research/...，用于检索时过滤）
    sub_pool = Column(String(64), nullable=False, server_default=text("'general'::character varying"))
    # 额外元数据（如 tier/price/model_type/compatible_api 等）
    metadata_ = Column("metadata", JSONB, nullable=False, server_default=text("'{}'::jsonb"))
    # 向量（固定 1024 维）
    embedding = Column(Vector(RESOURCE_VECTOR_DIMENSION), nullable=True)
    # 记录用的哪个 embedding 模型
    embedding_model_id = Column(String(64), nullable=True)
    # 内容哈希（基于 description + capabilities + sub_pool，增量更新用）
    content_hash = Column(String(128), nullable=False, server_default=text("''::character varying"))
    enabled = Column(Boolean, nullable=False, server_default=text("true"))
    updated_at = Column(
        DateTime,
        nullable=False,
        server_default=text("CURRENT_TIMESTAMP(0)"),
        server_onupdate=text("CURRENT_TIMESTAMP(0)"),
        default=_utcnow_naive,
    )
    created_at = Column(DateTime, nullable=False, default=_utcnow_naive, server_default=text("CURRENT_TIMESTAMP(0)"))
