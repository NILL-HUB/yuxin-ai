"""add SiliconFlow tts model to model_pool_config

Revision ID: f5a6b7c8d9e0
Revises: e4f5a6b7c8d9
Create Date: 2026-08-14 00:00:00.000000

把 TTS 运行时使用的 CosyVoice2 同步到模型池管理，管理员可以在后台切换/停用。
"""
from alembic import op
import sqlalchemy as sa


revision = "f5a6b7c8d9e0"
down_revision = "e4f5a6b7c8d9"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        sa.text(
            """
            INSERT INTO model_pool_config
                (provider, model_name, display_name, description, tier, capabilities,
                 price_per_1k_tokens, max_tokens, max_input_tokens, max_output_tokens,
                 status, model_type, compatible_api, fallback_model_id, priority,
                 embedding_dimension, updated_at, created_at)
            SELECT
                'SiliconFlow', 'FunAudioLLM/CosyVoice2-0.5B', 'CosyVoice2',
                'SiliconFlow TTS: CosyVoice2-0.5B', '2', '[]'::jsonb,
                0.000000, 0, 0, 0,
                'active', 'tts', 'openai', NULL, 0, 0, NOW(), NOW()
            WHERE EXISTS (
                SELECT 1 FROM model_provider_config WHERE name = 'SiliconFlow'
            )
              AND NOT EXISTS (
                SELECT 1 FROM model_pool_config
                WHERE provider = 'SiliconFlow'
                  AND model_name = 'FunAudioLLM/CosyVoice2-0.5B'
            )
            """
        )
    )


def downgrade() -> None:
    op.execute(
        sa.text(
            """
            DELETE FROM model_pool_config
            WHERE provider = 'SiliconFlow'
              AND model_name = 'FunAudioLLM/CosyVoice2-0.5B'
              AND model_type = 'tts'
            """
        )
    )
