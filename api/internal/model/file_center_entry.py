"""用户文件中心条目（虚拟目录树）。

每个账号一棵目录树：节点分 folder / file 两类；file 节点 1:1 指向一个 UploadFile。
物理对象归 RuntimeStorageProxy、删除/恢复归 RecycleBinService——本表只做「组织层」。

`upload_file_id` **不加外键约束**：回收站删除 upload_file 后本节点需保留、恢复时再挂回；
若加外键，悬挂引用会阻塞 upload_file 的物理删除。
"""
from datetime import UTC, datetime

from sqlalchemy import (
    UUID,
    Boolean,
    Column,
    DateTime,
    Index,
    PrimaryKeyConstraint,
    String,
    text,
)

from pkg.sqlalchemy import Base


def _utcnow_naive() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


class FileCenterEntry(Base):
    __tablename__ = "file_center_entry"
    __table_args__ = (
        PrimaryKeyConstraint("id", name="pk_file_center_entry_id"),
        Index("ix_file_center_entry_account_parent", "account_id", "parent_id"),
        Index("ix_file_center_entry_upload_file", "upload_file_id"),
        Index(
            "uq_file_center_entry_root_name",
            "account_id",
            "name",
            unique=True,
            postgresql_where=text("parent_id IS NULL"),
        ),
        Index(
            "uq_file_center_entry_child_name",
            "account_id",
            "parent_id",
            "name",
            unique=True,
            postgresql_where=text("parent_id IS NOT NULL"),
        ),
    )

    id = Column(UUID, nullable=False, server_default=text("uuid_generate_v4()"))
    account_id = Column(UUID, nullable=False)
    parent_id = Column(UUID, nullable=True)
    name = Column(String(512), nullable=False, server_default=text("''::character varying"))
    is_folder = Column(Boolean, nullable=False, server_default=text("false"))
    upload_file_id = Column(UUID, nullable=True)
    source = Column(String(32), nullable=False, server_default=text("'upload'::character varying"))
    origin = Column(String(32), nullable=True)
    created_at = Column(DateTime, nullable=False, server_default=text("CURRENT_TIMESTAMP(0)"))
    updated_at = Column(
        DateTime,
        nullable=False,
        server_default=text("CURRENT_TIMESTAMP(0)"),
        server_onupdate=text("CURRENT_TIMESTAMP(0)"),
        default=_utcnow_naive,
    )
