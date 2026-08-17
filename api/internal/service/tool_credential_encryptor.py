"""工具凭证加密服务（Fernet AES-256）。

复用 ModelKeyConfig 的 Fernet 加密模式，为 api_tool.headers / mcp.headers /
mcp.env / workflow 节点凭证 等敏感字段提供统一的加密/解密/脱敏能力。

设计要点：
- 复用 MODEL_KEY_ENCRYPTION_KEY 环境变量（避免引入新密钥）
- 若未配置则生成临时内存密钥并 WARNING（与 admin_model_pool_service 保持一致）
- 加密粒度：对 JSONB 字段中的 value 子字段加密，保留 key 字段可读
  例如 [{"key":"Authorization","value":"Bearer xxx"}] 加密后
       [{"key":"Authorization","value_encrypted":"gAAAAA..."}]
- 列表/详情 API 调用 mask_credentials 脱敏显示
- 运行时调用 decrypt_credentials 还原真实值
"""
from __future__ import annotations

import logging
import os
from typing import Any

from cryptography.fernet import Fernet, InvalidToken

logger = logging.getLogger(__name__)


def _is_placeholder_key(raw_key: str) -> bool:
    """判断 Fernet 密钥是否未配置或为占位符。"""
    if not raw_key:
        return True
    lowered = raw_key.lower()
    return (
        lowered.startswith("your-")
        or "-here" in lowered
        or raw_key.startswith("<changeme")
        or raw_key.startswith("placeholder-")
    )


def load_fernet_from_env(env_name: str, component_name: str) -> Fernet:
    """加载 Fernet 密钥（供各凭证加密模块共享）。

    规则：
    - 密钥未配置或为占位符时：
      - 生产环境（APP_ENV=production）直接抛错，阻止服务以弱/临时密钥启动（M-2）；
      - 开发/测试环境生成临时内存密钥并 WARNING（保留重启后需重新加密的行为）。
    - 非法密钥格式一律抛 ValueError。
    """
    raw_key = os.getenv(env_name, "").strip()
    if _is_placeholder_key(raw_key):
        is_production = str(os.getenv("APP_ENV") or "").strip().lower() == "production"
        if is_production:
            raise RuntimeError(
                f"{env_name} 未配置（或为占位符），生产环境禁止使用临时/占位密钥加密凭证。"
                "请配置有效 Fernet 密钥（生成方法: python -c "
                '\"from cryptography.fernet import Fernet; '
                'print(Fernet.generate_key().decode())\"）后重启服务。'
            )
        raw_key = Fernet.generate_key().decode("utf-8")
        logger.warning(
            "%s: %s 未配置，已生成临时内存密钥，"
            "重启后将无法解密历史凭证，请尽快配置该环境变量",
            component_name,
            env_name,
        )
    try:
        return Fernet(raw_key.encode("utf-8"))
    except (ValueError, TypeError) as exc:
        raise ValueError(
            f"{env_name} 不是合法的 Fernet 密钥，请使用 Fernet.generate_key() 生成"
        ) from exc


def _load_fernet() -> Fernet:
    """加载 Fernet 密钥，优先复用 MODEL_KEY_ENCRYPTION_KEY，避免引入新密钥。"""
    return load_fernet_from_env("MODEL_KEY_ENCRYPTION_KEY", "工具凭证")


_FERNET = _load_fernet()


def _encrypt_value(value: str) -> str:
    """加密单个字符串值，返回 Fernet token 字符串。"""
    if not value:
        return ""
    return _FERNET.encrypt(value.encode("utf-8")).decode("utf-8")


def _decrypt_value(token: str) -> str:
    """解密 Fernet token 字符串，失败抛 ValueError（让调用方感知密钥/数据问题）。"""
    if not token:
        return ""
    try:
        return _FERNET.decrypt(token.encode("utf-8")).decode("utf-8")
    except (InvalidToken, ValueError) as exc:
        raise ValueError("工具凭证解密失败，可能密钥已变更或数据未迁移") from exc


def _mask_value(value: str) -> str:
    """脱敏显示：保留首尾 4 字符，中间用 * 替换。"""
    if not value:
        return ""
    if len(value) <= 8:
        return "*" * len(value)
    return value[:4] + "*" * (len(value) - 8) + value[-4:]


# 加密后字段在 JSONB 中的标记前缀，用于区分已加密和未加密的值
# 采用 Fernet token 的特征前缀 "gAAAAA" 作为隐式标记（Fernet token 始终以此开头）
_ENCRYPTED_PREFIX = "gAAAAA"


