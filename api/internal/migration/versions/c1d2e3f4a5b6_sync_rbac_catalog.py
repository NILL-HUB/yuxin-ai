"""sync rbac catalog and default role grants

Revision ID: c1d2e3f4a5b6
Revises: c9d8e7f6a5b4
Create Date: 2026-08-17 00:00:00.000000

权限目录与默认角色以 internal/core/rbac.py 为单一事实源，
此迁移将存量库中的 permission/role/role_permission 同步到最新目录。
"""

from alembic import op
import sqlalchemy as sa

from internal.core.rbac import (
    DEFAULT_ROLES,
    PERMISSION_CATALOG,
    SUPER_ADMIN_ROLE_CODE,
    all_permission_codes,
)


revision = "c1d2e3f4a5b6"
down_revision = "c9d8e7f6a5b4"
branch_labels = None
depends_on = None


def upgrade():
    conn = op.get_bind()

    for spec in PERMISSION_CATALOG:
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

    for role_spec in DEFAULT_ROLES:
        conn.execute(
            sa.text(
                "INSERT INTO role (id, code, name, description, is_system) "
                "VALUES (uuid_generate_v4(), :code, :name, :description, true) "
                "ON CONFLICT (code) DO UPDATE SET "
                "name = EXCLUDED.name, description = EXCLUDED.description, is_system = true"
            ),
            {
                "code": role_spec.code,
                "name": role_spec.name,
                "description": role_spec.description,
            },
        )

    for role_spec in DEFAULT_ROLES:
        target_codes = (
            list(all_permission_codes())
            if role_spec.code == SUPER_ADMIN_ROLE_CODE
            else list(role_spec.permission_codes)
        )
        for code in target_codes:
            conn.execute(
                sa.text(
                    "INSERT INTO role_permission (role_id, permission_id) "
                    "SELECT r.id, p.id FROM role r, permission p "
                    "WHERE r.code = :role_code AND p.code = :permission_code "
                    "ON CONFLICT (role_id, permission_id) DO NOTHING"
                ),
                {"role_code": role_spec.code, "permission_code": code},
            )


def downgrade():
    # 数据同步迁移：仅新增/更新目录与授权，不删除存量数据，降级为空操作。
    pass
