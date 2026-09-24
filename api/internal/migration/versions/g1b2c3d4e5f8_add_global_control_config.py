"""add global control config table

Revision ID: g1b2c3d4e5f8
Revises: f3e4d5c6b7a8
Create Date: 2026-09-23 00:00:00.000000

admin「系统配置 → 全局控制配置」板块的存储表：单行 JSONB（id=1），按 section
分组存放全局行为配置（模型运行时降级 / 外部素材获取 / 会话级 Checkpoint /
技能目录同步 / 图像请求策略 / 视觉兜底模型）。

一次性数据迁移：把 public_ai_feature_config 中三条行为开关类旧 feature
（runtime_fallback / media_fetch / agent_checkpoint_by_conversation）的值搬入
新表对应 section，搬入成功后删除旧记录（模型绑定语义交由 /admin/public-ai-features
继续管理；_BUILTIN_FEATURES 不再 seed 这三条）。

down_revision 指向当前单 head f3e4d5c6b7a8。
"""
import json

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = "g1b2c3d4e5f8"
down_revision = "f3e4d5c6b7a8"
branch_labels = None
depends_on = None

# 新表默认配置：与收编前各读取点的默认行为保持一致（防行为漂移）。
# runtime_fallback enabled 默认 true、media_fetch / agent_checkpoint 默认 false、
# image_request_policy 默认 strict、skill_catalog_sync 默认关（沿用 SKILL_CATALOG_SYNC_ENABLED 默认）。
_DEFAULT_CONFIGS = {
    "runtime_fallback": {"enabled": True, "retry_attempts": 5},
    "media_fetch": {"enabled": False, "max_bytes_fallback": 536870912},
    "agent_checkpoint": {"enabled": False},
    "skill_catalog_sync": {"enabled": False},
    "image_request_policy": {"policy": "strict"},
    "vision_fallback": {"provider": "", "model": ""},
}

# 旧 feature_key → 新 section 的映射（值为该 section 中需要从旧记录搬入的键）
_LEGACY_FEATURE_TO_SECTION = {
    "runtime_fallback": "runtime_fallback",
    "media_fetch": "media_fetch",
    "agent_checkpoint_by_conversation": "agent_checkpoint",
}


def _build_configs_from_legacy_rows(rows) -> dict:
    """把旧 public_ai_feature_config 行（feature_key, enabled, extra_config）合并进默认配置。

    纯函数便于迁移守卫测试；未知 feature_key 行会被跳过。
    """
    configs = {section: dict(defaults) for section, defaults in _DEFAULT_CONFIGS.items()}
    for feature_key, enabled, extra_config in rows:
        section = _LEGACY_FEATURE_TO_SECTION.get(feature_key)
        if section is None:
            continue
        section_cfg = configs.setdefault(section, {})
        if enabled is not None:
            section_cfg["enabled"] = bool(enabled)
        extra = dict(extra_config or {}) if isinstance(extra_config, dict) else {}
        if section == "runtime_fallback" and "retry_attempts" in extra:
            try:
                value = int(extra["retry_attempts"])
                if value > 0:
                    section_cfg["retry_attempts"] = value
            except (TypeError, ValueError):
                pass
        if section == "media_fetch" and "max_bytes_fallback" in extra:
            try:
                value = int(extra["max_bytes_fallback"])
                if value > 0:
                    section_cfg["max_bytes_fallback"] = value
            except (TypeError, ValueError):
                pass
    return configs


def upgrade():
    op.create_table(
        "global_control_config",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("configs", JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP(0)")),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP(0)")),
    )
    op.execute("INSERT INTO global_control_config (id) VALUES (1) ON CONFLICT (id) DO NOTHING")

    bind = op.get_bind()
    rows = bind.execute(
        sa.text(
            "SELECT feature_key, enabled, extra_config FROM public_ai_feature_config "
            "WHERE feature_key IN ('runtime_fallback', 'media_fetch', 'agent_checkpoint_by_conversation')"
        )
    ).fetchall()

    configs = _build_configs_from_legacy_rows(rows)

    bind.execute(
        sa.text("UPDATE global_control_config SET configs = CAST(:configs AS JSONB) WHERE id = 1"),
        {"configs": json.dumps(configs, ensure_ascii=False)},
    )

    # 旧 feature 值成功搬入后删除旧记录（模型绑定语义不受影响，此三条本就不选模型）
    bind.execute(
        sa.text(
            "DELETE FROM public_ai_feature_config WHERE feature_key IN :feature_keys"
        ).bindparams(
            sa.bindparam("feature_keys", expanding=True),
        ),
        {"feature_keys": list(_LEGACY_FEATURE_TO_SECTION.keys())},
    )


def downgrade():
    # 回滚：删除新表即可；旧 feature 记录由 _BUILTIN_FEATURES seed 在启动时重新补齐
    op.drop_table("global_control_config")