def encrypt_headers(headers: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
    """加密 headers 列表中的 value 字段。

    输入格式：[{"key": "Authorization", "value": "Bearer xxx"}]
    输出格式：[{"key": "Authorization", "value": "<encrypted>"}]

    幂等性：若 value 已经是加密 token（以 _ENCRYPTED_PREFIX 开头），跳过并记 warning。
    """
    if not headers or not isinstance(headers, list):
        return []
    result = []
    for item in headers:
        if not isinstance(item, dict):
            continue
        new_item = dict(item)
        value = new_item.get("value")
        if isinstance(value, str) and value:
            if value.startswith(_ENCRYPTED_PREFIX):
                logger.warning("encrypt_headers 收到已加密的 value，已跳过；请确认数据来源是否正确")
            else:
                new_item["value"] = _encrypt_value(value)
        result.append(new_item)
    return result


def decrypt_headers(headers: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
    """解密 headers 列表中的 value 字段（返回真实值，用于运行时调用）。

    所有非空 value 都尝试解密；若 value 不是合法密文（InvalidToken），抛 ValueError。
    """
    if not headers or not isinstance(headers, list):
        return []
    result = []
    for item in headers:
        if not isinstance(item, dict):
            continue
        new_item = dict(item)
        value = new_item.get("value")
        if isinstance(value, str) and value:
            new_item["value"] = _decrypt_value(value)
        result.append(new_item)
    return result


def mask_headers(headers: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
    """脱敏 headers 列表（用于 admin 列表/详情 API 展示）。

    所有非空 value 都先解密再脱敏；若解密失败抛 ValueError。
    """
    if not headers or not isinstance(headers, list):
        return []
    result = []
    for item in headers:
        if not isinstance(item, dict):
            continue
        new_item = dict(item)
        value = new_item.get("value")
        if isinstance(value, str) and value:
            real_value = _decrypt_value(value)
            new_item["value"] = _mask_value(real_value)
        result.append(new_item)
    return result


def encrypt_env(env: dict[str, Any] | None) -> dict[str, Any]:
    """加密 env 字典中的所有 value（MCP stdio 模式环境变量）。

    输入格式：{"API_KEY": "sk-xxx", "DEBUG": "true"}
    输出格式：{"API_KEY": "<encrypted>", "DEBUG": "<encrypted>"}

    幂等性：若 value 已是加密 token，跳过并记 warning。
    """
    if not env or not isinstance(env, dict):
        return {}
    result = {}
    for key, value in env.items():
        if isinstance(value, str) and value:
            if value.startswith(_ENCRYPTED_PREFIX):
                logger.warning("encrypt_env 收到已加密的 value，已跳过；请确认数据来源是否正确")
                result[key] = value
            else:
                result[key] = _encrypt_value(value)
        else:
            result[key] = value
    return result


def decrypt_env(env: dict[str, Any] | None) -> dict[str, Any]:
    """解密 env 字典（返回真实值，用于运行时子进程 env 注入）。

    所有非空 value 都尝试解密；若 value 不是合法密文（InvalidToken），抛 ValueError。
    """
    if not env or not isinstance(env, dict):
        return {}
    result = {}
    for key, value in env.items():
        if isinstance(value, str) and value:
            result[key] = _decrypt_value(value)
        else:
            result[key] = value
    return result


def mask_env(env: dict[str, Any] | None) -> dict[str, Any]:
    """脱敏 env 字典（用于 admin 展示）。

    所有非空 value 都先解密再脱敏；若解密失败抛 ValueError。
    """
    if not env or not isinstance(env, dict):
        return {}
    result = {}
    for key, value in env.items():
        if isinstance(value, str) and value:
            real_value = _decrypt_value(value)
            result[key] = _mask_value(real_value)
        else:
            result[key] = value
    return result


def is_encrypted(value: str | None) -> bool:
    """判断 value 是否已加密。"""
    return bool(value) and isinstance(value, str) and value.startswith(_ENCRYPTED_PREFIX)


def ensure_encrypted_headers(headers: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
    """幂等加密：确保 headers 中的 value 已加密（用于写入 DB 前）。"""
    return encrypt_headers(headers)


def ensure_encrypted_env(env: dict[str, Any] | None) -> dict[str, Any]:
    """幂等加密：确保 env 中的 value 已加密（用于写入 DB 前）。"""
    return encrypt_env(env)
