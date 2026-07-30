"""add deprecated to public_ai_feature_config and mark legacy routing features

Revision ID: l7a8b9c0d1e2
Revises: k6f7a8b9c0d1
Create Date: 2026-07-30 07:00:00.000000

变更内容：
1. 为 public_ai_feature_config 表添加 deprecated 字段（默认 false）
2. 将 5 个旧路由类 feature_key 标记为 deprecated=true
   （intent_recognition/task_classification/task_decomposition/pool_intent_resolution/tool_selection）
   指挥官模式启用时这些 feature_key 被完全绕过，仅作为 fallback 保留
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'l7a8b9c0d1e2'
down_revision = 'k6f7a8b9c0d1'
branch_labels = None
depends_on = None


# 指挥官模式下被完全替代的旧路由 feature_key
_LEGACY_ROUTING_FEATURES = [
    "intent_recognition",
    "task_classification",
    "task_decomposition",
    "pool_intent_resolution",
    "tool_selection",
]


def upgrade():
    # 1. 添加 deprecated 字段
    op.add_column(
        'public_ai_feature_config',
        sa.Column(
            'deprecated',
            sa.Boolean(),
            nullable=False,
            server_default=sa.text('false'),
        ),
    )

    # 2. 标记旧路由 feature_key 为 deprecated
    #    op.execute() 不支持传 params，改用 connection.execute()
    bind = op.get_bind()
    bind.execute(
        sa.text(
            "UPDATE public_ai_feature_config SET deprecated = true "
            "WHERE feature_key IN :feature_keys"
        ).bindparams(
            sa.bindparam("feature_keys", expanding=True),
        ),
        {"feature_keys": _LEGACY_ROUTING_FEATURES},
    )


def downgrade():
    # 恢复旧路由 feature_key 的 deprecated 状态
    bind = op.get_bind()
    bind.execute(
        sa.text(
            "UPDATE public_ai_feature_config SET deprecated = false "
            "WHERE feature_key IN :feature_keys"
        ).bindparams(
            sa.bindparam("feature_keys", expanding=True),
        ),
        {"feature_keys": _LEGACY_ROUTING_FEATURES},
    )
    op.drop_column('public_ai_feature_config', 'deprecated')
