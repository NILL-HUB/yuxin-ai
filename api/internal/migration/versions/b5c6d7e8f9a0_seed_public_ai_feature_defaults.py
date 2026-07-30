# api/internal/migration/versions/b5c6d7e8f9a0_seed_public_ai_feature_defaults.py
"""seed default public_ai_feature_config records

Revision ID: b5c6d7e8f9a0
Revises: a4b5c6d7e8f9
Create Date: 2026-07-20 11:00:00.000000

预置公共 AI 功能配置默认记录，所有记录 model_config_id=NULL（未绑定具体模型），
fallback_tier='cheap'，enabled=true。管理员可在后台为每个功能绑定具体模型。
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "b5c6d7e8f9a0"
down_revision = "a4b5c6d7e8f9"
branch_labels = None
depends_on = None


# 默认功能配置清单
# 每条记录第 5 个字段 billable 标记是否扣用户额度：
#   True  = 用户直接请求流程中触发，用户直接受益，应扣用户额度
#   False = 系统后台维护或平台治理功能，系统承担成本
# 注意：billable 列由后续迁移 d8e9f0a1b2c3 添加并回填，此处仅作数据登记，
# INSERT 不包含 billable 列以保证全新部署时 seed 阶段不会因列缺失而失败。
_DEFAULT_FEATURES = [
    ("icon_prompt", "图标提示词生成", "icon", "图标生成时的描述提示词 LLM 调用", False),
    ("icon_image_generation", "图标图像生成", "icon", "图标生成的文生图 API 调用", False),
    ("memory_consolidation", "记忆巩固", "memory", "簇内 Episode 共性语义提取", False),
    ("memory_conflict_detection", "记忆冲突检测", "memory", "记忆冲突检测判定", False),
    ("memory_compression", "记忆压缩", "memory", "Layer 4 LLM 压缩", False),
    ("memory_explicit_detection", "显式陈述检测", "memory", "显式陈述确认", False),
    ("memory_entity_resolution", "实体同一性判定", "memory", "实体同一性判定", False),
    ("memory_entity_extraction", "实体关系抽取", "memory", "实体/关系抽取与对话摘要", False),
    ("memory_digest", "记忆摘要", "memory", "记忆摘要 LLM 精炼", False),
    ("memory_policy_routing", "查询意图分类", "memory", "记忆查询意图分类", False),
    ("memory_salience_scoring", "显著性评分", "memory", "六因子显著性评分", False),
    ("memory_write_conflict_resolution", "写时冲突判定", "memory", "写时冲突判定", False),
    ("memory_skill_emergence", "技能涌现", "memory", "技能模板提取与更新判定", False),
    ("intent_recognition", "意图识别", "routing", "用户意图识别", False),
    ("task_classification", "任务分类", "routing", "任务分类", False),
    ("task_decomposition", "任务分解", "routing", "多智能体任务分解", False),
    ("pool_intent_resolution", "子池匹配", "routing", "子池匹配判定", False),
    ("tool_selection", "工具选择", "routing", "LLM 根据查询语义选择最相关的 builtin 工具", False),
    ("prompt_optimization", "提示词优化", "assistant", "提示词优化助手", True),
    ("code_assistant", "代码助手", "assistant", "Python 代码助手", True),
    ("schema_assistant", "Schema 助手", "assistant", "OpenAPI/MCP Schema 助手", True),
    ("tag_assignment", "标签分配", "assistant", "自动标签分配", True),
    ("app_auto_creation", "应用自动创建", "assistant", "应用自动创建预设 prompt 生成", False),
    ("conversation_summary", "会话摘要", "conversation", "会话摘要/标题/建议问题生成", True),
    ("assistant_agent_intro", "辅助 Agent 介绍", "conversation", "辅助 Agent 介绍生成", True),
    ("direct_answer", "直接回答", "conversation", "Orchestrator direct_answer 模式", True),
    ("rerank_fallback", "重排兜底", "conversation", "provider rerank 不可用时 LLM 兜底", True),
]


def upgrade() -> None:
    conn = op.get_bind()
    for feature_key, feature_name, category, description, _billable in _DEFAULT_FEATURES:
        conn.execute(
            sa.text(
                "INSERT INTO public_ai_feature_config "
                "(feature_key, feature_name, feature_category, feature_description, "
                " model_config_id, provider_credential_key, enabled, fallback_tier, extra_config, updated_at, created_at) "
                "VALUES (:key, :name, :cat, :desc, NULL, NULL, true, 'cheap', '{}'::jsonb, NOW(), NOW()) "
                "ON CONFLICT (feature_key) DO NOTHING"
            ),
            {
                "key": feature_key,
                "name": feature_name,
                "cat": category,
                "desc": description,
            },
        )


def downgrade() -> None:
    conn = op.get_bind()
    keys = [f[0] for f in _DEFAULT_FEATURES]
    conn.execute(
        sa.text("DELETE FROM public_ai_feature_config WHERE feature_key = ANY(:keys)"),
        {"keys": keys},
    )
