"""create sandbox_config table

Revision ID: k5a6b7c8d9e0
Revises: j4e5f6a7b8c1
Create Date: 2026-09-29 00:00:00.000000

沙箱配置治理：把沙箱从「散读 env」收敛为「admin 可配 + 多后端热切换」。
本迁移只做 DDL + 权限种子；初始激活状态由 `SandboxConfigService.ensure_default_config()`
在启动时依当前 env 幂等补齐（保证升级瞬间行为零变化）。
"""
from alembic import op
import sqlalchemy as sa


revision = "k5a6b7c8d9e0"
down_revision = "j4e5f6a7b8c1"
branch_labels = None
depends_on = None


PERMISSIONS = [
    ("sandbox:read", "sandbox", "read", "查看沙箱配置"),
    ("sandbox:update", "sandbox", "update", "管理沙箱配置与后端切换"),
]


def upgrade():
    conn = op.get_bind()

    # 1. 创建 sandbox_config 表
    op.create_table(
        "sandbox_config",
        sa.Column("id", sa.UUID(), nullable=False, server_default=sa.text("uuid_generate_v4()")),
        sa.Column("capability", sa.String(32), nullable=False, server_default=sa.text("''")),
        sa.Column("backend", sa.String(32), nullable=False, server_default=sa.text("''")),
        sa.Column("label", sa.String(64), nullable=False, server_default=sa.text("''")),
        sa.Column("configs", sa.JSON(), nullable=False, server_default=sa.text("'{}'::json")),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP(0)")),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP(0)")),
        sa.PrimaryKeyConstraint("id", name="pk_sandbox_config_id"),
        sa.UniqueConstraint("capability", "backend", name="uq_sandbox_config_capability_backend"),
    )
    op.create_index(
        "ix_sandbox_config_capability_is_active",
        "sandbox_config",
        ["capability", "is_active"],
    )

    # 2. 权限种子
    for code, resource, action, name in PERMISSIONS:
        conn.execute(
            sa.text(
                "INSERT INTO permission (id, code, name, resource, action, description) "
                "VALUES (uuid_generate_v4(), :code, :name, :resource, :action, '') "
                "ON CONFLICT (code) DO NOTHING"
            ),
            {"code": code, "name": name, "resource": resource, "action": action},
        )

    # 3. 给 super_admin 角色授权
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

    # 2. 删除权限（只增不删的 initialize_defaults 会残留孤儿行，故显式清理）
    for code, _, _, _ in PERMISSIONS:
        conn.execute(sa.text("DELETE FROM permission WHERE code = :code"), {"code": code})

    # 3. 删除 sandbox_config 表
    op.drop_index("ix_sandbox_config_capability_is_active", table_name="sandbox_config")
    op.drop_table("sandbox_config")
