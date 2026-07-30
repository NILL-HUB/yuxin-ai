"""tier policy crud and numeric migration

Revision ID: f1a2b3c4d5e6
Revises: d5e6f7a8b9c2
Create Date: 2026-07-29 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = 'f1a2b3c4d5e6'
down_revision = 'd5e6f7a8b9c2'
branch_labels = None
depends_on = None


def upgrade():
    # 1. 为 model_tier_policy 表新增 tier_name 和 sort_order 字段
    op.add_column('model_tier_policy', sa.Column(
        'tier_name', sa.String(128), nullable=False, server_default=''
    ))
    op.add_column('model_tier_policy', sa.Column(
        'sort_order', sa.Integer(), nullable=False, server_default='0'
    ))

    # 2. 数据迁移：将旧的字符串档位编码映射为数字标识，并设置默认显示名
    #    cheap -> 1 (经济型), standard -> 2 (标准型), strong -> 3 (强力型),
    #    vision -> 4 (视觉型), long_context -> 5 (长上下文型)
    op.execute("""
        UPDATE model_tier_policy SET tier_code = '1', tier_name = '经济型', sort_order = 1 WHERE tier_code = 'cheap';
    """)
    op.execute("""
        UPDATE model_tier_policy SET tier_code = '2', tier_name = '标准型', sort_order = 2 WHERE tier_code = 'standard';
    """)
    op.execute("""
        UPDATE model_tier_policy SET tier_code = '3', tier_name = '强力型', sort_order = 3 WHERE tier_code = 'strong';
    """)
    op.execute("""
        UPDATE model_tier_policy SET tier_code = '4', tier_name = '视觉型', sort_order = 4 WHERE tier_code = 'vision';
    """)
    op.execute("""
        UPDATE model_tier_policy SET tier_code = '5', tier_name = '长上下文型', sort_order = 5 WHERE tier_code = 'long_context';
    """)

    # 3. 迁移 model_pool_config.tier 字段值
    op.execute("UPDATE model_pool_config SET tier = '1' WHERE tier = 'cheap';")
    op.execute("UPDATE model_pool_config SET tier = '2' WHERE tier = 'standard';")
    op.execute("UPDATE model_pool_config SET tier = '3' WHERE tier = 'strong';")
    op.execute("UPDATE model_pool_config SET tier = '4' WHERE tier = 'vision';")
    op.execute("UPDATE model_pool_config SET tier = '5' WHERE tier = 'long_context';")
    # 更新 server_default
    op.alter_column('model_pool_config', 'tier',
        server_default="'2'",
        existing_type=sa.String(64),
        existing_nullable=False,
    )

    # 4. 迁移 cost_policy.model_tier 字段值
    op.execute("UPDATE cost_policy SET model_tier = '1' WHERE model_tier = 'cheap';")
    op.execute("UPDATE cost_policy SET model_tier = '2' WHERE model_tier = 'standard';")
    op.execute("UPDATE cost_policy SET model_tier = '3' WHERE model_tier = 'strong';")
    op.execute("UPDATE cost_policy SET model_tier = '4' WHERE model_tier = 'vision';")
    op.execute("UPDATE cost_policy SET model_tier = '5' WHERE model_tier = 'long_context';")
    op.alter_column('cost_policy', 'model_tier',
        server_default="'2'",
        existing_type=sa.String(64),
        existing_nullable=False,
    )

    # 5. 迁移 public_ai_feature_config.fallback_tier 字段值
    op.execute("UPDATE public_ai_feature_config SET fallback_tier = '1' WHERE fallback_tier = 'cheap';")
    op.execute("UPDATE public_ai_feature_config SET fallback_tier = '2' WHERE fallback_tier = 'standard';")
    op.execute("UPDATE public_ai_feature_config SET fallback_tier = '3' WHERE fallback_tier = 'strong';")
    op.execute("UPDATE public_ai_feature_config SET fallback_tier = '4' WHERE fallback_tier = 'vision';")
    op.execute("UPDATE public_ai_feature_config SET fallback_tier = '5' WHERE fallback_tier = 'long_context';")


def downgrade():
    # 回滚字段
    op.drop_column('model_tier_policy', 'sort_order')
    op.drop_column('model_tier_policy', 'tier_name')

    # 回滚数据
    op.execute("UPDATE model_tier_policy SET tier_code = 'cheap' WHERE tier_code = '1';")
    op.execute("UPDATE model_tier_policy SET tier_code = 'standard' WHERE tier_code = '2';")
    op.execute("UPDATE model_tier_policy SET tier_code = 'strong' WHERE tier_code = '3';")
    op.execute("UPDATE model_tier_policy SET tier_code = 'vision' WHERE tier_code = '4';")
    op.execute("UPDATE model_tier_policy SET tier_code = 'long_context' WHERE tier_code = '5';")

    op.execute("UPDATE model_pool_config SET tier = 'cheap' WHERE tier = '1';")
    op.execute("UPDATE model_pool_config SET tier = 'standard' WHERE tier = '2';")
    op.execute("UPDATE model_pool_config SET tier = 'strong' WHERE tier = '3';")
    op.execute("UPDATE model_pool_config SET tier = 'vision' WHERE tier = '4';")
    op.execute("UPDATE model_pool_config SET tier = 'long_context' WHERE tier = '5';")
    op.alter_column('model_pool_config', 'tier',
        server_default="'standard'",
        existing_type=sa.String(64),
        existing_nullable=False,
    )

    op.execute("UPDATE cost_policy SET model_tier = 'cheap' WHERE model_tier = '1';")
    op.execute("UPDATE cost_policy SET model_tier = 'standard' WHERE model_tier = '2';")
    op.execute("UPDATE cost_policy SET model_tier = 'strong' WHERE model_tier = '3';")
    op.execute("UPDATE cost_policy SET model_tier = 'vision' WHERE model_tier = '4';")
    op.execute("UPDATE cost_policy SET model_tier = 'long_context' WHERE model_tier = '5';")
    op.alter_column('cost_policy', 'model_tier',
        server_default="'standard'",
        existing_type=sa.String(64),
        existing_nullable=False,
    )

    op.execute("UPDATE public_ai_feature_config SET fallback_tier = 'cheap' WHERE fallback_tier = '1';")
    op.execute("UPDATE public_ai_feature_config SET fallback_tier = 'standard' WHERE fallback_tier = '2';")
    op.execute("UPDATE public_ai_feature_config SET fallback_tier = 'strong' WHERE fallback_tier = '3';")
    op.execute("UPDATE public_ai_feature_config SET fallback_tier = 'vision' WHERE fallback_tier = '4';")
    op.execute("UPDATE public_ai_feature_config SET fallback_tier = 'long_context' WHERE fallback_tier = '5';")
