"""系统推送配置服务：单行 JSONB（id=1），密钥字段 Fernet 加密 + 掩码读取。

主备次序（2026-10-04 确认）：**个推为主、友盟为辅**；两家凭证均加密存储，
读取掩码展示；运行时经 `get_runtime_config()` 取解密凭证（仅服务端消费）。
照 mail_config / sms_config / desktop_client_config 同款模式（单行 JSONB + XxxConfigService）。
"""
from __future__ import annotations

from internal.extension.database_extension import db
from internal.model.push_channel import PushConfig
from .tool_credential_encryptor import _decrypt_value, _encrypt_value

# 密钥掩码：get_config 用它替换已设置的密文（前端提交该值表示“不修改”）
MASK = "******"
PROVIDERS = ("getui", "umeng")

DEFAULT_KEYS = {
    "enabled": False,
    "primary_provider": "getui",
    "fallback_enabled": True,
    "getui": {"app_id": "", "app_key": "", "app_secret": "", "master_secret": ""},
    "umeng": {"app_key": "", "app_master_secret": "", "production_mode": True},
}

_GLOBAL_BOOL_KEYS = ("enabled", "fallback_enabled")
_GETUI_STR_KEYS = ("app_id", "app_key")
_GETUI_SECRET_KEYS = ("app_secret", "master_secret")
_UMENG_STR_KEYS = ("app_key",)
_UMENG_SECRET_KEYS = ("app_master_secret",)


def _normalize_bool(value) -> bool:
    if isinstance(value, bool):
        return value
    return str(value or "").strip().lower() in ("1", "true", "yes", "on")


class PushConfigService:
    """系统推送配置：单行记录（id=1），configs JSONB 持久化；密钥字段密文存储。"""

    def __init__(self, session=None):
        self.session = session or db.session

    def _row(self) -> PushConfig:
        row = self.session.query(PushConfig).filter(PushConfig.id == 1).one_or_none()
        if row is None:
            row = PushConfig(id=1, configs={})
            self.session.add(row)
            self.session.flush()
        return row

    # ------------------------------------------------------------------ 读（掩码）

    def get_config(self) -> dict:
        """返回展示用配置：密钥字段以掩码替代（未设置则为空串）。"""
        stored = dict(self._row().configs or {})
        cfg = {
            "enabled": _normalize_bool(stored.get("enabled", DEFAULT_KEYS["enabled"])),
            "primary_provider": str(stored.get("primary_provider") or DEFAULT_KEYS["primary_provider"]),
            "fallback_enabled": _normalize_bool(
                stored.get("fallback_enabled", DEFAULT_KEYS["fallback_enabled"])
            ),
            "getui": {},
            "umeng": {},
        }
        getui_stored = dict(stored.get("getui") or {})
        for key in _GETUI_STR_KEYS:
            cfg["getui"][key] = str(getui_stored.get(key) or "")
        for key in _GETUI_SECRET_KEYS:
            cfg["getui"][key] = MASK if str(getui_stored.get(key) or "") else ""
        umeng_stored = dict(stored.get("umeng") or {})
        for key in _UMENG_STR_KEYS:
            cfg["umeng"][key] = str(umeng_stored.get(key) or "")
        cfg["umeng"]["production_mode"] = _normalize_bool(
            umeng_stored.get("production_mode", DEFAULT_KEYS["umeng"]["production_mode"])
        )
        for key in _UMENG_SECRET_KEYS:
            cfg["umeng"][key] = MASK if str(umeng_stored.get(key) or "") else ""
        return cfg

    # ------------------------------------------------------------------ 写

    def update_config(self, payload: dict) -> dict:
        """更新配置：密钥字段空值/掩码表示保留原值；其余字段覆盖。返回掩码后的最新配置。"""
        payload = payload or {}
        stored = dict(self._row().configs or {})

        if "enabled" in payload:
            stored["enabled"] = _normalize_bool(payload["enabled"])
        if "fallback_enabled" in payload:
            stored["fallback_enabled"] = _normalize_bool(payload["fallback_enabled"])
        if "primary_provider" in payload:
            provider = str(payload["primary_provider"] or "").strip().lower()
            if provider not in PROVIDERS:
                raise ValueError("primary_provider 只能是 getui / umeng")
            stored["primary_provider"] = provider

        if isinstance(payload.get("getui"), dict):
            incoming = payload["getui"]
            current = dict(stored.get("getui") or {})
            for key in _GETUI_STR_KEYS:
                if key in incoming:
                    current[key] = str(incoming.get(key) or "").strip()
            for key in _GETUI_SECRET_KEYS:
                if key in incoming:
                    raw = str(incoming.get(key) or "").strip()
                    if raw and raw != MASK:
                        current[key] = _encrypt_value(raw)
            stored["getui"] = current

        if isinstance(payload.get("umeng"), dict):
            incoming = payload["umeng"]
            current = dict(stored.get("umeng") or {})
            for key in _UMENG_STR_KEYS:
                if key in incoming:
                    current[key] = str(incoming.get(key) or "").strip()
            if "production_mode" in incoming:
                current["production_mode"] = _normalize_bool(incoming["production_mode"])
            for key in _UMENG_SECRET_KEYS:
                if key in incoming:
                    raw = str(incoming.get(key) or "").strip()
                    if raw and raw != MASK:
                        current[key] = _encrypt_value(raw)
            stored["umeng"] = current

        if stored.get("primary_provider") not in PROVIDERS:
            stored["primary_provider"] = DEFAULT_KEYS["primary_provider"]

        row = self._row()
        row.configs = stored
        self.session.commit()
        return self.get_config()

    # ------------------------------------------------------------------ 运行时（解密）

    def get_runtime_config(self) -> dict:
        """运行时可用的完整配置（密钥解密明文）；解密失败按未配置处理（fail-safe 跳过）。"""
        stored = dict(self._row().configs or {})
        cfg = {
            "enabled": _normalize_bool(stored.get("enabled", False)),
            "primary_provider": str(stored.get("primary_provider") or "getui"),
            "fallback_enabled": _normalize_bool(stored.get("fallback_enabled", True)),
            "getui": {},
            "umeng": {},
        }
        getui_stored = dict(stored.get("getui") or {})
        for key in _GETUI_STR_KEYS:
            cfg["getui"][key] = str(getui_stored.get(key) or "")
        for key in _GETUI_SECRET_KEYS:
            cfg["getui"][key] = self._safe_decrypt(getui_stored.get(key))
        umeng_stored = dict(stored.get("umeng") or {})
        for key in _UMENG_STR_KEYS:
            cfg["umeng"][key] = str(umeng_stored.get(key) or "")
        cfg["umeng"]["production_mode"] = _normalize_bool(umeng_stored.get("production_mode", True))
        for key in _UMENG_SECRET_KEYS:
            cfg["umeng"][key] = self._safe_decrypt(umeng_stored.get(key))
        return cfg

    @staticmethod
    def _safe_decrypt(value) -> str:
        raw = str(value or "")
        if not raw:
            return ""
        try:
            return _decrypt_value(raw)
        except Exception:
            return ""
