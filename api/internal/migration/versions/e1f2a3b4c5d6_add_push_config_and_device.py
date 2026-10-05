"""add push config and device tables

Revision ID: e1f2a3b4c5d6
Revises: f3a4b5c6d7e8

系统推送接入（个推为主 / 友盟为辅）批次 1 骨架：
- push_config：单行 JSONB（id=1），admin 配置两家凭证与主备开关（密钥字段密文存储）；
- push_device：App 上报的推送令牌（个推 cid / 友盟 device_token），按账号幂等。

设计：docs/superpowers/specs/2026-10-03-mobile-remote-control-multi-device-design.md §4.7
计划：docs/superpowers/plans/2026-10-04-push-channel-skeleton.md
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision = "e1f2a3b4c5d6"
down_revision = "f3a4b5c6d7e8"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "push_config",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("configs", JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP(0)")),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP(0)")),
    )
    op.execute("INSERT INTO push_config (id) VALUES (1) ON CONFLICT (id) DO NOTHING")

    op.create_table(
        "push_device",
        sa.Column("id", UUID(), nullable=False, server_default=sa.text("uuid_generate_v4()")),
        sa.Column("account_id", UUID(), nullable=False),
        sa.Column("platform", sa.String(length=16), nullable=False, server_default=sa.text("''::character varying")),
        sa.Column("provider", sa.String(length=16), nullable=False),
        sa.Column("token", sa.String(length=512), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP(0)")),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP(0)")),
        sa.PrimaryKeyConstraint("id", name="pk_push_device_id"),
        sa.UniqueConstraint("account_id", "provider", "token", name="uq_push_device_account_provider_token"),
    )
    op.create_index("push_device_account_idx", "push_device", ["account_id"], unique=False)


def downgrade():
    op.drop_index("push_device_account_idx", table_name="push_device")
    op.drop_table("push_device")
    op.drop_table("push_config")
