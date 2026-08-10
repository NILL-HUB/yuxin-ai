"""cleanup public_ai_feature_config: fix flags, drop legacy routing features, add last_called_at

Revision ID: m8b9c0d1e2f3
Revises: l7a8b9c0d1e2
Create Date: 2026-08-01 10:00:00.000000

变更内容：
1. 修复 conductor billable=true → false（系统治理功能不应扣用户额度）
2. 取消 intent_recognition 的 deprecated 标记（首页意图识别与指挥官路由无关，被误标）
3. 删除 4 条冗余路由配置：
   - task_decomposition（对应 _stream_multi_agent 路径已降级为死代码）
   - task_classification / pool_intent_resolution / tool_selection（指挥官启用后完全替代 orchestrator）
4. 添加 last_called_at 字段，记录功能最后被调用时间，辅助管理员识别未使用的配置
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'm8b9c0d1e2f3'
down_revision = 'l7a8b9c0d1e2'
branch_labels = None
depends_on = None


# 待删除的冗余路由 feature_key
# task_decomposition: _stream_multi_agent 已降级为 single_agent，TaskDecomposer 永不被调用
# task_classification / pool_intent_resolution / tool_selection: 指挥官启用后完全替代 orchestrator
_LEGACY_ROUTING_FEATURES_TO_DELETE = [
    "task_decomposition",
    "task_classification",
    "pool_intent_resolution",
    "tool_selection",
]


def upgrade():
    bind = op.get_bind()

    # 1. 修复 conductor billable：true → false
    #    conductor 是平台路由决策层，用户不直接受益，应系统承担成本
    bind.execute(
        sa.text(
            "UPDATE public_ai_feature_config SET billable = false "
            "WHERE feature_key = 'conductor' AND billable = true"
        )
    )

    # 2. 取消 intent_recognition 的 deprecated 标记
    #    intent_recognition 被 home_service 用于首页用户意图识别（推荐问题、个性化介绍），
    #    与指挥官路由决策无关，被误标为 deprecated
    bind.execute(
        sa.text(
            "UPDATE public_ai_feature_config SET deprecated = false "
            "WHERE feature_key = 'intent_recognition'"
        )
    )

    # 3. 删除 4 条冗余路由配置
    bind.execute(
        sa.text(
            "DELETE FROM public_ai_feature_config WHERE feature_key IN :feature_keys"
        ).bindparams(
            sa.bindparam("feature_keys", expanding=True),
        ),
        {"feature_keys": _LEGACY_ROUTING_FEATURES_TO_DELETE},
    )

    # 4. 添加 last_called_at 字段，记录功能最后被调用时间
    op.add_column(
        'public_ai_feature_config',
        sa.Column(
            'last_called_at',
            sa.DateTime(),
            nullable=True,
        ),
    )


def downgrade():
    # 回滚字段
    op.drop_column('public_ai_feature_config', 'last_called_at')

    bind = op.get_bind()

    # 恢复删除的 4 条配置（与 seed 一致的默认值）
    _restore_features = [
        ("task_classification", "任务分类", "routing", "任务分类"),
        ("task_decomposition", "任务分解", "routing", "多智能体任务分解"),
        ("pool_intent_resolution", "子池匹配", "routing", "子池匹配判定"),
        ("tool_selection", "工具选择", "routing", "LLM 根据查询语义选择最相关的 builtin 工具"),
    ]
    for feature_key, feature_name, category, description in _restore_features:
        bind.execute(
            sa.text(
                "INSERT INTO public_ai_feature_config "
                "(feature_key, feature_name, feature_category, feature_description, "
                " model_config_id, enabled, fallback_tier, model_type, billable, deprecated, extra_config, updated_at, created_at) "
                "VALUES (:key, :name, :cat, :desc, NULL, true, 'cheap', 'chat', false, true, '{}'::jsonb, NOW(), NOW()) "
                "ON CONFLICT (feature_key) DO NOTHING"
            ),
            {"key": feature_key, "name": feature_name, "cat": category, "desc": description},
        )

    # 恢复 intent_recognition deprecated 标记
    bind.execute(
        sa.text(
            "UPDATE public_ai_feature_config SET deprecated = true "
            "WHERE feature_key = 'intent_recognition'"
        )
    )

    # 恢复 conductor billable=true（回滚到错误状态，仅用于 downgrade 完整性）
    bind.execute(
        sa.text(
            "UPDATE public_ai_feature_config SET billable = true "
            "WHERE feature_key = 'conductor'"
        )
    )
