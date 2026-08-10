# api/internal/core/language_model/language_model_manager.py
"""语言模型管理器 — 动态懒加载缓存版本

替代原静态 yaml 加载，改为从数据库懒加载 Provider/Model 配置，
TTL 60s 兜底 + CRUD 主动失效缓存 + RLock 线程安全。
"""

import logging
import threading
import time
from typing import Any

from injector import inject, singleton
from pydantic import BaseModel, PrivateAttr

from internal.exception import NotFoundException
from internal.model.model_provider_entity import ModelProviderConfig
from internal.model.model_pool_entity import ModelPoolConfig
from .entities.model_entity import ModelEntity, ModelFeature
from .entities.provider_entity import ProviderEntity


# capabilities 标签归一化映射：将人类可读标签映射到 ModelFeature 枚举值
_CAPABILITY_LABEL_TO_FEATURE: dict[str, ModelFeature] = {
    # tool_call 别名
    "tool_call": ModelFeature.TOOL_CALL,
    "tool_calling": ModelFeature.TOOL_CALL,
    "tool": ModelFeature.TOOL_CALL,
    "tools": ModelFeature.TOOL_CALL,
    "function_calling": ModelFeature.TOOL_CALL,
    "function_call": ModelFeature.TOOL_CALL,
    "function calling": ModelFeature.TOOL_CALL,
    "tools_call": ModelFeature.TOOL_CALL,
    # agent_thought 别名
    "agent_thought": ModelFeature.AGENT_THOUGHT,
    "agent": ModelFeature.AGENT_THOUGHT,
    "thought": ModelFeature.AGENT_THOUGHT,
    "reasoning": ModelFeature.AGENT_THOUGHT,
    "reasoning_model": ModelFeature.AGENT_THOUGHT,
}


def _normalize_capability_to_feature(raw: str) -> ModelFeature | None:
    """将 capabilities 字符串归一化为 ModelFeature 枚举值，无法识别时返回 None。"""
    if not isinstance(raw, str):
        return None
    normalized = raw.strip().lower().replace(" ", "_").replace("-", "_")
    # 1. 直接匹配 ModelFeature 枚举值
    try:
        return ModelFeature(normalized)
    except ValueError:
        pass
    # 2. 匹配别名映射
    return _CAPABILITY_LABEL_TO_FEATURE.get(normalized)


from pkg.sqlalchemy import SQLAlchemy

logger = logging.getLogger(__name__)


