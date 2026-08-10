"""内容存储配置模型。

Admin 端运行时切换存储后端的基础：``storage_config`` 表记录各存储后端
（local / cos / oss）的配置项与激活状态。新上传文件使用激活后端，
历史文件按 ``upload_file.storage_backend`` 字段路由访问。
"""
from datetime import UTC, datetime

from sqlalchemy import (
    UUID,
    Boolean,
    Column,
    DateTime,
    Index,
    JSON,
    PrimaryKeyConstraint,
    String,
    text,
)

from pkg.sqlalchemy import Base


def _utcnow_naive() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


class StorageConfig(Base):
    __tablename__ = "storage_config"
    __table_args__ = (
        PrimaryKeyConstraint("id", name="pk_storage_config_id"),
        Index("ix_storage_config_is_active", "is_active"),
    )

    id = Column(UUID, nullable=False, server_default=text("uuid_generate_v4()"))
    # 存储后端：local / cos / oss
    backend = Column(String(32), nullable=False, server_default=text("'local'::character varying"))
    # 后端配置项（JSON）：COS_SECRET_ID/COS_BUCKET/OSS_ENDPOINT 等
    configs = Column(JSON, nullable=False, server_default=text("'{}'::json"))
    # 是否启用：同一时间仅一个后端可激活
    is_active = Column(Boolean, nullable=False, server_default=text("false"))
    created_at = Column(DateTime, nullable=False, server_default=text("CURRENT_TIMESTAMP(0)"))
    updated_at = Column(
        DateTime,
        nullable=False,
        server_default=text("CURRENT_TIMESTAMP(0)"),
        server_onupdate=text("CURRENT_TIMESTAMP(0)"),
        default=_utcnow_naive,
    )
