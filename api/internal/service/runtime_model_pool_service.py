import logging
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any, Optional

from injector import inject

from internal.core.language_model.language_model_manager import LanguageModelManager
from internal.model.model_pool_entity import ModelKeyConfig, ModelPoolConfig, ModelTierPolicy
from internal.model.model_provider_entity import ModelProviderConfig
from internal.service.admin_model_pool_service import _decrypt_key_value, CONTEXT_LESS_MODEL_TYPES, normalize_provider_base_url
from pkg.sqlalchemy import SQLAlchemy

logger = logging.getLogger(__name__)


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

    def _key_pool_config(self) -> dict[str, Any]:
        """读取 Key 池熔断配置（表优先、缺省兜底），失败时返回内置默认值。"""
        defaults = {"failure_threshold": 3, "cooldown_seconds": 300}
        try:
            from internal.service.global_control_config_service import (
                GlobalControlConfigService,
            )

            cfg = GlobalControlConfigService(session=self._session()).get_config("model_key_pool")
            if isinstance(cfg, dict) and cfg:
                return {
                    "failure_threshold": int(cfg.get("failure_threshold") or defaults["failure_threshold"]),
                    "cooldown_seconds": int(cfg.get("cooldown_seconds") or defaults["cooldown_seconds"]),
                }
        except Exception:
            logger.warning("读取 model_key_pool 配置失败，使用内置默认值", exc_info=True)
        return defaults

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

    @staticmethod
    def _cost_reference(model: ModelPoolConfig) -> float:
        """同档成本参考：按 3:1 输入输出均衡权重，成本值取自成本基准（元/1k）。
        返回越小越省；两个成本都未配置时返回很大值（排最后，仍可用但非优先）。"""
        in_cost = float(getattr(model, "input_cost_per_1k_tokens", 0) or 0)
        out_cost = float(getattr(model, "output_cost_per_1k_tokens", 0) or 0)
        if in_cost <= 0 and out_cost <= 0:
            return float("inf")
        return in_cost * 3 + out_cost

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
        # 同 priority 组内按成本参考值升序（省模型优先）；priority 仍为第一键
        models.sort(key=lambda m: (0 - int(m.priority or 0), self._cost_reference(m), m.created_at or self._now()))

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
        self._recover_cooled_down_keys(session, provider=model.provider)
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
        threshold = self._key_pool_config()["failure_threshold"]
        if key.failure_count >= threshold:
            key.status = "circuit_open"
            key.circuit_opened_at = self._now()
            circuit_opened = True
        key.updated_at = self._now()
        session.commit()
        return circuit_opened

    def _recover_cooled_down_keys(self, session: Any, *, provider: str) -> None:
        """把冷却期已到的 circuit_open Key 复位为 active（失败计数清零）。

        - 只扫描**本 provider** 的熔断 Key：与 get_keys_for_model 的选键范围一致，
          避免「查 A 模型却复活 B 供应商的 Key」。
        - `circuit_opened_at is None` 视为**不可恢复**：只有带时间戳、且冷却已过的
          Key 才复活。这样既不会在部署时把历史 `circuit_open` 行（无时间戳）静默
          全量复活，也不会让 admin 手动拉闸（set_key_status 不写时间戳）被自动撤销。
        """
        candidates = (
            session.query(ModelKeyConfig)
            .filter(
                ModelKeyConfig.status == "circuit_open",
                ModelKeyConfig.provider == provider,
            )
            .all()
        )
        if not candidates:
            return
        cooldown = self._key_pool_config()["cooldown_seconds"]
        if cooldown < 0:
            return
        deadline = self._now() - timedelta(seconds=cooldown)
        recovered: list[ModelKeyConfig] = []
        for key in candidates:
            opened_at = key.circuit_opened_at
            if opened_at is None or opened_at > deadline:
                continue
            key.status = "active"
            key.failure_count = 0
            key.circuit_opened_at = None
            key.updated_at = self._now()
            recovered.append(key)
        if not recovered:
            return
        session.commit()
        logger.info(
            "Key 池冷却恢复 %d 个 Key provider=%s", len(recovered), provider
        )

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
