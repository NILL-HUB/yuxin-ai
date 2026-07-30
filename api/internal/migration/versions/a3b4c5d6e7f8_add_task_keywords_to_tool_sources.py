# api/internal/migration/versions/a3b4c5d6e7f8_add_task_keywords_to_tool_sources.py
"""add task_keywords to mcp_provider, skill_package, workflow

Revision ID: a3b4c5d6e7f8
Revises: z2c3d4e5f6a7
Create Date: 2026-07-26 15:00:00.000000

为 mcp_provider / skill_package / workflow 三张表增加 task_keywords 字段
（JSONB，默认 '[]'::jsonb），用于 ToolSelectorService 的关键词快速匹配通道。

设计动机：
- ToolSelectorService 之前仅对 builtin 工具做 LLM 语义选择，MCP/Skill/Workflow
  在候选收集后被 _filter_builtin_candidates 过滤掉，永远不会被 LLM 选中
- 方案A 引入"关键词快通道 + LLM 兜底"双层机制：
  1. 优先匹配 task_keywords（零成本，毫秒级）
  2. 未命中再走 LLM 语义选择（覆盖全 source_type，不只 builtin）
- task_keywords 由用户在创建/编辑 MCP/Skill/Workflow 时填写，与 Agent 子池的
  task_keywords 字段对称，保持系统统一的关键词快速路径设计范式

同时为三张表建立 GIN 索引以加速 JSONB 包含查询。
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB


# revision identifiers, used by Alembic.
revision = "a3b4c5d6e7f8"
down_revision = "z2c3d4e5f6a7"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 1. mcp_provider 增加 task_keywords
    op.add_column(
        "mcp_provider",
        sa.Column(
            "task_keywords",
            JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
    )
    op.create_index(
        "mcp_provider_task_keywords_idx",
        "mcp_provider",
        ["task_keywords"],
        postgresql_using="gin",
    )

    # 2. skill_package 增加 task_keywords
    op.add_column(
        "skill_package",
        sa.Column(
            "task_keywords",
            JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
    )
    op.create_index(
        "skill_package_task_keywords_idx",
        "skill_package",
        ["task_keywords"],
        postgresql_using="gin",
    )

    # 3. workflow 增加 task_keywords
    op.add_column(
        "workflow",
        sa.Column(
            "task_keywords",
            JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
    )
    op.create_index(
        "workflow_task_keywords_idx",
        "workflow",
        ["task_keywords"],
        postgresql_using="gin",
    )

    # 4. 为现有 workflow 记录基于 name 补全初始 task_keywords
    # workflow.name 通常包含显式语义（如"翻译工作流""数据同步工作流"），可作初始关键词
    op.execute("""
        UPDATE workflow
        SET task_keywords = CASE
            WHEN name IS NOT NULL AND name <> '' THEN jsonb_build_array(name)
            ELSE '[]'::jsonb
        END
        WHERE name IS NOT NULL AND name <> ''
    """)

    # 5. 为现有 skill_package 记录基于 name + label 补全初始 task_keywords
    op.execute("""
        UPDATE skill_package
        SET task_keywords = (
            SELECT jsonb_agg(DISTINCT x)
            FROM (VALUES (name), (label)) AS t(x)
            WHERE x IS NOT NULL AND x <> ''
        )
        WHERE name IS NOT NULL AND name <> ''
    """)

    # 6. 为现有 mcp_provider 记录基于 name + label 补全初始 task_keywords
    op.execute("""
        UPDATE mcp_provider
        SET task_keywords = (
            SELECT jsonb_agg(DISTINCT x)
            FROM (VALUES (name), (label)) AS t(x)
            WHERE x IS NOT NULL AND x <> ''
        )
        WHERE name IS NOT NULL AND name <> ''
    """)


def downgrade() -> None:
    # mcp_provider
    op.drop_index("mcp_provider_task_keywords_idx", table_name="mcp_provider")
    op.drop_column("mcp_provider", "task_keywords")

    # skill_package
    op.drop_index("skill_package_task_keywords_idx", table_name="skill_package")
    op.drop_column("skill_package", "task_keywords")

    # workflow
    op.drop_index("workflow_task_keywords_idx", table_name="workflow")
    op.drop_column("workflow", "task_keywords")
