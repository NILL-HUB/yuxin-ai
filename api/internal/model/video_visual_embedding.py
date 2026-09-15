"""视觉向量表（关键帧跨模态检索）。

独立于 knowledge_segment_embedding_{dim} 的原因：
1. 视觉编码模型的输入是「图文混合」（input={"image": ...} 或对象数组），
   与文本 embedding 的裸字符串入参不兼容；
2. 该表的生命周期跟随素材解析（重解析即清空重建），与文本片段向量不同步；
3. 维度和文本 embedding 无关。

维度固定为 VISUAL_EMBEDDING_DIMENSION：
Qwen3-VL-Embedding-8B 原生 4096 维，超出 pgvector 的 vector 类型上限 2000，
需经 MRL 降维到 1536（本项目主维度，与文本 embedding 分表惯例一致）。
"""
from datetime import UTC, datetime

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    Column,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    PrimaryKeyConstraint,
    String,
    UniqueConstraint,
    UUID,
    text,
)

from pkg.sqlalchemy import Base

# 视觉向量维度：4096 原生维度经 MRL 降到 pgvector 上限内，且对齐本项目主维度
VISUAL_EMBEDDING_DIMENSION = 1536


def _utcnow_naive() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


class VideoVisualEmbedding(Base):
    """关键帧视觉向量。

    文本与图片在本模型的语义空间中是对齐的，因此文本 query 可直接与
    本表的图片向量比对（跨模态召回），无需额外的融合排序层。
    """

    __tablename__ = "video_visual_embedding"
    __table_args__ = (
        PrimaryKeyConstraint("id", name="pk_video_visual_embedding_id"),
        UniqueConstraint("segment_id", name="uq_video_visual_embedding_segment"),
        Index("video_visual_embedding_kb_idx", "knowledge_base_id"),
        Index("video_visual_embedding_document_idx", "knowledge_document_id"),
        Index("video_visual_embedding_account_idx", "account_id"),
    )

    id = Column(UUID, nullable=False, server_default=text("uuid_generate_v4()"))
    account_id = Column(UUID, nullable=False)
    knowledge_base_id = Column(
        UUID, ForeignKey("knowledge_base.id", ondelete="CASCADE"), nullable=False
    )
    knowledge_document_id = Column(
        UUID, ForeignKey("knowledge_document.id", ondelete="CASCADE"), nullable=False
    )
    segment_id = Column(
        UUID, ForeignKey("knowledge_segment.id", ondelete="CASCADE"), nullable=False
    )
    # 帧文件在对象存储中的 key（对应 UploadFile.key），供「改细节」定位画面
    frame_url = Column(String(512), nullable=False, server_default=text("''::character varying"))
    # 帧在该视频中的序号（从 1 开始），与 Segment.metadata.scene_index 对齐
    scene_index = Column(Integer, nullable=False, server_default=text("0"))
    # 生成该向量的模型 id（便于换模型后重建）
    model_id = Column(String(36), nullable=True)
    embedding = Column(Vector(VISUAL_EMBEDDING_DIMENSION), nullable=False)
    updated_at = Column(
        DateTime,
        nullable=False,
        server_default=text("CURRENT_TIMESTAMP(0)"),
        server_onupdate=text("CURRENT_TIMESTAMP(0)"),
        default=_utcnow_naive,
    )
    created_at = Column(DateTime, nullable=False, server_default=text("CURRENT_TIMESTAMP(0)"))
