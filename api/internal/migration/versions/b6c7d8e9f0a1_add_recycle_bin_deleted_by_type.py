"""add recycle_bin.deleted_by_type

Revision ID: b6c7d8e9f0a1
Revises: d1e2f3a4b5e6
Create Date: 2026-08-08 00:00:00.000000

区分回收站条目来源：admin=管理员删除（删除时提示并选择留存天数）；
user=用户侧删除（静默进入回收站，默认留存 30 天，内容从用户视角消失，仅管理员可见/恢复）。

存量数据均为管理员删除路径，默认值 admin 兼容。
"""
from alembic import op
import sqlalchemy as sa


revision = "b6c7d8e9f0a1"
down_revision = "d1e2f3a4b5e6"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "recycle_bin",
        sa.Column(
            "deleted_by_type",
            sa.String(length=16),
            server_default=sa.text("'admin'::character varying"),
            nullable=False,
        ),
    )
    op.create_index(
        "recycle_bin_deleted_by_type_idx",
        "recycle_bin",
        ["deleted_by_type"],
    )


def downgrade():
    op.drop_index("recycle_bin_deleted_by_type_idx", table_name="recycle_bin")
    op.drop_column("recycle_bin", "deleted_by_type")
