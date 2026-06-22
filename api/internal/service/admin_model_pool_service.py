import logging
import math
import os
from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID

from cryptography.fernet import Fernet, InvalidToken

from internal.exception import NotFoundException
from internal.extension.database_extension import db
from internal.lib.helper import escape_like_pattern
from internal.model.model_pool_entity import (
    CostPolicy,
    ModelKeyConfig,
    ModelPoolConfig,
    ModelTierPolicy,
)


logger = logging.getLogger(__name__)


def _load_fernet() -> Fernet:
    raw_key = os.getenv("MODEL_KEY_ENCRYPTION_KEY", "").strip()
    if not raw_key:
        raw_key = Fernet.generate_key().decode("utf-8")
        logger.warning(
            "MODEL_KEY_ENCRYPTION_KEY 未配置，已生成临时内存密钥，重启后将无法解密历史 Key，请尽快配置该环境变量"
        )
    try:
        return Fernet(raw_key.encode("utf-8"))
    except (ValueError, TypeError) as exc:
        raise ValueError("MODEL_KEY_ENCRYPTION_KEY 不是合法的 Fernet 密钥，请使用 Fernet.generate_key() 生成") from exc


_FERNET = _load_fernet()


def _encrypt_key_value(value: str) -> str:
    if not value:
        return ""
    return _FERNET.encrypt(value.encode("utf-8")).decode("utf-8")


def _decrypt_key_value(token: str) -> str:
    if not token:
        return ""
    try:
        return _FERNET.decrypt(token.encode("utf-8")).decode("utf-8")
    except (InvalidToken, ValueError):
        return ""


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

    @staticmethod
    def _parse_datetime(value) -> datetime | None:
        if value is None or value == "":
            return None
        if isinstance(value, datetime):
            return value.replace(tzinfo=None) if value.tzinfo else value
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            try:
                return datetime.fromtimestamp(int(value), tz=UTC).replace(tzinfo=None)
            except (OverflowError, OSError, ValueError):
                return None
        if isinstance(value, str):
            text = value.strip()
            if text.isdigit():
                try:
                    return datetime.fromtimestamp(int(text), tz=UTC).replace(tzinfo=None)
                except (OverflowError, OSError, ValueError):
                    return None
            try:
                parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
                return parsed.astimezone(UTC).replace(tzinfo=None) if parsed.tzinfo else parsed
            except ValueError:
                return None
        return None

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
            fallback_model_id=payload.get("fallback_model_id") or None,
            priority=int(payload.get("priority") or 0),
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
        if "fallback_model_id" in payload:
            model.fallback_model_id = payload["fallback_model_id"] or None
        if "priority" in payload:
            model.priority = int(payload.get("priority") or 0)
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
            model_id=payload.get("model_id") or None,
            expires_at=self._parse_datetime(payload.get("expires_at")),
            used_credits=self._decimal(payload.get("used_credits"), "0.0000"),
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
        if "model_id" in payload:
            key.model_id = payload["model_id"] or None
        if "expires_at" in payload:
            key.expires_at = self._parse_datetime(payload.get("expires_at"))
        if "used_credits" in payload:
            key.used_credits = self._decimal(payload.get("used_credits"), "0.0000")
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
            "fallback_model_id": model.fallback_model_id or None,
            "priority": int(model.priority or 0),
            "created_at": self._timestamp(model.created_at),
            "updated_at": self._timestamp(model.updated_at),
        }

    def _serialize_key(self, key: ModelKeyConfig) -> dict:
        raw_value = _decrypt_key_value(key.key_value_encrypted)
        return {
            "id": str(key.id),
            "provider": key.provider,
            "key_alias": key.key_alias,
            "key_mask": _mask_key_value(raw_value),
            "tenant_quota": f"{Decimal(str(key.tenant_quota or 0)):.4f}",
            "status": key.status,
            "failure_count": int(key.failure_count or 0),
            "used_credits": f"{Decimal(str(key.used_credits or 0)):.4f}",
            "model_id": key.model_id or None,
            "last_used_at": self._timestamp(key.last_used_at),
            "expires_at": self._timestamp(key.expires_at),
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
