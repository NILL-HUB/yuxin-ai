"""系统资源回收站表。

所有 admin 可管理的系统资源删除时先进入回收站（软删除 + 快照），
由定时任务在留存期到期后彻底物理销毁；回收站不可手动清空，仅管理员可查看/恢复。
"""
from datetime import datetime, timezone

from sqlalchemy import (
    Column,
    DateTime,
    Index,
    Integer,
    PrimaryKeyConstraint,
    String,
    Text,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB

from pkg.sqlalchemy import Base


def _utcnow_naive() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


class RecycleBin(Base):
    __tablename__ = "recycle_bin"
    __table_args__ = (
        PrimaryKeyConstraint("id", name="pk_recycle_bin_id"),
        Index("recycle_bin_status_idx", "status"),
        Index("recycle_bin_expire_idx", "status", "expire_at"),
        Index("recycle_bin_resource_idx", "resource_type", "resource_id"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    # 资源类型：knowledge_base / system_prompt / app / workflow / skill / mcp / api_tool
    resource_type = Column(String(64), nullable=False)
    # 原资源主键（UUID 或字符串键）
    resource_id = Column(String(128), nullable=False)
    # 资源业务键（system_prompt 时为 prompt_key，其余为 UUID 字符串）
    resource_key = Column(String(128), nullable=False, server_default=text("''::character varying"))
    # 展示名称（删除时的名称，便于恢复后识别）
    resource_name = Column(String(255), nullable=False, server_default=text("''::character varying"))
    # 删除时的完整快照（JSONB，恢复时回填）
    snapshot = Column(JSONB, nullable=False, server_default=text("'{}'::jsonb"))
    # 操作管理员 ID（deleted_by_type=user 时为用户账号 ID）
    deleted_by = Column(String(64), nullable=True)
    # 删除来源：admin=管理员删除 / user=用户侧删除（用户删除默认留存 30 天，仅管理员可见/恢复）
    deleted_by_type = Column(String(16), nullable=False, server_default=text("'admin'::character varying"))
    # 删除时间
    deleted_at = Column(DateTime, nullable=False, server_default=text("CURRENT_TIMESTAMP(0)"), default=_utcnow_naive)
    # 留存天数
    retention_days = Column(Integer, nullable=False, server_default=text("30"))
    # 到期销毁时间（deleted_at + retention_days）
    expire_at = Column(DateTime, nullable=False)
    # 状态：pending=待销毁 / restored=已恢复 / expired=已销毁
    status = Column(String(32), nullable=False, server_default=text("'pending'::character varying"))
    # 销毁/恢复说明（失败原因等）
    remark = Column(Text, nullable=False, server_default=text("''::text"))
    updated_at = Column(
        DateTime,
        nullable=False,
        server_default=text("CURRENT_TIMESTAMP(0)"),
        default=_utcnow_naive,
        onupdate=_utcnow_naive,
    )
