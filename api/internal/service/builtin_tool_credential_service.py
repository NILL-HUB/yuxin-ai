"""内置工具凭证服务：把第三方工具密钥从"散读 env"收编为 admin 可配。

设计（对齐 sandbox/storage 的既有范式）：
- **写入**：凭证以加密 JSONB 落在 `builtin_tool_provider.credentials`（键=env 名，如 `TAVILY_API_KEY`），
  复用 `tool_credential_encryptor`（Fernet），**不落明文**。
- **读取**：`ToolCredentialResolver.get_tool_credential()` 升级为「DB（解密）优先 → env 兜底」，
  签名不变、缺失语义不变 → 业务代码零改动、DB 为空时行为与升级前逐字节一致。
- **管理**：`list_providers` / `update_provider_credentials` / `probe_provider`（凭证齐备性检查）。

「某 provider 需要哪些键」由代码（`PROVIDER_CREDENTIAL_KEYS`）声明——这是开发者定义
（工具实现读哪个 env），不是管理员配置，故不入库，避免冗余与漂移。
"""
from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from typing import Any

from injector import inject

from internal.exception import NotFoundException, ValidateErrorException
from internal.model.builtin_tool import BuiltinToolProvider
from internal.service.tool_credential_encryptor import (
    encrypt_env,
    is_encrypted,
    mask_env,
)
from pkg.sqlalchemy import SQLAlchemy

from .base_service import BaseService


# 各内置工具 provider 需要的凭证键（env 名）——**以代码为准**（等于工具实现读取的 env 名，
# 实测来源：`grep get_tool_credential api/internal/core/tools/builtin_tools`）。
PROVIDER_CREDENTIAL_KEYS: dict[str, list[str]] = {
    "web_tools": ["TAVILY_API_KEY", "EXA_API_KEY", "SERPAPI_API_KEY", "BRAVE_SEARCH_API_KEY"],
    "tavily": ["TAVILY_API_KEY"],
    "serpapi": ["SERPAPI_API_KEY"],
    "google": ["SERPER_API_KEY"],
    "x_search": ["XAI_API_KEY"],
    "newsapi": ["NEWSAPI_API_KEY"],
    "gaode": ["GAODE_API_KEY"],
    "openweathermap": ["OPENWEATHERMAP_API_KEY"],
    "wolframalpha": ["WOLFRAM_ALPHA_APPID"],
    "github": ["GITHUB_ACCESS_TOKEN"],
    "baidu": ["BAIDU_TRANSLATE_APP_ID", "BAIDU_TRANSLATE_SECRET_KEY"],
    "stability": ["STABILITY_API_KEY"],
    "atlascloud_image": ["ATLASCLOUD_API_KEY"],
    "atlascloud_video": ["ATLASCLOUD_API_KEY"],
    "browser_automation": ["BROWSER_AUTOMATION_URL", "BROWSER_AUTOMATION_TOKEN"],
    "computer_control": ["COMPUTER_CONTROL_URL", "COMPUTER_CONTROL_TOKEN"],
    "host_os": ["OS_AUTOMATION_URL", "OS_AUTOMATION_TOKEN"],
}


