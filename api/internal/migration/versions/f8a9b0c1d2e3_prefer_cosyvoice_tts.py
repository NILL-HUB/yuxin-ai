"""prefer CosyVoice2 for TTS in model_pool_config

Revision ID: f8a9b0c1d2e3
Revises: d5e6f7a8b9c3
Create Date: 2026-08-15 00:00:00.000000

语音回放质量优先 CosyVoice2（长文本更稳定、音色一致），
MOSS-TTSD 保留为短文本/空音频兜底。管理员仍可在模型池调整优先级。
"""
from alembic import op
import sqlalchemy as sa


revision = "f8a9b0c1d2e3"
down_revision = "d5e6f7a8b9c3"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        sa.text(
            """
            UPDATE model_pool_config
            SET priority = 20
            WHERE provider = 'SiliconFlow'
              AND model_name = 'FunAudioLLM/CosyVoice2-0.5B'
              AND model_type = 'tts'
            """
        )
    )
    op.execute(
        sa.text(
            """
            UPDATE model_pool_config
            SET priority = 10
            WHERE provider = 'SiliconFlow'
              AND model_name = 'fnlp/MOSS-TTSD-v0.5'
              AND model_type = 'tts'
            """
        )
    )


def downgrade() -> None:
    op.execute(
        sa.text(
            """
            UPDATE model_pool_config
            SET priority = 0
            WHERE provider = 'SiliconFlow'
              AND model_name = 'FunAudioLLM/CosyVoice2-0.5B'
              AND model_type = 'tts'
            """
        )
    )
