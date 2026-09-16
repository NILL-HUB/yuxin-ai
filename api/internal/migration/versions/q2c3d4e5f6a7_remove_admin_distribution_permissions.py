"""remove admin distribution permissions

Revision ID: q2c3d4e5f6a7
Revises: p1a2b3c4d5e6
Create Date: 2026-09-14 00:00:00.000000

管理端分销能力已下线：分销上下级绑定是**用户端独有**功能，管理员账号不得与
用户端混用（管理员若需使用分销应走用户端注册账号）。管理端只保留管理后端内容
的能力（订单/售后/提现/支付配置，以及「编排控制」里的 ENABLE_DISTRIBUTION 开关）。

本迁移清理 `distribution:view` / `distribution:manage` 两个权限点及其角色绑定。

背景（为什么必须写这条迁移）：`AdminRbacService.initialize_defaults()` 是
**只增不删**的幂等补齐——从 `PERMISSION_CATALOG` 移除权限点后，DB 里的
`permission` 行与 `role_permission` 绑定不会被自动清理，会形成孤儿权限。
历史同类案例见 `n8c9d0e1f2a3_drop_app_assignment`（该迁移删表却漏删权限点）。

downgrade 会按原定义重建权限点并重新授予 super_admin，便于回滚（自定义角色的
历史绑定不恢复）。
"""
from alembic import op
from sqlalchemy import text

revision = "q2c3d4e5f6a7"
down_revision = "p1a2b3c4d5e6"
branch_labels = None
depends_on = None

_REMOVED_PERMISSIONS = [
    ("distribution:view", "distribution", "view", "查看分销管理"),
    ("distribution:manage", "distribution", "manage", "管理分销关系"),
]


def upgrade():
    conn = op.get_bind()

    # 先删角色绑定，再删权限点（role_permission.permission_id 有 FK 约束）
    codes = tuple(code for code, _res, _act, _name in _REMOVED_PERMISSIONS)
    removed_bindings = conn.execute(
        text(
            "DELETE FROM role_permission WHERE permission_id IN "
            "(SELECT id FROM permission WHERE code = ANY(:codes))"
        ),
        {"codes": list(codes)},
    ).rowcount
    removed_permissions = conn.execute(
        text("DELETE FROM permission WHERE code = ANY(:codes)"),
        {"codes": list(codes)},
    ).rowcount

    print(
        f"[migration] 移除管理端分销权限：{removed_permissions} 个权限点、"
        f"{removed_bindings} 条角色绑定"
    )


def downgrade():
    conn = op.get_bind()

    # 1) 重建权限点（幂等）
    for code, resource, action, name in _REMOVED_PERMISSIONS:
        conn.execute(
            text(
                "INSERT INTO permission (id, code, name, resource, action, description, "
                "updated_at, created_at) "
                "VALUES (uuid_generate_v4(), :code, :name, :resource, :action, :description, "
                "NOW(), NOW()) "
                "ON CONFLICT (code) DO NOTHING"
            ),
            {
                "code": code,
                "name": name,
                "resource": resource,
                "action": action,
                "description": name,
            },
        )

    # 2) 重新授予 super_admin（系统保留角色，运行时本就会获得全量权限）
    conn.execute(
        text(
            "INSERT INTO role_permission (role_id, permission_id, created_at) "
            "SELECT r.id, p.id, NOW() FROM role r CROSS JOIN permission p "
            "WHERE r.code = 'super_admin' AND p.code = ANY(:codes) "
            "ON CONFLICT (role_id, permission_id) DO NOTHING"
        ),
        {"codes": [code for code, _res, _act, _name in _REMOVED_PERMISSIONS]},
    )

    print("[migration] 已恢复管理端分销权限点与 super_admin 授权")
