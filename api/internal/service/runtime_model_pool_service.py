from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any, Optional

from injector import inject

from internal.core.language_model.language_model_manager import LanguageModelManager
from internal.model.model_pool_entity import ModelKeyConfig, ModelPoolConfig, ModelTierPolicy
from internal.model.model_provider_entity import ModelProviderConfig
from internal.service.admin_model_pool_service import _decrypt_key_value, CONTEXT_LESS_MODEL_TYPES, normalize_provider_base_url
from pkg.sqlalchemy import SQLAlchemy


@inject
@dataclass
class RuntimeModelPoolService:
    """桥接 admin 模型池配置与运行时 LLM 调用"""

    db: SQLAlchemy
    language_model_manager: Optional[LanguageModelManager] = None

    def _session(self):
        return self.db.session

    @staticmethod
    def _now() -> datetime:
        return datetime.now(UTC).replace(tzinfo=None)

    def get_active_models(self, tier: str | None = None, model_type: str | None = None) -> list[ModelPoolConfig]:
        query = self._session().query(ModelPoolConfig).filter(ModelPoolConfig.status == "active")
        if tier:
            query = query.filter(ModelPoolConfig.tier == tier)
        if model_type:
            query = query.filter(ModelPoolConfig.model_type == model_type)
        return query.order_by(
            ModelPoolConfig.priority.desc(),
            ModelPoolConfig.created_at.asc(),
        ).all()

    def _get_tier_policy(self, tier: str) -> ModelTierPolicy | None:
        """查询档位策略配置（包含 default_model 和 allowed_models 白名单）。"""
        return self._session().query(ModelTierPolicy).filter(ModelTierPolicy.tier_code == tier).one_or_none()

    def select_model_with_fallback(
        self,
        tier: str = "2",
        model_type: str | None = None,
    ) -> tuple[ModelPoolConfig | None, list[ModelPoolConfig]]:
        models = self.get_active_models(tier, model_type)
        if not models:
            return None, []

        # 读取档位策略配置
        policy = self._get_tier_policy(tier)
        if policy is None:
            # 无策略配置，按原逻辑取 priority 最高的
            return models[0], models[1:]

        # 应用 allowed_models 白名单过滤（如果配置了非空白名单）
        allowed = policy.allowed_models or []
        if allowed:
            # allowed_models 存储的是模型 ID 列表
            allowed_set = {str(item) for item in allowed}
            filtered = [m for m in models if str(m.id) in allowed_set]
            if filtered:
                models = filtered

        # 优先使用 default_model（如果在白名单内且 active）
        default_model_id = (policy.default_model or "").strip()
        if default_model_id:
            for i, m in enumerate(models):
                if str(m.id) == default_model_id:
                    # 将默认模型移到首位
                    return m, models[:i] + models[i + 1:]

        # 无 default_model 或 default_model 不在候选中，取排序后第一个
        return models[0], models[1:]

    def get_keys_for_model(self, model_id: Any) -> list[ModelKeyConfig]:
        session = self._session()
        model = session.query(ModelPoolConfig).filter(ModelPoolConfig.id == model_id).one_or_none()
        if model is None:
            return []
        now = self._now()
        model_id_text = str(model.id)
        query = session.query(ModelKeyConfig).filter(
            ModelKeyConfig.status == "active",
            (ModelKeyConfig.effective_at.is_(None)) | (ModelKeyConfig.effective_at <= now),
            (ModelKeyConfig.expires_at.is_(None)) | (ModelKeyConfig.expires_at > now),
            (ModelKeyConfig.used_credits < ModelKeyConfig.tenant_quota) | (ModelKeyConfig.tenant_quota <= 0),
        )
        query = query.filter(
            ((ModelKeyConfig.model_id.is_(None)) & (ModelKeyConfig.provider == model.provider))
            | (ModelKeyConfig.model_id == model_id_text)
        )
        return query.order_by(
            ModelKeyConfig.used_credits.asc(),
            ModelKeyConfig.created_at.asc(),
        ).all()

    def select_key(self, model_id: Any) -> ModelKeyConfig | None:
        keys = self.get_keys_for_model(model_id)
        return keys[0] if keys else None

    def record_key_success(self, key_id: Any, credits_used: float = 0.0) -> None:
        session = self._session()
        key = session.query(ModelKeyConfig).filter(ModelKeyConfig.id == key_id).one_or_none()
        if key is None:
            return
        key.used_credits = Decimal(str(key.used_credits or 0)) + Decimal(str(credits_used or 0))
        key.last_used_at = self._now()
        tenant_quota = Decimal(str(key.tenant_quota or 0))
        if tenant_quota > 0 and Decimal(str(key.used_credits)) >= tenant_quota:
            key.status = "disabled"
        key.updated_at = self._now()
        session.commit()

    def record_key_failure(self, key_id: Any) -> bool:
        session = self._session()
        key = session.query(ModelKeyConfig).filter(ModelKeyConfig.id == key_id).one_or_none()
        if key is None:
            return False
        key.failure_count = int(key.failure_count or 0) + 1
        circuit_opened = False
        if key.failure_count >= 3:
            key.status = "circuit_open"
            circuit_opened = True
        key.updated_at = self._now()
        session.commit()
        return circuit_opened

    def build_llm_config(self, model: ModelPoolConfig, key: ModelKeyConfig) -> dict[str, Any]:
        api_key = _decrypt_key_value(key.key_value_encrypted)
        parameters: dict[str, Any] = {}
        # 注入输出长度上限：按模型池配置的 max_output_tokens 限制单次生成长度，
        # 避免"只写总上限导致上下文爆掉"——输出侧独立受控
        if model.model_type not in CONTEXT_LESS_MODEL_TYPES and (model.max_output_tokens or 0) > 0:
            parameters["max_tokens"] = int(model.max_output_tokens)
        config: dict[str, Any] = {
            "provider": model.provider,
            "model": model.model_name,
            "parameters": parameters,
            "api_key": api_key,
            "key_id": str(key.id),
            "model_id": str(model.id),
        }
        # 获取 Provider 的 base_url：优先用 LanguageModelManager 缓存，降级直接查库
        base_url = ""
        try:
            if self.language_model_manager is not None:
                provider_entity = self.language_model_manager.get_or_load_provider(model.provider)
                base_url = provider_entity.default_base_url or ""
        except Exception:
            pass
        if not base_url:
            try:
                provider_config = self._session().query(ModelProviderConfig).filter_by(name=model.provider).first()
                if provider_config and provider_config.default_base_url:
                    base_url = normalize_provider_base_url(
                        provider_config.default_base_url,
                        is_full_url=bool(getattr(provider_config, "is_full_url", False)),
                    )
            except Exception:
                pass
        if base_url:
            config["base_url"] = base_url
        return config
