# api/internal/migration/versions/d8e9f0a1b2c3_add_billable_to_public_ai_feature_config.py
"""add billable to public_ai_feature_config

Revision ID: d8e9f0a1b2c3
Revises: c7d8e9f0a1b2
Create Date: 2026-07-22 14:00:00.000000

为公共 AI 功能配置加 billable 字段，标记功能是否应该扣用户额度。
billable=true 表示在用户直接请求流程中触发，用户直接受益，应扣用户额度。
billable=false 表示系统后台维护或平台治理功能，系统承担成本。
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "d8e9f0a1b2c3"
down_revision = "c7d8e9f0a1b2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 1. 加列，默认 false（系统承担）
    op.add_column(
        "public_ai_feature_config",
        sa.Column(
            "billable",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )

    # 2. 更新 8 个用户直接受益的功能为 billable=true
    billable_keys = [
        "direct_answer",
        "conversation_summary",
        "assistant_agent_intro",
        "rerank_fallback",
        "prompt_optimization",
        "code_assistant",
        "schema_assistant",
        "tag_assignment",
    ]
    op.get_bind().execute(
        sa.text(
            "UPDATE public_ai_feature_config SET billable = true "
            "WHERE feature_key IN :keys"
        ).bindparams(sa.bindparam("keys", expanding=True)),
        {"keys": billable_keys},
    )


def downgrade() -> None:
    op.drop_column("public_ai_feature_config", "billable")
