import base64
import math
from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID

from internal.exception import NotFoundException
from internal.extension.database_extension import db
from internal.lib.helper import escape_like_pattern
from internal.model.model_pool_entity import (
    CostPolicy,
    ModelKeyConfig,
    ModelPoolConfig,
    ModelTierPolicy,
)


def _encrypt_key_value(value: str) -> str:
    if not value:
        return ""
    return base64.b64encode(value.encode("utf-8")).decode("utf-8")


def _mask_key_value(value: str) -> str:
    if not value:
        return ""
    if len(value) <= 8:
        return "*" * len(value)
    return value[:4] + "*" * (len(value) - 8) + value[-4:]


class AdminModelPoolService:
    def __init__(self, session=None):
        self.session = session or db.session

    @staticmethod
    def _timestamp(value) -> int | None:
        if value is None:
            return None
        return int(value.replace(tzinfo=UTC).timestamp())

    @staticmethod
    def _now() -> datetime:
        return datetime.now(UTC).replace(tzinfo=None)

    @staticmethod
    def _decimal(value, default: str = "0.000000") -> Decimal:
        try:
            return Decimal(str(value if value is not None else default))
        except Exception:
            return Decimal(default)

    def list_models(self, *, search: str = "", provider: str = "", tier: str = "", status: str = "", current_page: int = 1, page_size: int = 20) -> dict:
        current_page = max(int(current_page or 1), 1)
        page_size = max(min(int(page_size or 20), 50), 1)
        query = self.session.query(ModelPoolConfig)
        search = (search or "").strip()
        if search:
            like_value = f"%{escape_like_pattern(search)}%"
            query = query.filter(
                (ModelPoolConfig.model_name.ilike(like_value))
                | (ModelPoolConfig.display_name.ilike(like_value))
            )
        if provider:
            query = query.filter(ModelPoolConfig.provider == provider)
        if tier:
            query = query.filter(ModelPoolConfig.tier == tier)
        if status:
            query = query.filter(ModelPoolConfig.status == status)
        total = query.count()
        models = query.order_by(ModelPoolConfig.created_at.desc()).offset((current_page - 1) * page_size).limit(page_size).all()
        return {
            "list": [self._serialize_model(model) for model in models],
            "paginator": {
                "total_record": total,
                "total_page": math.ceil(total / page_size) if total else 0,
                "current_page": current_page,
                "page_size": page_size,
            },
        }

    def get_model(self, model_id: UUID) -> dict:
        return self._serialize_model(self._get_model_or_raise(model_id))

    def create_model(self, payload: dict) -> dict:
        model = ModelPoolConfig(
            provider=payload["provider"],
            model_name=payload["model_name"],
            display_name=payload.get("display_name") or "",
            tier=payload.get("tier") or "standard",
            capabilities=payload.get("capabilities") or [],
            price_per_1k_tokens=self._decimal(payload.get("price_per_1k_tokens")),
            max_tokens=int(payload.get("max_tokens") or 0),
            status=payload.get("status") or "active",
        )
        self.session.add(model)
        self.session.commit()
        return self._serialize_model(model)

    def update_model(self, model_id: UUID, payload: dict) -> dict:
        model = self._get_model_or_raise(model_id)
        if "provider" in payload:
            model.provider = payload["provider"]
        if "model_name" in payload:
            model.model_name = payload["model_name"]
        if "display_name" in payload:
            model.display_name = payload["display_name"] or ""
        if "tier" in payload:
            model.tier = payload["tier"]
        if "capabilities" in payload:
            model.capabilities = payload["capabilities"] or []
        if "price_per_1k_tokens" in payload:
            model.price_per_1k_tokens = self._decimal(payload.get("price_per_1k_tokens"))
        if "max_tokens" in payload:
            model.max_tokens = int(payload.get("max_tokens") or 0)
        if "status" in payload:
            model.status = payload["status"]
        model.updated_at = self._now()
        self.session.commit()
        return self._serialize_model(model)

    def delete_model(self, model_id: UUID) -> None:
        model = self._get_model_or_raise(model_id)
        self.session.delete(model)
        self.session.commit()

    def set_model_status(self, model_id: UUID, status: str) -> dict:
        model = self._get_model_or_raise(model_id)
        model.status = status
        model.updated_at = self._now()
        self.session.commit()
        return self._serialize_model(model)

    def list_keys(self, *, provider: str = "", status: str = "", current_page: int = 1, page_size: int = 20) -> dict:
        current_page = max(int(current_page or 1), 1)
        page_size = max(min(int(page_size or 20), 50), 1)
        query = self.session.query(ModelKeyConfig)
        if provider:
            query = query.filter(ModelKeyConfig.provider == provider)
        if status:
            query = query.filter(ModelKeyConfig.status == status)
        total = query.count()
        keys = query.order_by(ModelKeyConfig.created_at.desc()).offset((current_page - 1) * page_size).limit(page_size).all()
        return {
            "list": [self._serialize_key(key) for key in keys],
            "paginator": {
                "total_record": total,
                "total_page": math.ceil(total / page_size) if total else 0,
                "current_page": current_page,
                "page_size": page_size,
            },
        }

    def create_key(self, payload: dict) -> dict:
        key = ModelKeyConfig(
            provider=payload["provider"],
            key_alias=payload["key_alias"],
            key_value_encrypted=_encrypt_key_value(payload.get("key_value") or ""),
            tenant_quota=self._decimal(payload.get("tenant_quota"), "0.0000"),
            status=payload.get("status") or "active",
        )
        self.session.add(key)
        self.session.commit()
        return self._serialize_key(key)

    def update_key(self, key_id: UUID, payload: dict) -> dict:
        key = self._get_key_or_raise(key_id)
        if "provider" in payload:
            key.provider = payload["provider"]
        if "key_alias" in payload:
            key.key_alias = payload["key_alias"]
        if "key_value" in payload and payload["key_value"]:
            key.key_value_encrypted = _encrypt_key_value(payload["key_value"])
        if "tenant_quota" in payload:
            key.tenant_quota = self._decimal(payload.get("tenant_quota"), "0.0000")
        if "status" in payload:
            key.status = payload["status"]
        key.updated_at = self._now()
        self.session.commit()
        return self._serialize_key(key)

    def delete_key(self, key_id: UUID) -> None:
        key = self._get_key_or_raise(key_id)
        self.session.delete(key)
        self.session.commit()

    def set_key_status(self, key_id: UUID, status: str) -> dict:
        key = self._get_key_or_raise(key_id)
        key.status = status
        key.updated_at = self._now()
        self.session.commit()
        return self._serialize_key(key)

    def list_tier_policies(self) -> dict:
        policies = self.session.query(ModelTierPolicy).order_by(ModelTierPolicy.tier_code.asc()).all()
        return {"list": [self._serialize_tier_policy(policy) for policy in policies]}

    def update_tier_policy(self, tier_code: str, payload: dict) -> dict:
        policy = self.session.query(ModelTierPolicy).filter(ModelTierPolicy.tier_code == tier_code).one_or_none()
        if policy is None:
            raise NotFoundException("档位策略不存在")
        if "allowed_models" in payload:
            policy.allowed_models = payload["allowed_models"] or []
        if "default_model" in payload:
            policy.default_model = payload["default_model"] or ""
        if "routing_rules" in payload:
            policy.routing_rules = payload["routing_rules"] or {}
        policy.updated_at = self._now()
        self.session.commit()
        return self._serialize_tier_policy(policy)

    def list_cost_policies(self) -> dict:
        policies = self.session.query(CostPolicy).order_by(CostPolicy.created_at.desc()).all()
        return {"list": [self._serialize_cost_policy(policy) for policy in policies]}

    def update_cost_policy(self, policy_id: UUID, payload: dict) -> dict:
        policy = self._get_cost_policy_or_raise(policy_id)
        if "policy_name" in payload:
            policy.policy_name = payload["policy_name"]
        if "model_tier" in payload:
            policy.model_tier = payload["model_tier"]
        if "max_cost_per_request" in payload:
            policy.max_cost_per_request = self._decimal(payload.get("max_cost_per_request"))
        if "billing_mode" in payload:
            policy.billing_mode = payload["billing_mode"]
        if "upgrade_threshold" in payload:
            policy.upgrade_threshold = self._decimal(payload.get("upgrade_threshold"))
        policy.updated_at = self._now()
        self.session.commit()
        return self._serialize_cost_policy(policy)

    def _get_model_or_raise(self, model_id: UUID) -> ModelPoolConfig:
        model = self.session.query(ModelPoolConfig).filter(ModelPoolConfig.id == model_id).one_or_none()
        if model is None:
            raise NotFoundException("模型配置不存在")
        return model

    def _get_key_or_raise(self, key_id: UUID) -> ModelKeyConfig:
        key = self.session.query(ModelKeyConfig).filter(ModelKeyConfig.id == key_id).one_or_none()
        if key is None:
            raise NotFoundException("模型Key不存在")
        return key

    def _get_cost_policy_or_raise(self, policy_id: UUID) -> CostPolicy:
        policy = self.session.query(CostPolicy).filter(CostPolicy.id == policy_id).one_or_none()
        if policy is None:
            raise NotFoundException("成本策略不存在")
        return policy

    def _serialize_model(self, model: ModelPoolConfig) -> dict:
        return {
            "id": str(model.id),
            "provider": model.provider,
            "model_name": model.model_name,
            "display_name": model.display_name or "",
            "tier": model.tier,
            "capabilities": list(model.capabilities or []),
            "price_per_1k_tokens": f"{Decimal(str(model.price_per_1k_tokens or 0)):.6f}",
            "max_tokens": int(model.max_tokens or 0),
            "status": model.status,
            "created_at": self._timestamp(model.created_at),
            "updated_at": self._timestamp(model.updated_at),
        }

    def _serialize_key(self, key: ModelKeyConfig) -> dict:
        raw_value = ""
        try:
            raw_value = base64.b64decode(key.key_value_encrypted.encode("utf-8")).decode("utf-8") if key.key_value_encrypted else ""
        except Exception:
            raw_value = ""
        return {
            "id": str(key.id),
            "provider": key.provider,
            "key_alias": key.key_alias,
            "key_mask": _mask_key_value(raw_value),
            "tenant_quota": f"{Decimal(str(key.tenant_quota or 0)):.4f}",
            "status": key.status,
            "failure_count": int(key.failure_count or 0),
            "created_at": self._timestamp(key.created_at),
            "updated_at": self._timestamp(key.updated_at),
        }

    def _serialize_tier_policy(self, policy: ModelTierPolicy) -> dict:
        return {
            "id": str(policy.id),
            "tier_code": policy.tier_code,
            "allowed_models": list(policy.allowed_models or []),
            "default_model": policy.default_model or "",
            "routing_rules": dict(policy.routing_rules or {}),
            "created_at": self._timestamp(policy.created_at),
            "updated_at": self._timestamp(policy.updated_at),
        }

    def _serialize_cost_policy(self, policy: CostPolicy) -> dict:
        return {
            "id": str(policy.id),
            "policy_name": policy.policy_name,
            "model_tier": policy.model_tier,
            "max_cost_per_request": f"{Decimal(str(policy.max_cost_per_request or 0)):.6f}",
            "billing_mode": policy.billing_mode,
            "upgrade_threshold": f"{Decimal(str(policy.upgrade_threshold or 0)):.6f}",
            "created_at": self._timestamp(policy.created_at),
            "updated_at": self._timestamp(policy.updated_at),
        }
