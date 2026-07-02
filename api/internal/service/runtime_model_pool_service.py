from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from injector import inject

from internal.model.model_pool_entity import ModelKeyConfig, ModelPoolConfig
from internal.service.admin_model_pool_service import _decrypt_key_value
from pkg.sqlalchemy import SQLAlchemy


@inject
@dataclass
class RuntimeModelPoolService:
    """桥接 admin 模型池配置与运行时 LLM 调用"""

    db: SQLAlchemy

    def _session(self):
        return self.db.session

    @staticmethod
    def _now() -> datetime:
        return datetime.now(UTC).replace(tzinfo=None)

    def get_active_models(self, tier: str | None = None) -> list[ModelPoolConfig]:
        query = self._session().query(ModelPoolConfig).filter(ModelPoolConfig.status == "active")
        if tier:
            query = query.filter(ModelPoolConfig.tier == tier)
        return query.order_by(
            ModelPoolConfig.priority.desc(),
            ModelPoolConfig.created_at.asc(),
        ).all()

    def select_model_with_fallback(
        self,
        tier: str = "standard",
    ) -> tuple[ModelPoolConfig | None, list[ModelPoolConfig]]:
        models = self.get_active_models(tier)
        if not models:
            return None, []
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
        config: dict[str, Any] = {
            "provider": model.provider,
            "model": model.model_name,
            "parameters": {},
            "api_key": api_key,
            "key_id": str(key.id),
            "model_id": str(model.id),
        }
        if model.base_url:
            config["base_url"] = model.base_url
        return config
