"""add auth channels: phone fields, mail/sms config, auth switches

Revision ID: h2c3d4e5f6a8
Revises: g1a2b3c4d5e7
Create Date: 2026-08-31 14:00:00.000000
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = "h2c3d4e5f6a8"
down_revision = "g1a2b3c4d5e7"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("account", sa.Column("phone", sa.String(32), nullable=False, server_default=sa.text("''::character varying")))
    op.add_column("account", sa.Column("phone_verified_at", sa.DateTime(), nullable=True))
    op.add_column("account", sa.Column("email_verified_at", sa.DateTime(), nullable=True))
    op.execute(
        "CREATE UNIQUE INDEX account_phone_active_idx ON account (phone) "
        "WHERE phone <> ''"
    )

    op.create_table(
        "mail_config",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("configs", JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP(0)")),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP(0)")),
    )
    op.create_table(
        "sms_config",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("configs", JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP(0)")),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP(0)")),
    )
    op.execute("INSERT INTO mail_config (id) VALUES (1) ON CONFLICT (id) DO NOTHING")
    op.execute("INSERT INTO sms_config (id) VALUES (1) ON CONFLICT (id) DO NOTHING")

    conn = op.get_bind()
    conn.execute(sa.text(
        "INSERT INTO orchestration_feature_flag (id, code, name, description, enabled, risk_level, fallback_behavior) VALUES "
        "(uuid_generate_v4(), 'AUTH_EMAIL_ENABLED', '邮箱登录注册通道', '邮箱+密码登录、邮箱验证码注册/登录/改密/挑战', true, 'low', 'block'),"
        "(uuid_generate_v4(), 'AUTH_PHONE_ENABLED', '手机号登录注册通道', '手机号+验证码登录/注册/改密/挑战/绑定', false, 'low', 'block'),"
        "(uuid_generate_v4(), 'AUTH_LOGIN_CHALLENGE_ENABLED', '新IP登录二次验证', '异地新IP登录二次验证开关', true, 'medium', 'block') "
        "ON CONFLICT (code) DO NOTHING"
    ))


def downgrade():
    op.execute("DROP INDEX IF EXISTS account_phone_active_idx")
    op.drop_column("account", "email_verified_at")
    op.drop_column("account", "phone_verified_at")
    op.drop_column("account", "phone")
    op.drop_table("sms_config")
    op.drop_table("mail_config")
    conn = op.get_bind()
    conn.execute(sa.text("DELETE FROM orchestration_feature_flag WHERE code IN ('AUTH_EMAIL_ENABLED','AUTH_PHONE_ENABLED','AUTH_LOGIN_CHALLENGE_ENABLED')"))