@inject
@singleton
class LanguageModelManager(BaseModel):
    """语言模型管理器 — 数据库驱动的懒加载缓存"""

    # 使用 PrivateAttr 声明私有属性（pydantic v2 要求）
    _db: Any = PrivateAttr(default=None)
    _provider_cache: dict = PrivateAttr(default_factory=dict)
    _model_cache: dict = PrivateAttr(default_factory=dict)
    _lock: Any = PrivateAttr(default=None)

    CACHE_TTL_SECONDS: int = 60

    model_config = {"arbitrary_types_allowed": True}

    def __init__(self, db: SQLAlchemy = None, **data):
        super().__init__(**data)
        self._db = db
        self._provider_cache: dict[str, tuple[ProviderEntity, float]] = {}
        self._model_cache: dict[str, dict[str, tuple[ModelEntity, float]]] = {}
        self._lock = threading.RLock()

    # ------------------------------------------------------------------
    # Provider 懒加载
    # ------------------------------------------------------------------

    def get_or_load_provider(self, provider_name: str) -> ProviderEntity:
        """懒加载供应商实体，命中缓存直接返回

        Args:
            provider_name: 供应商唯一标识

        Returns:
            ProviderEntity 实例

        Raises:
            NotFoundException: 供应商不存在或已禁用
        """
        with self._lock:
            cached = self._provider_cache.get(provider_name)
            if cached and (time.time() - cached[1]) < self.CACHE_TTL_SECONDS:
                return cached[0]

            if self._db is None:
                raise NotFoundException(f"数据库未初始化，无法加载供应商: {provider_name}")

            provider_config = (
                self._db.session.query(ModelProviderConfig)
                .filter_by(name=provider_name, status="active")
                .first()
            )
            if not provider_config:
                raise NotFoundException(f"供应商 {provider_name} 不存在或已禁用")

            entity = self._build_provider_entity(provider_config)
            self._provider_cache[provider_name] = (entity, time.time())
            self._model_cache.setdefault(provider_name, {})
            return entity

    def get_providers(self) -> list[ProviderEntity]:
        """获取所有 active 供应商列表（用于前端下拉）"""
        if self._db is None:
            return []
        configs = (
            self._db.session.query(ModelProviderConfig)
            .filter_by(status="active")
            .order_by(ModelProviderConfig.created_at.asc())
            .all()
        )
        return [self._build_provider_entity(c) for c in configs]

    # ------------------------------------------------------------------
    # Model 懒加载
    # ------------------------------------------------------------------

    def get_or_load_model_entity(self, provider_name: str, model_name: str) -> ModelEntity:
        """懒加载模型实体

        Args:
            provider_name: 供应商唯一标识
            model_name: 模型名称

        Returns:
            ModelEntity 实例

        Raises:
            NotFoundException: 模型不存在或已禁用
        """
        # 确保 provider 已加载
        provider_entity = self.get_or_load_provider(provider_name)

        with self._lock:
            cache = self._model_cache.get(provider_name, {})
            cached = cache.get(model_name)
            if cached and (time.time() - cached[1]) < self.CACHE_TTL_SECONDS:
                return cached[0]

            if self._db is None:
                raise NotFoundException(f"数据库未初始化，无法加载模型: {model_name}")

            model_config = (
                self._db.session.query(ModelPoolConfig)
                .filter_by(provider=provider_name, model_name=model_name, status="active")
                .first()
            )
            if not model_config:
                raise NotFoundException(f"模型 {model_name} 不存在或已禁用")

            entity = self._build_model_entity(model_config, provider_entity)
            self._model_cache.setdefault(provider_name, {})[model_name] = (entity, time.time())
            return entity

    # ------------------------------------------------------------------
    # 缓存失效
    # ------------------------------------------------------------------

    def invalidate_provider(self, provider_name: str) -> None:
        """失效整个供应商缓存（含其下所有模型）"""
        with self._lock:
            self._provider_cache.pop(provider_name, None)
            self._model_cache.pop(provider_name, None)
        logger.info("Provider 缓存失效: name=%s", provider_name)

    def invalidate_model(self, provider_name: str, model_name: str) -> None:
        """失效单个模型缓存"""
        with self._lock:
            if provider_name in self._model_cache:
                self._model_cache[provider_name].pop(model_name, None)
        logger.info("Model 缓存失效: provider=%s, model=%s", provider_name, model_name)

    def invalidate_all(self) -> None:
        """全量失效缓存（启动/调试用）"""
        with self._lock:
            self._provider_cache.clear()
            self._model_cache.clear()
        logger.info("所有模型缓存已清空")

    # ------------------------------------------------------------------
    # 实体构建（从 DB 记录 → pydantic 实体）
    # ------------------------------------------------------------------

    def _build_provider_entity(self, config: ModelProviderConfig) -> ProviderEntity:
        """从 DB 记录构建 ProviderEntity"""
        from internal.service.admin_model_pool_service import normalize_provider_base_url

        return ProviderEntity(
            name=config.name,
            label=config.label or config.name,
            description=config.description or "",
            icon=config.icon or "",
            background=config.background or "#FFFFFF",
            default_base_url=normalize_provider_base_url(
                config.default_base_url,
                is_full_url=bool(getattr(config, "is_full_url", False)),
            ),
            supported_model_types=config.supported_model_types or ["chat"],
        )

    def _build_model_entity(
        self,
        model_config: ModelPoolConfig,
        provider_entity: ProviderEntity,
    ) -> ModelEntity:
        """从 DB 记录构建 ModelEntity（替代从 yaml 构建）"""
        # 将 capabilities 列表转换为 ModelFeature 枚举列表（支持人类可读标签归一化）
        raw_features = model_config.capabilities or []
        features: list[ModelFeature] = []
        for f in raw_features:
            feature = _normalize_capability_to_feature(f)
            if feature is not None and feature not in features:
                features.append(feature)

        # 上下文窗口与输出上限拆分：输入侧用 max_input_tokens，输出侧用 max_output_tokens
        # （兼容历史 max_tokens 总窗口字段）
        context_window = model_config.max_input_tokens or model_config.max_tokens or 4096
        max_output_tokens = model_config.max_output_tokens or 4096

        return ModelEntity(
            model=model_config.model_name,
            label=model_config.display_name or model_config.model_name,
            model_type=model_config.model_type,
            features=features,
            context_window=context_window,
            max_output_tokens=max_output_tokens,
            attributes={
                "model": model_config.model_name,
                "openai_api_base": provider_entity.default_base_url,
                "openai_api_key": "",  # 由 attribute_overrides 运行时注入
            },
            parameters=[],
            metadata={
                "pricing": {
                    "input": float(model_config.price_per_1k_tokens or 0),
                    "output": float(model_config.price_per_1k_tokens or 0),
                    "unit": 0.001,
                },
                "model_type": model_config.model_type,
                "compatible_api": model_config.compatible_api,
                "tier": model_config.tier,
                "priority": model_config.priority,
                "fallback_model_id": model_config.fallback_model_id,
                # 供运行时上下文控制消费：输入窗口（记忆/上下文裁剪预算）与输出上限
                "context_window": context_window,
                "max_output_tokens": max_output_tokens,
            },
        )
