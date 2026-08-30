"""add peak/valley & cache pricing to model_pool_config

Revision ID: g1a2b3c4d5e7
Revises: f0a1b2c3d4e5
Create Date: 2026-08-31 10:00:00.000000
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = "g1a2b3c4d5e7"
down_revision = "f0a1b2c3d4e5"
branch_labels = None
depends_on = None


_NUMERIC_COLUMNS = [
    "input_cached_price_per_1k_tokens",
    "input_cached_cost_per_1k_tokens",
    "peak_input_price_per_1k_tokens",
    "peak_output_price_per_1k_tokens",
    "peak_input_cached_price_per_1k_tokens",
    "peak_input_cost_per_1k_tokens",
    "peak_output_cost_per_1k_tokens",
    "peak_input_cached_cost_per_1k_tokens",
    "valley_input_price_per_1k_tokens",
    "valley_output_price_per_1k_tokens",
    "valley_input_cached_price_per_1k_tokens",
    "valley_input_cost_per_1k_tokens",
    "valley_output_cost_per_1k_tokens",
    "valley_input_cached_cost_per_1k_tokens",
]


def upgrade():
    op.add_column("model_pool_config", sa.Column(
        "peak_valley_enabled", sa.Boolean(), nullable=False, server_default=sa.text("false")))
    op.add_column("model_pool_config", sa.Column(
        "cache_pricing_enabled", sa.Boolean(), nullable=False, server_default=sa.text("false")))
    for name in _NUMERIC_COLUMNS:
        op.add_column("model_pool_config", sa.Column(
            name, sa.Numeric(precision=12, scale=6), nullable=False, server_default=sa.text("0.000000")))
    op.add_column("model_pool_config", sa.Column(
        "peak_windows", JSONB(), nullable=False, server_default=sa.text("'[]'::jsonb")))

    op.add_column("billing_usage_event", sa.Column(
        "cached_input_tokens", sa.Integer(), nullable=False, server_default=sa.text("0")))
    op.add_column("billing_usage_event", sa.Column(
        "price_tier", sa.String(length=16), nullable=False, server_default=sa.text("''::character varying")))
    op.add_column("billing_usage_event", sa.Column("moment", sa.DateTime(), nullable=True))

    # billing_config 增加文本值列，承载字符串类配置（如峰谷判定时区）；数值类配置仍走 value_numeric
    op.add_column("billing_config", sa.Column(
        "value_text", sa.Text(), nullable=False, server_default=sa.text("''::text")))

    seeds = [
        ("peak_valley_timezone", "Asia/Shanghai", "谷峰判定时区"),
        ("min_margin_ratio", "0.1", "双界校验：售价不低于成本×1+该值"),
        ("official_price_cap_ratio", "1.1", "双界校验：售价不高于官方价×该值"),
        ("default_margin_ratio", "0.3", "自动定价助手默认目标毛利率"),
        ("usd_to_cny", "7.2", "美元计价供应商成本折算汇率"),
    ]
    conn = op.get_bind()
    for code, value, desc in seeds:
        if code == "peak_valley_timezone":
            conn.execute(sa.text(
                "INSERT INTO billing_config (code, value_text, description, updated_at, created_at) "
                "VALUES (:code, :value, :desc, CURRENT_TIMESTAMP(0), CURRENT_TIMESTAMP(0)) "
                "ON CONFLICT (code) DO NOTHING"
            ).bindparams(code=code, value=value, desc=desc))
        else:
            conn.execute(sa.text(
                "INSERT INTO billing_config (code, value_numeric, description, updated_at, created_at) "
                "VALUES (:code, :value, :desc, CURRENT_TIMESTAMP(0), CURRENT_TIMESTAMP(0)) "
                "ON CONFLICT (code) DO NOTHING"
            ).bindparams(code=code, value=value, desc=desc))


def downgrade():
    conn = op.get_bind()
    conn.execute(sa.text(
        "DELETE FROM billing_config WHERE code IN "
        "('peak_valley_timezone','min_margin_ratio','official_price_cap_ratio','default_margin_ratio','usd_to_cny')"))
    op.drop_column("billing_config", "value_text")
    op.drop_column("billing_usage_event", "moment")
    op.drop_column("billing_usage_event", "price_tier")
    op.drop_column("billing_usage_event", "cached_input_tokens")
    op.drop_column("model_pool_config", "peak_windows")
    for name in _NUMERIC_COLUMNS:
        op.drop_column("model_pool_config", name)
    op.drop_column("model_pool_config", "cache_pricing_enabled")
    op.drop_column("model_pool_config", "peak_valley_enabled")