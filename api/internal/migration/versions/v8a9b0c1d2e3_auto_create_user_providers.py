# api/internal/migration/versions/v8a9b0c1d2e3_auto_create_user_providers.py
"""auto create user custom providers from model_pool_config

Revision ID: v8a9b0c1d2e3
Revises: u7f8a9b0c1d2
Create Date: 2026-07-16 23:02:00.000000

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "v8a9b0c1d2e3"
down_revision = "u7f8a9b0c1d2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """扫描 model_pool_config，为未在 model_provider_config 中的 provider 自动创建记录。
    default_base_url 取该 provider 下第一条非空 base_url，若无则为空字符串。
    注意：此脚本在 base_url 字段删除之前执行。"""
    connection = op.get_bind()

    # 查找 model_pool_config 中存在但 model_provider_config 中不存在的 provider
    missing_providers = connection.execute(
        sa.text(
            "SELECT DISTINCT mpc.provider, "
            "(SELECT mpc2.base_url FROM model_pool_config mpc2 "
            " WHERE mpc2.provider = mpc.provider AND mpc2.base_url IS NOT NULL AND mpc2.base_url != '' "
            " ORDER BY mpc2.created_at ASC LIMIT 1) as base_url "
            "FROM model_pool_config mpc "
            "WHERE mpc.provider NOT IN (SELECT name FROM model_provider_config)"
        )
    ).fetchall()

    for row in missing_providers:
        provider_name = row[0]
        base_url = row[1] or ""
        connection.execute(
            sa.text(
                "INSERT INTO model_provider_config (id, name, label, description, icon, background, "
                "default_base_url, supported_model_types, status, created_at, updated_at) "
                "VALUES (uuid_generate_v4(), :name, :label, '', '', '#FFFFFF', "
                ":default_base_url, '[\"chat\"]'::jsonb, 'active', "
                "CURRENT_TIMESTAMP(0), CURRENT_TIMESTAMP(0))"
            ),
            {
                "name": provider_name,
                "label": provider_name,
                "default_base_url": base_url,
            },
        )


def downgrade() -> None:
    """无法精确回滚自动创建的 provider，仅删除非内置 provider。
    内置 10 个 provider 由迁移 2 管理，此处不删除。"""
    connection = op.get_bind()
    builtin_names = [
        "atlascloud", "deepseek", "moonshot", "tongyi", "wenxin",
        "ollama", "google", "zhipu", "grok", "openai",
    ]
    placeholders = ",".join(f":name_{i}" for i in range(len(builtin_names)))
    params = {f"name_{i}": builtin_names[i] for i in range(len(builtin_names))}
    connection.execute(
        sa.text(f"DELETE FROM model_provider_config WHERE name NOT IN ({placeholders})"),
        params,
    )
