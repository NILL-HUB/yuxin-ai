"""seed admin commerce and distribution permissions

Revision ID: fe1a2b3c4d5e
Revises: c0e1d2f3a4b6
Create Date: 2026-08-28 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


revision = 'fe1a2b3c4d5e'
down_revision = 'c0e1d2f3a4b6'
branch_labels = None
depends_on = None


PERMISSIONS = [
    ("distribution:view", "distribution", "view", "查看分销管理"),
    ("distribution:manage", "distribution", "manage", "管理分销关系"),
    ("order:view", "order", "view", "查看订单管理"),
    ("order:manage", "order", "manage", "管理订单"),
    ("refund:view", "refund", "view", "查看售后管理"),
    ("refund:manage", "refund", "manage", "审核退款"),
    ("withdraw:view", "withdraw", "view", "查看提现审核"),
    ("withdraw:manage", "withdraw", "manage", "审核提现"),
    ("payment_config:read", "payment_config", "read", "查看支付配置"),
    ("payment_config:manage", "payment_config", "manage", "管理支付配置"),
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