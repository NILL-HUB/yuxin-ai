from uuid import UUID

from internal.extension.database_extension import db
from internal.model.distribution import PaymentProviderConfig
from internal.service import tool_credential_encryptor
from internal.service.payment.gateway_base import normalize_provider

SUPPORTED_PROVIDERS = ("wechat", "alipay")

# 需要加密存储的密钥字段白名单
SECRET_CONFIG_KEYS = {
    "mch_id",
    "mch_key",
    "app_secret",
    "private_key",
    "apiclient_key",
    "ali_public_key",
    "notify_secret",
    "serial_no",
    "api_v3_key",
    "platform_public_key",
    "merchant_private_key",
}
# 明文展示字段（appid/商户展示名等）
PLAIN_CONFIG_KEYS = {
    "app_id",
    "appid",
    "seller_id",
    "public_key",
    "notify_url",
    "return_url",
}


class PaymentConfigService:
    """支付渠道配置（微信支付 / 支付宝）。

    与存储切换源同构：配置落库、JSON 存储、密钥 Fernet 加密、读取脱敏；
    两渠道可同时启停。真实网关 SDK 未接入时仅承载配置，下单走适配器桩。
    """

    def __init__(self, session=None):
        self.session = session or db.session

    def get(self, provider: str) -> PaymentProviderConfig | None:
        provider = normalize_provider(provider)
        return (
            self.session.query(PaymentProviderConfig)
            .filter(PaymentProviderConfig.provider == provider)
            .one_or_none()
        )

    def is_enabled(self, provider: str) -> bool:
        config = self.get(provider)
        return bool(config and config.enabled)

    def list_sanitized(self) -> list[dict]:
        rows = (
            self.session.query(PaymentProviderConfig)
            .order_by(PaymentProviderConfig.created_at.asc())
            .all()
        )
        return [self._sanitize(row) for row in rows]

    def upsert(self, provider: str, name: str, configs: dict, updated_by: UUID | None = None) -> PaymentProviderConfig:
        provider = normalize_provider(provider)
        if provider not in SUPPORTED_PROVIDERS:
            raise ValueError(f"不支持的支付渠道: {provider}")
        config = self.get(provider)
        encrypted = self._encrypt_payload(configs)
        if config is None:
            config = PaymentProviderConfig(
                provider=provider,
                name=name or provider,
                configs=encrypted,
                enabled=False,
                updated_by=updated_by,
            )
            self.session.add(config)
        else:
            config.name = name or config.name or provider
            config.configs = encrypted
            config.updated_by = updated_by
        self.session.commit()
        return config

    def set_enabled(self, provider: str, enabled: bool, updated_by: UUID | None = None) -> PaymentProviderConfig:
        provider = normalize_provider(provider)
        config = self.get(provider)
        if config is None:
            config = PaymentProviderConfig(
                provider=provider,
                name=provider,
                configs={},
                enabled=bool(enabled),
                updated_by=updated_by,
            )
            self.session.add(config)
        else:
            config.enabled = bool(enabled)
            config.updated_by = updated_by
        self.session.commit()
        return config

    def ensure_defaults(self) -> None:
        """启动时补齐渠道占位配置（默认禁用），并迁移历史 wechatpay 命名为 wechat。"""
        legacy = (
            self.session.query(PaymentProviderConfig)
            .filter(PaymentProviderConfig.provider == "wechatpay")
            .one_or_none()
        )
        if legacy is not None:
            current = self.get("wechat")
            if current is None:
                legacy.provider = "wechat"
                self.session.add(legacy)
            else:
                if legacy.enabled and not current.enabled:
                    current.enabled = True
                self.session.delete(legacy)
        for provider in SUPPORTED_PROVIDERS:
            if self.get(provider) is None:
                self.session.add(
                    PaymentProviderConfig(
                        provider=provider,
                        name={"wechat": "微信支付", "alipay": "支付宝"}[provider],
                        configs={},
                        enabled=False,
                    )
                )
        try:
            self.session.commit()
        except Exception:
            self.session.rollback()

    def decrypt_payload(self, config: PaymentProviderConfig) -> dict:
        """解密密钥字段供网关适配器使用。"""
        payload = dict(config.configs or {})
        for key, value in list(payload.items()):
            if key in SECRET_CONFIG_KEYS and isinstance(value, str) and value:
                payload[key] = tool_credential_encryptor._decrypt_value(value)
        return payload

    def _encrypt_payload(self, configs: dict) -> dict:
        payload = {}
        for key, value in dict(configs or {}).items():
            if key not in (SECRET_CONFIG_KEYS | PLAIN_CONFIG_KEYS):
                continue
            if key in SECRET_CONFIG_KEYS and value:
                payload[key] = tool_credential_encryptor._encrypt_value(str(value))
            else:
                payload[key] = value
        return payload

    def _sanitize(self, config: PaymentProviderConfig) -> dict:
        payload = dict(config.configs or {})
        sanitized = {}
        for key, value in payload.items():
            if key in SECRET_CONFIG_KEYS and isinstance(value, str) and value:
                sanitized[key] = tool_credential_encryptor._mask_value(tool_credential_encryptor._decrypt_value(value))
            else:
                sanitized[key] = value
        return {
            "provider": config.provider,
            "name": config.name,
            "enabled": bool(config.enabled),
            "configs": sanitized,
            "updated_at": config.updated_at.timestamp() if config.updated_at else None,
        }