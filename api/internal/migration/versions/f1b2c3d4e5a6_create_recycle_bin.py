"""create recycle_bin table

Revision ID: f1b2c3d4e5a6
Revises: e0a1b2c3d4e5
Create Date: 2026-08-06 00:00:00.000000

系统资源回收站：所有 admin 可管理的系统资源删除时先进入回收站，
留存期到期后由定时任务彻底销毁；回收站不可手动清空，仅管理员可查看/恢复。
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "f1b2c3d4e5a6"
down_revision = "e0a1b2c3d4e5"
branch_labels = None
depends_on = None


PERMISSIONS = [
    ("recycle_bin:read", "recycle_bin", "read", "查看系统资源回收站"),
    ("recycle_bin:write", "recycle_bin", "write", "恢复系统资源回收站条目"),
]


def upgrade():
    op.create_table(
        "recycle_bin",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("resource_type", sa.String(length=64), nullable=False),
        sa.Column("resource_id", sa.String(length=128), nullable=False),
        sa.Column("resource_key", sa.String(length=128), server_default=sa.text("''::character varying"), nullable=False),
        sa.Column("resource_name", sa.String(length=255), server_default=sa.text("''::character varying"), nullable=False),
        sa.Column("snapshot", postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'{}'::jsonb"), nullable=False),
        sa.Column("deleted_by", sa.String(length=64), nullable=True),
        sa.Column("deleted_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP(0)"), nullable=False),
        sa.Column("retention_days", sa.Integer(), server_default=sa.text("30"), nullable=False),
        sa.Column("expire_at", sa.DateTime(), nullable=False),
        sa.Column("status", sa.String(length=32), server_default=sa.text("'pending'::character varying"), nullable=False),
        sa.Column("remark", sa.Text(), server_default=sa.text("''::text"), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP(0)"), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_recycle_bin_id"),
    )
    op.create_index("recycle_bin_status_idx", "recycle_bin", ["status"])
    op.create_index("recycle_bin_expire_idx", "recycle_bin", ["status", "expire_at"])
    op.create_index("recycle_bin_resource_idx", "recycle_bin", ["resource_type", "resource_id"])

    # seed 回收站权限（super_admin 角色）
    conn = op.get_bind()
    for code, resource, action, name in PERMISSIONS:
        conn.execute(
            sa.text(
                "INSERT INTO permission (id, code, name, resource, action, description) "
                "VALUES (uuid_generate_v4(), :code, :name, :resource, :action, '') "
                "ON CONFLICT (code) DO NOTHING"
            ),
            {"code": code, "name": name, "resource": resource, "action": action},
        )
    super_admin_role_id = conn.execute(
        sa.text("SELECT id FROM role WHERE code = 'super_admin'")
    ).scalar_one_or_none()
    if super_admin_role_id is not None:
        for code, _, _, _ in PERMISSIONS:
            conn.execute(
                sa.text(
                    "INSERT INTO role_permission (role_id, permission_id) "
                    "SELECT :role_id, p.id FROM permission p "
                    "WHERE p.code = :code "
                    "ON CONFLICT (role_id, permission_id) DO NOTHING"
                ),
                {"role_id": super_admin_role_id, "code": code},
            )


def downgrade():
    op.drop_index("recycle_bin_resource_idx", table_name="recycle_bin")
    op.drop_index("recycle_bin_expire_idx", table_name="recycle_bin")
    op.drop_index("recycle_bin_status_idx", table_name="recycle_bin")
    op.drop_table("recycle_bin")

    conn = op.get_bind()
    codes = [p[0] for p in PERMISSIONS]
    super_admin_role_id = conn.execute(
        sa.text("SELECT id FROM role WHERE code = 'super_admin'")
    ).scalar_one_or_none()
    if super_admin_role_id is not None:
        for code in codes:
            conn.execute(
                sa.text(
                    "DELETE FROM role_permission "
                    "WHERE role_id = :role_id "
                    "AND permission_id = (SELECT id FROM permission WHERE code = :code)"
                ),
                {"role_id": super_admin_role_id, "code": code},
            )
    for code in codes:
        conn.execute(
            sa.text("DELETE FROM permission WHERE code = :code"),
            {"code": code},
        )
