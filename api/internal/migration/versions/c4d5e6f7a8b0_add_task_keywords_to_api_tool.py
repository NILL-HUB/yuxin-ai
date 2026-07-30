# api/internal/migration/versions/c4d5e6f7a8b0_add_task_keywords_to_api_tool.py
"""add task_keywords to api_tool

Revision ID: c4d5e6f7a8b0
Revises: 905c76df81dc
Create Date: 2026-07-27 16:00:00.000000

为 api_tool 表增加 task_keywords 字段（JSONB，默认 '[]'::jsonb），
用于 ToolSelectorService 的关键词快速匹配通道（方案A）。

设计动机：
- 方案A 要求全 source_type 覆盖关键词快通道，builtin/mcp/skill/workflow 已落地
- api_tool 作为用户自定义 API 工具，同样需要支持关键词快速匹配
- 用户在创建/编辑 API 工具时可填写 task_keywords，让常见查询绕过 LLM 调用

同时为 api_task_keywords 建立 GIN 索引以加速 JSONB 包含查询。
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB


# revision identifiers, used by Alembic.
revision = "c4d5e6f7a8b0"
down_revision = "905c76df81dc"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 1. api_tool 增加 task_keywords
    op.add_column(
        "api_tool",
        sa.Column(
            "task_keywords",
            JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
    )
    op.create_index(
        "api_tool_task_keywords_idx",
        "api_tool",
        ["task_keywords"],
        postgresql_using="gin",
    )

    # 2. 为现有 api_tool 记录基于 name + description 补全初始 task_keywords
    # api_tool.name 通常包含语义信息（如"weather_api"），可作初始关键词
    op.execute("""
        UPDATE api_tool
        SET task_keywords = (
            SELECT jsonb_agg(DISTINCT x)
            FROM (VALUES (name)) AS t(x)
            WHERE x IS NOT NULL AND x <> ''
        )
        WHERE name IS NOT NULL AND name <> ''
    """)


def downgrade() -> None:
    op.drop_index("api_tool_task_keywords_idx", table_name="api_tool")
    op.drop_column("api_tool", "task_keywords")
