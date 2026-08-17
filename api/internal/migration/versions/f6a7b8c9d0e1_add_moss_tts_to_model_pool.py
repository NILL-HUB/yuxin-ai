"""add MOSS TTS model to model_pool_config

Revision ID: f6a7b8c9d0e1
Revises: f5a6b7c8d9e0
Create Date: 2026-08-15 00:00:00.000000

CosyVoice2 对极短文本可能返回空音频，连续语音场景改为优先使用 MOSS-TTSD，
模型池中保留两个 TTS 模型供管理员切换。
"""
from alembic import op
import sqlalchemy as sa


revision = "f6a7b8c9d0e1"
down_revision = "f5a6b7c8d9e0"
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
                'SiliconFlow', 'fnlp/MOSS-TTSD-v0.5', 'MOSS-TTSD',
                'SiliconFlow TTS: MOSS-TTSD-v0.5', '2', '[]'::jsonb,
                0.000000, 0, 0, 0,
                'active', 'tts', 'openai', NULL, 10, 0, NOW(), NOW()
            WHERE EXISTS (
                SELECT 1 FROM model_provider_config WHERE name = 'SiliconFlow'
            )
              AND NOT EXISTS (
                SELECT 1 FROM model_pool_config
                WHERE provider = 'SiliconFlow'
                  AND model_name = 'fnlp/MOSS-TTSD-v0.5'
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
              AND model_name = 'fnlp/MOSS-TTSD-v0.5'
              AND model_type = 'tts'
            """
        )
    )
