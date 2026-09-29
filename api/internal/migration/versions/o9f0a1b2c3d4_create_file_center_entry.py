"""create file_center_entry table

Revision ID: o9f0a1b2c3d4
Revises: n8d9e0f1a2b3
Create Date: 2026-09-30 00:00:00.000000

用户文件中心：在既有存储抽象（RuntimeStorageProxy）与回收站（RecycleBinService）之上，
新增「组织层」虚拟目录树。物理对象与删除语义均复用既有链路，本迁移只建表 + 索引。
"""
from alembic import op
import sqlalchemy as sa


revision = "o9f0a1b2c3d4"
down_revision = "n8d9e0f1a2b3"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "file_center_entry",
        sa.Column("id", sa.UUID(), nullable=False, server_default=sa.text("uuid_generate_v4()")),
        sa.Column("account_id", sa.UUID(), nullable=False),
        sa.Column("parent_id", sa.UUID(), nullable=True),
        sa.Column("name", sa.String(512), nullable=False, server_default=sa.text("''::character varying")),
        sa.Column("is_folder", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("upload_file_id", sa.UUID(), nullable=True),
        sa.Column("source", sa.String(32), nullable=False, server_default=sa.text("'upload'::character varying")),
        sa.Column("origin", sa.String(32), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP(0)")),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP(0)")),
        sa.PrimaryKeyConstraint("id", name="pk_file_center_entry_id"),
    )
    op.create_index("ix_file_center_entry_account_parent", "file_center_entry", ["account_id", "parent_id"])
    op.create_index("ix_file_center_entry_upload_file", "file_center_entry", ["upload_file_id"])
    op.create_index(
        "uq_file_center_entry_root_name",
        "file_center_entry",
        ["account_id", "name"],
        unique=True,
        postgresql_where=sa.text("parent_id IS NULL"),
    )
    op.create_index(
        "uq_file_center_entry_child_name",
        "file_center_entry",
        ["account_id", "parent_id", "name"],
        unique=True,
        postgresql_where=sa.text("parent_id IS NOT NULL"),
    )


def downgrade():
    op.drop_index("uq_file_center_entry_child_name", table_name="file_center_entry")
    op.drop_index("uq_file_center_entry_root_name", table_name="file_center_entry")
    op.drop_index("ix_file_center_entry_upload_file", table_name="file_center_entry")
    op.drop_index("ix_file_center_entry_account_parent", table_name="file_center_entry")
    op.drop_table("file_center_entry")
