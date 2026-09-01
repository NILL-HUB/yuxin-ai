"""seed system_config permissions

Revision ID: i3d4e5f6a9b8
Revises: h2c3d4e5f6a8
Create Date: 2026-09-01 00:00:00.000000

邮件/短信通道改为 DB 配置后，admin 邮件发送配置（/admin/mail-config）
由支持层映射到 system_config:manage；此处将 system_config:manage/read
登记进 permission 目录并授予 super_admin（super_admin 亦通过
c1d2e3f4a5b6 同步迁移按 all_permission_codes 授权，此处双保险幂等）。
"""
from alembic import op
import sqlalchemy as sa

from internal.core.rbac import PERMISSION_CATALOG


revision = "i3d4e5f6a9b8"
down_revision = "h2c3d4e5f6a8"
branch_labels = None
depends_on = None


PERMISSION_CODES = {"system_config:read", "system_config:manage"}


def upgrade():
    conn = op.get_bind()

    for spec in PERMISSION_CATALOG:
        if spec.code not in PERMISSION_CODES:
            continue
        conn.execute(
            sa.text(
                "INSERT INTO permission (id, code, name, resource, action, description) "
                "VALUES (uuid_generate_v4(), :code, :name, :resource, :action, :description) "
                "ON CONFLICT (code) DO UPDATE SET "
                "name = EXCLUDED.name, resource = EXCLUDED.resource, "
                "action = EXCLUDED.action, description = EXCLUDED.description"
            ),
            {
                "code": spec.code,
                "name": spec.name,
                "resource": spec.resource,
                "action": spec.action,
                "description": spec.description,
            },
        )

    super_admin_role_id = conn.execute(
        sa.text("SELECT id FROM role WHERE code = 'super_admin'")
    ).scalar_one_or_none()

    if super_admin_role_id is not None:
        for code in PERMISSION_CODES:
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

    super_admin_role_id = conn.execute(
        sa.text("SELECT id FROM role WHERE code = 'super_admin'")
    ).scalar_one_or_none()

    if super_admin_role_id is not None:
        for code in PERMISSION_CODES:
            conn.execute(
                sa.text(
                    "DELETE FROM role_permission "
                    "WHERE role_id = :role_id "
                    "AND permission_id = (SELECT id FROM permission WHERE code = :code)"
                ),
                {"role_id": super_admin_role_id, "code": code},
            )

    for code in PERMISSION_CODES:
        conn.execute(
            sa.text("DELETE FROM permission WHERE code = :code"),
            {"code": code},
        )
