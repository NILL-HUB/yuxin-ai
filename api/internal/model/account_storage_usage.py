"""账号存储用量计量模型。

缓存每个账号已用存储字节数，避免每次上传都全表 SUM(upload_file.size)。
上传 / 删除 / 回收站清理 / 物理销毁时同步增减。
"""
from datetime import UTC, datetime

from sqlalchemy import (
    BigInteger,
    Column,
    DateTime,
    ForeignKey,
    PrimaryKeyConstraint,
    UUID,
    UniqueConstraint,
    text,
)

from pkg.sqlalchemy import Base


def _utcnow_naive() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


class AccountStorageUsage(Base):
    __tablename__ = "account_storage_usage"
    __table_args__ = (
        PrimaryKeyConstraint("id", name="pk_account_storage_usage_id"),
        UniqueConstraint("account_id", name="uq_account_storage_usage_account_id"),
    )

    id = Column(UUID, nullable=False, server_default=text("uuid_generate_v4()"))
    account_id = Column(UUID, ForeignKey("account.id", ondelete="CASCADE"), nullable=False)
    # 已用字节数，BigInteger 支持 TB 级
    used_bytes = Column(BigInteger, nullable=False, server_default=text("0"))
    updated_at = Column(
        DateTime,
        nullable=False,
        server_default=text("CURRENT_TIMESTAMP(0)"),
        server_onupdate=text("CURRENT_TIMESTAMP(0)"),
        default=_utcnow_naive,
    )
    created_at = Column(DateTime, nullable=False, server_default=text("CURRENT_TIMESTAMP(0)"))
