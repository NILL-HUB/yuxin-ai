"""seed siliconflow provider and qwen3-vl-embedding visual model

Revision ID: dae1f2a3b4c5
Revises: c9d0e1f2a3b4
Create Date: 2026-09-15

变更内容：
把关键帧视觉编码模型 Qwen/Qwen3-VL-Embedding-8B 同步到模型池，供
VisualEmbeddingService 通过 get_provider_credentials 取用。

维度 1536：原生 4096 超出 pgvector 上限 2000，经 MRL 降维。

幂等：provider 与模型均以 NOT EXISTS 保护，可重复执行。
**不写密钥**：按仓库规范，密钥由管理员在 admin 模型池配置（model_key_config），
迁移只登记 provider 与模型元数据。
"""
from alembic import op
import sqlalchemy as sa


revision = "dae1f2a3b4c5"
down_revision = "c9d0e1f2a3b4"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 1. provider：SiliconFlow（代码中无 seed，此前依赖管理员手工创建；
    #    若已存在则保持原样，不覆盖运维配置的 base_url）
    #
    #    注意 id：`model_provider_config.id` 在建表迁移 `t6e7f8a9b0c1` 中
    #    只声明了 nullable=False，**没有 server_default**（实测真实库
    #    column_default 为空），因此不能依赖默认值，必须在 INSERT 里显式给出
    #    `uuid_generate_v4()`。其余 seed 迁移（u7f8a9b0c1d2 / v8a9b0c1d2e3 /
    #    本文件下方 model_pool_config）均已显式生成。
    op.execute(
        sa.text(
            """
            INSERT INTO model_provider_config
                (id, name, label, description, default_base_url, supported_model_types, status)
            SELECT
                uuid_generate_v4(),
                'SiliconFlow', '硅基流动',
                '硅基流动 AI 云（多模态嵌入、重排序、语音与图像生成）',
                'https://api.siliconflow.cn/v1',
                '["chat","embedding","tts","asr","rerank","visual_embedding"]'::jsonb,
                'active'
            WHERE NOT EXISTS (
                SELECT 1 FROM model_provider_config WHERE name = 'SiliconFlow'
            )
            """
        )
    )

    # 2. 视觉编码模型：入参与 OpenAI /embeddings 不兼容（图片传 {"image": ...}），
    #    故由 VisualEmbeddingService 直连 HTTP，不注册进 model_class_registry
    op.execute(
        sa.text(
            """
            INSERT INTO model_pool_config
                (provider, model_name, display_name, description, tier, capabilities,
                 price_per_1k_tokens, max_tokens, max_input_tokens, max_output_tokens,
                 status, model_type, compatible_api, fallback_model_id, priority,
                 embedding_dimension, updated_at, created_at)
            SELECT
                'SiliconFlow', 'Qwen/Qwen3-VL-Embedding-8B', 'Qwen3-VL-Embedding-8B',
                '多模态嵌入模型：文本与图片共享语义空间，支撑以图搜图与跨模态召回',
                '2', '[]'::jsonb,
                0.000000, 0, 0, 0,
                'active', 'visual_embedding', 'openai', NULL, 100,
                1536, NOW(), NOW()
            WHERE EXISTS (
                SELECT 1 FROM model_provider_config WHERE name = 'SiliconFlow'
            )
              AND NOT EXISTS (
                SELECT 1 FROM model_pool_config
                WHERE provider = 'SiliconFlow'
                  AND model_name = 'Qwen/Qwen3-VL-Embedding-8B'
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
              AND model_name = 'Qwen/Qwen3-VL-Embedding-8B'
              AND model_type = 'visual_embedding'
            """
        )
    )
