"""create storage_config table

Revision ID: a1b2c3d4e5f7
Revises: f1b2c3d4e5a6
Create Date: 2026-08-01 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


revision = 'a1b2c3d4e5f7'
down_revision = 'f1b2c3d4e5a6'
branch_labels = None
depends_on = None


PERMISSIONS = [
    ("storage:read", "storage", "read", "查看内容存储配置"),
    ("storage:update", "storage", "update", "管理内容存储配置与文件"),
]


def upgrade():
    conn = op.get_bind()

    # 1. 创建 storage_config 表
    op.create_table(
        "storage_config",
        sa.Column("id", sa.UUID(), nullable=False, server_default=sa.text("uuid_generate_v4()")),
        sa.Column("backend", sa.String(32), nullable=False, server_default=sa.text("'local'")),
        sa.Column("configs", sa.JSON(), nullable=False, server_default=sa.text("'{}'::json")),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP(0)")),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP(0)")),
        sa.PrimaryKeyConstraint("id", name="pk_storage_config_id"),
    )
    op.create_index("ix_storage_config_is_active", "storage_config", ["is_active"])

    # 2. 给 upload_file 表加 storage_backend 字段
    op.add_column(
        "upload_file",
        sa.Column("storage_backend", sa.String(32), nullable=True),
    )
    op.create_index("ix_upload_file_storage_backend", "upload_file", ["storage_backend"])

    # 3. 插入权限种子
    for code, resource, action, name in PERMISSIONS:
        conn.execute(
            sa.text(
                "INSERT INTO permission (id, code, name, resource, action, description) "
                "VALUES (uuid_generate_v4(), :code, :name, :resource, :action, '') "
                "ON CONFLICT (code) DO NOTHING"
            ),
            {"code": code, "name": name, "resource": resource, "action": action},
        )

    # 4. 给 super_admin 角色授权
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
    conn = op.get_bind()

    # 1. 移除 super_admin 角色权限
    super_admin_role_id = conn.execute(
        sa.text("SELECT id FROM role WHERE code = 'super_admin'")
    ).scalar_one_or_none()

    if super_admin_role_id is not None:
        for code, _, _, _ in PERMISSIONS:
            conn.execute(
                sa.text(
                    "DELETE FROM role_permission "
                    "WHERE role_id = :role_id "
                    "AND permission_id = (SELECT id FROM permission WHERE code = :code)"
                ),
                {"role_id": super_admin_role_id, "code": code},
            )

    # 2. 删除权限
    for code, _, _, _ in PERMISSIONS:
        conn.execute(sa.text("DELETE FROM permission WHERE code = :code"), {"code": code})

    # 3. 删除 upload_file.storage_backend 字段
    op.drop_index("ix_upload_file_storage_backend", table_name="upload_file")
    op.drop_column("upload_file", "storage_backend")

    # 4. 删除 storage_config 表
    op.drop_index("ix_storage_config_is_active", table_name="storage_config")
    op.drop_table("storage_config")
