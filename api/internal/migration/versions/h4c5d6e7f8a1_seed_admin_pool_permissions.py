"""seed admin pool governance permissions

Revision ID: h4c5d6e7f8a1
Revises: g3b4c5d6e7f9
Create Date: 2026-06-23 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


revision = 'h4c5d6e7f8a1'
down_revision = 'g3b4c5d6e7f9'
branch_labels = None
depends_on = None


PERMISSIONS = [
    ("model_pool:read", "model_pool", "read", "查看模型池"),
    ("model_pool:manage", "model_pool", "manage", "管理模型池"),
    ("agent_pool:read", "agent_pool", "read", "查看智能体池"),
    ("agent_pool:manage", "agent_pool", "manage", "管理智能体池"),
    ("tool_governance:read", "tool_governance", "read", "查看工具治理"),
    ("tool_governance:manage", "tool_governance", "manage", "管理工具治理"),
    ("routing_log:read", "routing_log", "read", "查看路由日志"),
    ("routing_log:update", "routing_log", "update", "管理路由日志"),
    ("openapi:read", "openapi", "read", "查看开放API"),
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
