"""add desktop device registry table

Revision ID: l6a7b8c9d0e1
Revises: k5f6a7b8c9d0
Create Date: 2026-09-11 00:00:00.000000

桌面设备注册表：解决「服务端 → 宿主机 worker」调用断链。

背景：桌面端每次启动用 crypto.randomBytes 随机生成 worker/bridge token，
仅注入本机 worker 环境变量，服务端无从获知；服务端依赖静态配置的
DESKTOP_BRIDGE_URL/TOKEN，随机值永远对不上 → 对话里让 Agent 操作本机必然失败。

本表让桌面端登录后主动注册 bridge 地址与 token（密文），服务端按账号动态解析。
"""
from alembic import op
import sqlalchemy as sa

revision = "l6a7b8c9d0e1"
down_revision = "k5f6a7b8c9d0"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "desktop_device",
        sa.Column("id", sa.UUID(), primary_key=True, server_default=sa.text("uuid_generate_v4()")),
        sa.Column("device_id", sa.String(128), nullable=False),
        sa.Column("account_id", sa.UUID(), nullable=False),
        sa.Column("name", sa.String(128), nullable=False, server_default=sa.text("''::character varying")),
        sa.Column("platform", sa.String(32), nullable=False, server_default=sa.text("''::character varying")),
        sa.Column("bridge_origin", sa.String(255), nullable=False, server_default=sa.text("''::character varying")),
        sa.Column(
            "bridge_token_encrypted",
            sa.String(512),
            nullable=False,
            server_default=sa.text("''::character varying"),
        ),
        sa.Column("is_default", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("status", sa.String(16), nullable=False, server_default=sa.text("'online'::character varying")),
        sa.Column("last_seen_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP(0)")),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP(0)")),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP(0)")),
    )
    # 同一设备在账号内唯一（幂等 UPSERT 的依据）
    op.create_index(
        "desktop_device_account_device_uniq",
        "desktop_device",
        ["account_id", "device_id"],
        unique=True,
    )
    op.create_index("desktop_device_account_idx", "desktop_device", ["account_id"])
    op.create_index("desktop_device_device_id_idx", "desktop_device", ["device_id"])


def downgrade():
    op.drop_index("desktop_device_device_id_idx", table_name="desktop_device")
    op.drop_index("desktop_device_account_idx", table_name="desktop_device")
    op.drop_index("desktop_device_account_device_uniq", table_name="desktop_device")
    op.drop_table("desktop_device")
