"""add sub_pool_definition table

Revision ID: i5d6e7f8a9b2
Revises: h4c5d6e7f8a1
Create Date: 2026-06-24 00:00:00.000000

"""
import json

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB


revision = 'i5d6e7f8a9b2'
down_revision = 'h4c5d6e7f8a1'
branch_labels = None
depends_on = None


BUILTIN_AGENT_SUB_POOLS = [
    {"name": "general", "label": "通用", "visible_to_user": True, "description": "默认兜底 Agent", "default_capabilities": [], "task_keywords": [], "sort_order": 0},
    {"name": "coding", "label": "编程", "visible_to_user": True, "description": "写代码、改代码、部署、排错", "default_capabilities": ["coding"], "task_keywords": ["写代码", "改代码", "部署", "排错", "前端", "后端", "测试", "Docker", "bug"], "sort_order": 1},
    {"name": "office", "label": "办公", "visible_to_user": True, "description": "文档、PPT、表格、图片基础处理", "default_capabilities": ["document", "spreadsheet", "presentation"], "task_keywords": ["P 图", "P图", "PPT", "Word", "文档", "Excel", "表格", "图片处理", "图片"], "sort_order": 2},
    {"name": "data", "label": "数据", "visible_to_user": True, "description": "数据分析、SQL、报表、可视化", "default_capabilities": ["data_analysis", "sql", "visualization"], "task_keywords": ["数据", "数据分析", "SQL", "报表", "可视化", "统计"], "sort_order": 3},
    {"name": "research", "label": "研究", "visible_to_user": True, "description": "搜索、行业研究、竞品分析", "default_capabilities": ["research", "search"], "task_keywords": ["调研", "搜索", "竞品", "行业", "报告"], "sort_order": 4},
    {"name": "customer_service", "label": "客服", "visible_to_user": True, "description": "工单、FAQ、售后", "default_capabilities": ["customer_service"], "task_keywords": ["客服", "售后", "退款", "工单", "FAQ"], "sort_order": 5},
    {"name": "internal_admin", "label": "内部管理", "visible_to_user": False, "description": "运维、审计、系统管理", "default_capabilities": ["audit", "ops", "admin"], "task_keywords": ["审计", "权限", "系统管理", "运维"], "sort_order": 6},
]

BUILTIN_TOOL_SUB_POOLS = [
    {"name": "general", "label": "通用工具", "visible_to_user": True, "default_enabled": True, "description": "适合通用任务的工具池", "task_keywords": [], "sort_order": 0},
    {"name": "mcp", "label": "MCP 工具", "visible_to_user": True, "default_enabled": True, "description": "通过 MCP Provider 暴露的工具池", "task_keywords": [], "sort_order": 1},
    {"name": "api", "label": "API 工具", "visible_to_user": True, "default_enabled": True, "description": "通过 OpenAPI Schema 接入的工具池", "task_keywords": [], "sort_order": 2},
    {"name": "builtin", "label": "内置工具", "visible_to_user": True, "default_enabled": True, "description": "系统内置工具池", "task_keywords": [], "sort_order": 3},
    {"name": "knowledge", "label": "知识库工具", "visible_to_user": True, "default_enabled": True, "description": "系统知识、用户资料和知识检索工具池", "task_keywords": [], "sort_order": 4},
    {"name": "memory", "label": "长期记忆", "visible_to_user": True, "default_enabled": True, "description": "用户长期记忆读取与确认工具池", "task_keywords": [], "sort_order": 5},
    {"name": "external_data", "label": "外部数据源", "visible_to_user": True, "default_enabled": True, "description": "外部数据源连接和同步工具池", "task_keywords": [], "sort_order": 6},
    {"name": "system_admin", "label": "系统管理", "visible_to_user": False, "default_enabled": False, "description": "仅管理员可见的高权限工具池", "task_keywords": [], "sort_order": 7},
]


def upgrade():
    op.create_table(
        "sub_pool_definition",
        sa.Column("id", sa.UUID(), nullable=False, server_default=sa.text("uuid_generate_v4()")),
        sa.Column("pool_type", sa.String(length=32), nullable=False, server_default=sa.text("'agent'")),
        sa.Column("name", sa.String(length=64), nullable=False),
        sa.Column("label", sa.String(length=128), nullable=False, server_default=sa.text("''")),
        sa.Column("description", sa.Text(), nullable=False, server_default=sa.text("''")),
        sa.Column("visible_to_user", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("default_enabled", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("default_capabilities", JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("task_keywords", JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("is_system", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.text("now()")),
        sa.PrimaryKeyConstraint("id", name="pk_sub_pool_definition_id"),
        sa.UniqueConstraint("pool_type", "name", name="uq_sub_pool_type_name"),
    )
    op.create_index("sub_pool_definition_type_idx", "sub_pool_definition", ["pool_type"])
    op.create_index("sub_pool_definition_enabled_idx", "sub_pool_definition", ["enabled"])

    conn = op.get_bind()
    for pool in BUILTIN_AGENT_SUB_POOLS:
        conn.execute(
            sa.text(
                "INSERT INTO sub_pool_definition (id, pool_type, name, label, description, visible_to_user, default_enabled, default_capabilities, task_keywords, is_system, sort_order, enabled) "
                "VALUES (uuid_generate_v4(), 'agent', :name, :label, :description, :visible_to_user, true, :capabilities, :keywords, true, :sort_order, true) "
                "ON CONFLICT (pool_type, name) DO NOTHING"
            ),
            {
                "name": pool["name"],
                "label": pool["label"],
                "description": pool["description"],
                "visible_to_user": pool["visible_to_user"],
                "capabilities": json.dumps(pool["default_capabilities"]),
                "keywords": json.dumps(pool["task_keywords"]),
                "sort_order": pool["sort_order"],
            },
        )
    for pool in BUILTIN_TOOL_SUB_POOLS:
        conn.execute(
            sa.text(
                "INSERT INTO sub_pool_definition (id, pool_type, name, label, description, visible_to_user, default_enabled, default_capabilities, task_keywords, is_system, sort_order, enabled) "
                "VALUES (uuid_generate_v4(), 'tool', :name, :label, :description, :visible_to_user, :default_enabled, '[]'::jsonb, '[]'::jsonb, true, :sort_order, true) "
                "ON CONFLICT (pool_type, name) DO NOTHING"
            ),
            {
                "name": pool["name"],
                "label": pool["label"],
                "description": pool["description"],
                "visible_to_user": pool["visible_to_user"],
                "default_enabled": pool["default_enabled"],
                "sort_order": pool["sort_order"],
            },
        )


def downgrade():
    op.drop_index("sub_pool_definition_enabled_idx", table_name="sub_pool_definition")
    op.drop_index("sub_pool_definition_type_idx", table_name="sub_pool_definition")
    op.drop_table("sub_pool_definition")
