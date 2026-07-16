# api/internal/migration/versions/u7f8a9b0c1d2_import_builtin_providers.py
"""import 10 builtin providers

Revision ID: u7f8a9b0c1d2
Revises: t6e7f8a9b0c1
Create Date: 2026-07-16 23:01:00.000000

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "u7f8a9b0c1d2"
down_revision = "t6e7f8a9b0c1"
branch_labels = None
depends_on = None


BUILTIN_PROVIDERS = [
    {
        "name": "atlascloud",
        "label": "Atlas Cloud",
        "default_base_url": "https://api.atlascloud.com/v1",
        "supported_model_types": ["chat"],
    },
    {
        "name": "deepseek",
        "label": "DeepSeek",
        "default_base_url": "https://api.deepseek.com/v1",
        "supported_model_types": ["chat"],
    },
    {
        "name": "moonshot",
        "label": "月之暗面",
        "default_base_url": "https://api.moonshot.cn/v1",
        "supported_model_types": ["chat"],
    },
    {
        "name": "tongyi",
        "label": "通义千问",
        "default_base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
        "supported_model_types": ["chat", "embedding"],
    },
    {
        "name": "wenxin",
        "label": "文心一言",
        "default_base_url": "https://qianfan.baidubce.com/v2",
        "supported_model_types": ["chat"],
    },
    {
        "name": "ollama",
        "label": "Ollama",
        "default_base_url": "http://localhost:11434/v1",
        "supported_model_types": ["chat"],
    },
    {
        "name": "google",
        "label": "Google",
        "default_base_url": "https://generativelanguage.googleapis.com/v1beta",
        "supported_model_types": ["chat"],
    },
    {
        "name": "zhipu",
        "label": "智谱AI",
        "default_base_url": "https://open.bigmodel.cn/api/paas/v4",
        "supported_model_types": ["chat", "embedding"],
    },
    {
        "name": "grok",
        "label": "xAI Grok",
        "default_base_url": "https://api.x.ai/v1",
        "supported_model_types": ["chat"],
    },
    {
        "name": "openai",
        "label": "OpenAI",
        "default_base_url": "https://api.openai.com/v1",
        "supported_model_types": ["chat", "completion", "embedding"],
    },
]


def upgrade() -> None:
    connection = op.get_bind()
    for provider in BUILTIN_PROVIDERS:
        # 检查是否已存在（幂等）
        existing = connection.execute(
            sa.text("SELECT id FROM model_provider_config WHERE name = :name"),
            {"name": provider["name"]},
        ).fetchone()
        if existing:
            continue
        connection.execute(
            sa.text(
                "INSERT INTO model_provider_config (id, name, label, description, icon, background, "
                "default_base_url, supported_model_types, status, created_at, updated_at) "
                "VALUES (uuid_generate_v4(), :name, :label, '', '', '#FFFFFF', "
                ":default_base_url, CAST(:supported_model_types AS jsonb), 'active', "
                "CURRENT_TIMESTAMP(0), CURRENT_TIMESTAMP(0))"
            ),
            {
                "name": provider["name"],
                "label": provider["label"],
                "default_base_url": provider["default_base_url"],
                "supported_model_types": sa.text(f"'{json.dumps(provider['supported_model_types'])}'"),
            },
        )


def downgrade() -> None:
    connection = op.get_bind()
    names = [p["name"] for p in BUILTIN_PROVIDERS]
    placeholders = ",".join(f":name_{i}" for i in range(len(names)))
    params = {f"name_{i}": names[i] for i in range(len(names))}
    connection.execute(
        sa.text(f"DELETE FROM model_provider_config WHERE name IN ({placeholders})"),
        params,
    )
