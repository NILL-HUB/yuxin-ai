"""外部数据源凭证处理：对 config 中的敏感 key 做 Fernet 加密/解密/脱敏。

复用 tool_credential_encryptor 的 Fernet 能力（MODEL_KEY_ENCRYPTION_KEY），
仅加密约定敏感 key；非敏感配置（folder_path/owner/repo/database_id 等）
保持明文，保证可读与可查询。
"""
from __future__ import annotations

import logging
from typing import Any

from internal.service.tool_credential_encryptor import (
    _decrypt_value,
    _encrypt_value,
    _mask_value,
    is_encrypted,
)

logger = logging.getLogger(__name__)

# 需要加密存储的 config key（覆盖 lark/notion/github 的全部凭证字段）
SENSITIVE_KEYS = frozenset(
    {
        "app_secret",
        "integration_token",
        "personal_access_token",
        "api_key",
        "token",
        "client_secret",
    }
)


def encrypt_config(config: dict[str, Any] | None) -> dict[str, Any]:
    """加密敏感 key 的值；已加密（gAAAAA 前缀）跳过，保证幂等。"""
    if not config:
        return {}
    result: dict[str, Any] = {}
    for key, value in config.items():
        if key in SENSITIVE_KEYS and isinstance(value, str) and value and not is_encrypted(value):
            result[key] = _encrypt_value(value)
        else:
            result[key] = value
    return result


def decrypt_config(config: dict[str, Any] | None) -> dict[str, Any]:
    """解密敏感 key，供连接器调用外部 API；单 key 解密失败降级为空串并告警。

    仅对「已加密」的值解密；未加密（历史明文或迁移未覆盖）的值原样返回，
    避免把仍在使用的明文凭证误清空。
    """
    if not config:
        return {}
    result: dict[str, Any] = {}
    for key, value in config.items():
        if key in SENSITIVE_KEYS and isinstance(value, str) and value and is_encrypted(value):
            try:
                result[key] = _decrypt_value(value)
            except ValueError:
                logger.warning("外部数据源凭证解密失败 key=%s，已降级为空串", key)
                result[key] = ""
        else:
            result[key] = value
    return result


def mask_config(config: dict[str, Any] | None) -> dict[str, Any]:
    """脱敏输出：敏感 key 一律返回掩码（不区分明文/密文），用于 API 返回。"""
    if not config:
        return {}
    result: dict[str, Any] = {}
    for key, value in config.items():
        if key in SENSITIVE_KEYS and isinstance(value, str) and value:
            real = value
            if is_encrypted(value):
                try:
                    real = _decrypt_value(value)
                except ValueError:
                    real = ""
            result[key] = _mask_value(real)
        else:
            result[key] = value
    return result
