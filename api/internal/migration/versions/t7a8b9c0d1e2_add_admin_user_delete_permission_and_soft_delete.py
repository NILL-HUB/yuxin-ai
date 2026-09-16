"""add admin_user delete permission and soft-delete columns

Revision ID: t7a8b9c0d1e2
Revises: r4e5f6a7b8c9
Create Date: 2026-09-16 00:00:00.000000

补齐管理员（admin_user）的删除能力——此前管理端只有 CRU + 状态管理
（read/create/update/disable/enable/reset-password/revoke-sessions），
**完全没有删除端点、权限点、服务方法与软删除列**，属系统性缺口。

本迁移做两件事：

1. 登记 `admin_user:delete` 权限点，并授予 `super_admin`。
   注意：`admin_user:*` 此前**仅 super_admin 实质持有**（运行时对 super_admin
   走 `all_permission_codes()` 短路，`DEFAULT_ROLES` 中无其它角色被授予），
   故这里只补 super_admin 绑定，与既有 `i3d4e5f6a9b8` 的 seed 范式一致
   （super_admin 走全量短路，此处属表内一致性双保险、幂等）。

2. `admin_user` 新增软删除三列（`deleted_at` / `deleted_by` / `deleted_reason`），
   对齐 `account` 表既有范式。

**为什么软删除而非物理删除**：`admin_user.id` 被 `admin_session`、
`admin_user_role`、`audit_log`、`knowledge_base.owner_admin_user_id`、
`external_data_source.owner_admin_user_id`、`app/workflow/api_tool_provider.created_by_admin`
等多处外键引用；物理删除会触发 FK 约束失败，且会丢失"谁曾拥有哪些权限"的
审计追溯能力。

守卫：test/internal/migration/test_migration_graph_integrity.py（单 head）、
test/internal/migration/test_migration_empty_db_smoke.py（空库可跑通）。
"""
from alembic import op
import sqlalchemy as sa

from internal.core.rbac import PERMISSION_CATALOG


revision = "t7a8b9c0d1e2"
down_revision = "r4e5f6a7b8c9"
branch_labels = None
depends_on = None


PERMISSION_CODES = {"admin_user:delete"}


def upgrade():
    conn = op.get_bind()

    # 1) 登记权限点（幂等 upsert）
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

    # 2) admin_user 软删除三列（幂等）
    conn.execute(
        sa.text(
            "ALTER TABLE admin_user "
            "ADD COLUMN IF NOT EXISTS deleted_at TIMESTAMP WITHOUT TIME ZONE"
        )
    )
    conn.execute(
        sa.text("ALTER TABLE admin_user ADD COLUMN IF NOT EXISTS deleted_by UUID")
    )
    conn.execute(
        sa.text(
            "ALTER TABLE admin_user "
            "ADD COLUMN IF NOT EXISTS deleted_reason VARCHAR(1024) NOT NULL "
            "DEFAULT ''::character varying"
        )
    )


def downgrade():
    conn = op.get_bind()

    # 1) 撤销 super_admin 绑定并删除权限点
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

    # 2) 回滚软删除列
    conn.execute(sa.text("ALTER TABLE admin_user DROP COLUMN IF EXISTS deleted_reason"))
    conn.execute(sa.text("ALTER TABLE admin_user DROP COLUMN IF EXISTS deleted_by"))
    conn.execute(sa.text("ALTER TABLE admin_user DROP COLUMN IF EXISTS deleted_at"))