@inject
@dataclass
class BuiltinToolCredentialService(BaseService):
    """内置工具凭证的读写与治理。"""

    db: SQLAlchemy

    # ------------------------------------------------------------------
    # 读取（供 ToolCredentialResolver 调用，DB 解密优先）
    # ------------------------------------------------------------------
    def get_credential(self, env_name: str) -> str:
        """返回该 env 名在 DB 中配置的**明文**凭证；未配置或解密失败返回空串。"""
        name = str(env_name or "").strip()
        if not name:
            return ""
        row = self._find_provider_with_key(name)
        if row is None:
            return ""
        token = (row.credentials or {}).get(name)
        if not isinstance(token, str) or not token:
            return ""
        try:
            from internal.service.tool_credential_encryptor import _decrypt_value

            return _decrypt_value(token) or ""
        except Exception:
            logging.exception("内置工具凭证解密失败 provider=%s key=%s", row.name, name)
            return ""

    def _find_provider_with_key(self, env_name: str) -> BuiltinToolProvider | None:
        """在 builtin_tool_provider.credentials（JSONB，键明文）中查找含该键的 provider。"""
        try:
            rows = self.db.session.query(BuiltinToolProvider).all()
        except Exception:
            return None
        for row in rows:
            creds = row.credentials
            if isinstance(creds, dict) and creds.get(env_name):
                return row
        return None

    # ------------------------------------------------------------------
    # 管理
    # ------------------------------------------------------------------
    def list_providers(self) -> list[dict[str, Any]]:
        """列出"有凭证需求"的 provider 及其各键的配置状态（掩码，不回明文）。"""
        rows = {row.name: row for row in self.db.session.query(BuiltinToolProvider).all()}
        result: list[dict[str, Any]] = []
        for provider_name, keys in sorted(PROVIDER_CREDENTIAL_KEYS.items()):
            row = rows.get(provider_name)
            stored = dict(row.credentials or {}) if row is not None and isinstance(row.credentials, dict) else {}
            masked: dict[str, str] = {}
            if stored:
                try:
                    masked = mask_env(stored)
                except Exception:
                    logging.exception("内置工具凭证掩码失败 provider=%s", provider_name)
                    masked = {k: "" for k in stored}
            items = []
            for key in keys:
                db_configured = bool(stored.get(key))
                env_configured = bool(os.getenv(key, "").strip())
                items.append({
                    "key": key,
                    "configured": db_configured or env_configured,
                    "source": "db" if db_configured else ("env" if env_configured else ""),
                    "masked": masked.get(key, ""),
                })
            result.append({
                "provider": provider_name,
                "label": (row.label if row is not None and row.label else provider_name),
                "keys": items,
            })
        return result

    def update_provider_credentials(self, provider_name: str, values: dict[str, Any] | None) -> dict[str, Any]:
        """设置/更新某 provider 的凭证（加密入库）；空字符串表示清除该键。"""
        name = str(provider_name or "").strip()
        allowed = PROVIDER_CREDENTIAL_KEYS.get(name)
        if allowed is None:
            raise NotFoundException(f"该 provider 无可用凭证键: {name}")
        row = self.db.session.query(BuiltinToolProvider).filter_by(name=name).one_or_none()
        if row is None:
            raise NotFoundException(f"内置工具 provider 不存在: {name}")

        current = dict(row.credentials or {}) if isinstance(row.credentials, dict) else {}
        for key, value in (values or {}).items():
            key = str(key or "").strip()
            if key not in allowed:
                # 白名单过滤：未声明的键忽略（不落库）
                raise ValidateErrorException(f"不支持的凭证键: {key}")
            text = str(value if value is not None else "").strip()
            if text:
                current[key] = text if is_encrypted(text) else encrypt_env({key: text})[key]
            else:
                current.pop(key, None)
        row.credentials = current
        self.db.session.commit()
        return {"provider": name, "credentials": mask_env(current) if current else {}}

    def probe_provider(self, provider_name: str) -> dict[str, Any]:
        """凭证齐备性检查：逐键判断 DB/env 是否有值，返回缺失清单。

        说明：这是**凭证齐备性**检查（不发起外网调用）；真正的端到端连通性
        由管理员在对话中实际调用工具验证。
        """
        name = str(provider_name or "").strip()
        keys = PROVIDER_CREDENTIAL_KEYS.get(name)
        if keys is None:
            raise NotFoundException(f"该 provider 无可用凭证键: {name}")
        missing = [key for key in keys if not self._is_configured(key)]
        # web_tools 允许"全部缺失"（免费 DuckDuckGo 兜底），故不阻塞
        optional_all_missing = name == "web_tools" and len(missing) == len(keys)
        ok = not missing or optional_all_missing
        return {
            "ok": ok,
            "provider": name,
            "missing": missing,
            "note": "web_tools 无任何 key 时回退免费 DuckDuckGo" if optional_all_missing else "",
        }

    def _is_configured(self, env_name: str) -> bool:
        row = self._find_provider_with_key(env_name)
        if row is not None and isinstance(row.credentials, dict) and row.credentials.get(env_name):
            return True
        return bool(os.getenv(env_name, "").strip())
