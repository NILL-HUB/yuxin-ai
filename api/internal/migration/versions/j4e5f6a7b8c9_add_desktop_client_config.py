"""add desktop client config table

Revision ID: j4e5f6a7b8c9
Revises: b2c3d4e5f6a7
Create Date: 2026-09-09 00:00:00.000000

admin 端"桌面客户端连接地址"配置的存储表：单行 JSONB（id=1），
桌面端启动时经 GET /desktop-config 读取（未配置回退同源）。
照 mail_config / sms_config 同款模式。
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = "j4e5f6a7b8c9"
down_revision = "b2c3d4e5f6a7"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "desktop_client_config",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("configs", JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP(0)")),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP(0)")),
    )
    op.execute("INSERT INTO desktop_client_config (id) VALUES (1) ON CONFLICT (id) DO NOTHING")


def downgrade():
    op.drop_table("desktop_client_config")
