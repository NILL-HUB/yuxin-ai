# api/internal/service/public_ai_feature_service.py
"""公共 AI 功能配置服务。

提供按 feature_key 读取模型配置的统一入口。
被 LanguageModelService.get_feature_model / get_feature_credentials 调用。
"""
import logging
from dataclasses import dataclass
from typing import Any

from injector import inject

from internal.model import PublicAIFeatureConfig
from internal.model.model_pool_entity import ModelPoolConfig
from pkg.sqlalchemy import SQLAlchemy

logger = logging.getLogger(__name__)


# 系统预置的 feature_key 默认配置。
# feature_key 由代码注册，管理员在后台仅为其绑定模型/开关/档位，不能新建或删除。
# 启动时通过 ensure_builtin_features() 自动补齐缺失记录，避免迁移脚本多 head 问题。
_BUILTIN_FEATURES: list[dict[str, Any]] = [
    {
        "feature_key": "conductor",
        "feature_name": "指挥官决策",
        "feature_category": "routing",
        "feature_description": "LLM 指挥官：任务规划、Agent 派发、模型档位匹配",
        "model_type": "chat",
        "fallback_tier": "3",  # 指挥官需要强模型，默认档位 3
        "billable": False,     # 系统治理功能，系统承担成本（平台路由决策，用户不直接受益）
    },
    {
        "feature_key": "schedule_intent_parser",
        "feature_name": "定时任务配置解析",
        "feature_category": "routing",
        "feature_description": "把用户一句话需求解析为 6 段秒级 cron + 精化 prompt + 缺失字段反问",
        "model_type": "chat",
        "fallback_tier": "3",  # 配置解析需要较强的结构化输出能力
        "billable": False,     # 系统侧辅助调用（用户创建定时任务时后台解析），系统承担成本
    },
]


@inject
@dataclass
class PublicAIFeatureService:
    """公共 AI 功能配置读取服务。"""

    db: SQLAlchemy

    def ensure_builtin_features(self) -> int:
        """启动时补齐系统预置的 feature_key 记录。

        已存在的 feature_key 不覆盖（保留管理员配置）。
        返回新插入的记录数。
        """
        inserted = 0
        for feat in _BUILTIN_FEATURES:
            existing = self.get_feature_config(feat["feature_key"])
            if existing is not None:
                continue
            try:
                self.db.session.add(PublicAIFeatureConfig(
                    feature_key=feat["feature_key"],
                    feature_name=feat["feature_name"],
                    feature_category=feat["feature_category"],
                    feature_description=feat["feature_description"],
                    model_config_id=None,
                    enabled=True,
                    fallback_tier=feat["fallback_tier"],
                    model_type=feat["model_type"],
                    billable=feat["billable"],
                    extra_config={},
                ))
                inserted += 1
            except Exception:
                logger.warning(
                    "ensure_builtin_features: 插入失败 feature_key=%s",
                    feat["feature_key"],
                    exc_info=True,
                )
        if inserted > 0:
            self.db.session.commit()
            logger.info("ensure_builtin_features: 补齐 %d 条预置功能配置", inserted)
        return inserted

    def get_feature_config(self, feature_key: str) -> PublicAIFeatureConfig | None:
        """按 feature_key 读取配置记录，不存在返回 None。"""
        try:
            return self.db.session.query(PublicAIFeatureConfig).filter_by(
                feature_key=feature_key,
            ).first()
        except Exception:
            logger.warning("get_feature_config: 读取失败 feature_key=%s", feature_key, exc_info=True)
            return None

    def get_feature_model_config(self, feature_key: str) -> ModelPoolConfig | None:
        """读取功能绑定的 model_pool_config 记录。

        优先返回 model_config_id 指向的模型；未配置或不可用时返回 None
        （调用方应根据 fallback_tier 自动降级）。
        """
        cfg = self.get_feature_config(feature_key)
        if cfg is None or not cfg.enabled or cfg.model_config_id is None:
            return None
        try:
            return self.db.session.query(ModelPoolConfig).filter_by(
                id=cfg.model_config_id,
                status="active",
            ).first()
        except Exception:
            logger.warning("get_feature_model_config: 模型查询失败 feature_key=%s", feature_key, exc_info=True)
            return None

    def touch_last_called(self, feature_key: str) -> None:
        """更新功能最后调用时间，用于管理员识别未使用的配置。

        在 get_feature_model() 成功返回时调用。采用低频更新策略：同进程内 60s 内
        重复调用跳过，避免高频功能每次调用都写库。
        """
        import time as _time
        now = _time.time()
        cache_key = f"_touch_ts:{feature_key}"
        last = getattr(self, cache_key, 0)
        if now - last < 60:
            return
        setattr(self, cache_key, now)
        try:
            from sqlalchemy import text
            self.db.session.execute(
                text(
                    "UPDATE public_ai_feature_config SET last_called_at = NOW() "
                    "WHERE feature_key = :key"
                ),
                {"key": feature_key},
            )
            self.db.session.commit()
        except Exception:
            logger.debug("touch_last_called 更新失败 feature_key=%s", feature_key, exc_info=True)
            self.db.session.rollback()

    def get_feature_fallback_tier(self, feature_key: str) -> str:
        """读取功能的回退档位，未配置返回 'cheap'。"""
        cfg = self.get_feature_config(feature_key)
        if cfg is None:
            return "cheap"
        return (cfg.fallback_tier or "cheap").lower()

    def get_feature_model_type(self, feature_key: str) -> str:
        """读取功能所需的模型类型，未配置返回 'chat'。"""
        cfg = self.get_feature_config(feature_key)
        if cfg is None:
            return "chat"
        return (cfg.model_type or "chat").lower()

    def is_feature_enabled(self, feature_key: str) -> bool:
        """功能是否启用。未配置记录视为启用（走 fallback）。"""
        cfg = self.get_feature_config(feature_key)
        if cfg is None:
            return True
        return bool(cfg.enabled)

    def list_all_features(self) -> list[PublicAIFeatureConfig]:
        """列出所有配置记录，用于管理后台展示。"""
        return self.db.session.query(PublicAIFeatureConfig).order_by(
            PublicAIFeatureConfig.feature_category.asc(),
            PublicAIFeatureConfig.feature_key.asc(),
        ).all()
