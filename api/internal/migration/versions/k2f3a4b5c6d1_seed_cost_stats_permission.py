"""seed cost stats permission

Revision ID: k2f3a4b5c6d1
Revises: j1e2f3a4b5c0
Create Date: 2026-07-01 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


revision = 'k2f3a4b5c6d1'
down_revision = 'j1e2f3a4b5c0'
branch_labels = None
depends_on = None


PERMISSIONS = [
    ("cost_stats:read", "cost_stats", "read", "查看成本统计"),
]


def upgrade():
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
