# api/internal/migration/versions/d5e6f7a8b9c2_encrypt_historical_tool_credentials.py
"""encrypt historical tool credentials

Revision ID: d5e6f7a8b9c2
Revises: d5e6f7a8b9c1
Create Date: 2026-07-27 18:00:00.000000

历史凭证加密迁移（不向后兼容）。

遍历以下表/字段，对未加密（不以 "gAAAAA" 开头）的敏感 value 做一次性 Fernet 加密：
- api_tool_provider.headers[*].value
- mcp_provider.headers[*].value
- mcp_provider.env.{key}
- app_config.mcp_bindings[*].headers[*].value / env.{key}
  （app_config_version 不迁移，历史版本保留原样，新发布的配置走加密路径）

幂等设计：已加密（以 "gAAAAA" 开头）的值会被跳过，迁移可重复执行。

依赖 MODEL_KEY_ENCRYPTION_KEY 环境变量提供 Fernet 密钥，未配置则报错中止迁移，
避免使用临时内存密钥加密后无法再次解密。

downgrade 不可逆：凭证加密是单向迁移，回滚会破坏数据可解密性。
"""
import json
import os
from typing import Any

import sqlalchemy as sa
from alembic import op
from cryptography.fernet import Fernet, InvalidToken


# revision identifiers, used by Alembic.
revision = "d5e6f7a8b9c2"
down_revision = "d5e6f7a8b9c1"
branch_labels = None
depends_on = None


_ENCRYPTED_PREFIX = "gAAAAA"


def _load_fernet() -> Fernet:
    """加载 Fernet 密钥；未配置则抛错中止迁移。"""
    raw_key = os.getenv("MODEL_KEY_ENCRYPTION_KEY", "").strip()
    if not raw_key:
        raise RuntimeError(
            "MODEL_KEY_ENCRYPTION_KEY 环境变量未配置，"
            "无法执行历史凭证加密迁移；请配置该变量后重试。"
        )
    try:
        return Fernet(raw_key.encode("utf-8"))
    except (ValueError, TypeError) as exc:
        raise RuntimeError(
            "MODEL_KEY_ENCRYPTION_KEY 不是合法的 Fernet 密钥，"
            "请使用 Fernet.generate_key() 生成"
        ) from exc


def _is_encrypted(value: Any) -> bool:
    return isinstance(value, str) and bool(value) and value.startswith(_ENCRYPTED_PREFIX)


def _encrypt_value(fernet: Fernet, value: Any) -> str:
    if value is None:
        return ""
    text = str(value)
    if not text:
        return ""
    if _is_encrypted(text):
        # 幂等：已加密则跳过
        return text
    return fernet.encrypt(text.encode("utf-8")).decode("utf-8")


def _encrypt_headers(fernet: Fernet, headers: Any) -> tuple[Any, int]:
    """加密 headers 列表，返回 (新列表, 加密计数)。"""
    if not isinstance(headers, list):
        return headers, 0
    encrypted_count = 0
    new_headers: list[dict[str, Any]] = []
    for item in headers:
        if not isinstance(item, dict):
            new_headers.append(item)
            continue
        new_item = dict(item)
        value = new_item.get("value")
        if isinstance(value, str) and value and not _is_encrypted(value):
            new_item["value"] = _encrypt_value(fernet, value)
            encrypted_count += 1
        new_headers.append(new_item)
    return new_headers, encrypted_count


def _encrypt_env(fernet: Fernet, env: Any) -> tuple[Any, int]:
    """加密 env 字典，返回 (新字典, 加密计数)。"""
    if not isinstance(env, dict):
        return env, 0
    encrypted_count = 0
    new_env: dict[str, Any] = {}
    for key, value in env.items():
        if isinstance(value, str) and value and not _is_encrypted(value):
            new_env[key] = _encrypt_value(fernet, value)
            encrypted_count += 1
        else:
            new_env[key] = value
    return new_env, encrypted_count


def _verify_fernet_roundtrip(fernet: Fernet) -> None:
    """在迁移前自检：加密一段文本再解密，确保密钥可用。"""
    sample = "migration-sanity-check"
    encrypted = fernet.encrypt(sample.encode("utf-8")).decode("utf-8")
    try:
        decrypted = fernet.decrypt(encrypted.encode("utf-8")).decode("utf-8")
    except InvalidToken as exc:
        raise RuntimeError("MODEL_KEY_ENCRYPTION_KEY 自检失败") from exc
    if decrypted != sample:
        raise RuntimeError("MODEL_KEY_ENCRYPTION_KEY 自检失败：加解密结果不一致")


def _migrate_api_tool_providers(conn, fernet: Fernet) -> int:
    """加密 api_tool_provider.headers 中的 value。"""
    rows = conn.execute(
        sa.text("SELECT id, headers FROM api_tool_provider")
    ).fetchall()
    total = 0
    for row in rows:
        row_id, headers = row[0], row[1]
        if not headers:
            continue
        new_headers, count = _encrypt_headers(fernet, headers)
        if count == 0:
            continue
        conn.execute(
            sa.text("UPDATE api_tool_provider SET headers = CAST(:headers AS JSONB) WHERE id = :id"),
            {"headers": json.dumps(new_headers, ensure_ascii=False), "id": row_id},
        )
        total += count
    return total


def _migrate_mcp_providers(conn, fernet: Fernet) -> int:
    """加密 mcp_provider.headers[*].value 和 mcp_provider.env.{key}。"""
    rows = conn.execute(
        sa.text("SELECT id, headers, env FROM mcp_provider")
    ).fetchall()
    total = 0
    for row in rows:
        row_id, headers, env = row[0], row[1], row[2]
        new_headers, headers_count = _encrypt_headers(fernet, headers)
        new_env, env_count = _encrypt_env(fernet, env)
        if headers_count == 0 and env_count == 0:
            continue
        conn.execute(
            sa.text(
                "UPDATE mcp_provider "
                "SET headers = CAST(:headers AS JSONB), env = CAST(:env AS JSONB) "
                "WHERE id = :id"
            ),
            {
                "headers": json.dumps(new_headers, ensure_ascii=False),
                "env": json.dumps(new_env, ensure_ascii=False),
                "id": row_id,
            },
        )
        total += headers_count + env_count
    return total


def _migrate_app_config_mcp_bindings(conn, fernet: Fernet) -> int:
    """加密 app_config.mcp_bindings JSONB 中的 headers/env。

    mcp_bindings 结构示例：
    [
      {
        "name": "...", "transport": "...",
        "headers": [{"key": "Authorization", "value": "Bearer xxx"}],
        "env": {"API_KEY": "sk-xxx"}
      },
      ...
    ]
    """
    rows = conn.execute(
        sa.text("SELECT id, mcp_bindings FROM app_config")
    ).fetchall()
    total = 0
    for row in rows:
        row_id, mcp_bindings = row[0], row[1]
        if not isinstance(mcp_bindings, list) or not mcp_bindings:
            continue
        new_bindings: list[dict[str, Any]] = []
        binding_changed = False
        for binding in mcp_bindings:
            if not isinstance(binding, dict):
                new_bindings.append(binding)
                continue
            new_binding = dict(binding)
            new_headers, headers_count = _encrypt_headers(fernet, binding.get("headers"))
            new_env, env_count = _encrypt_env(fernet, binding.get("env"))
            if headers_count > 0:
                new_binding["headers"] = new_headers
                binding_changed = True
            if env_count > 0:
                new_binding["env"] = new_env
                binding_changed = True
            total += headers_count + env_count
            new_bindings.append(new_binding)
        if not binding_changed:
            continue
        conn.execute(
            sa.text("UPDATE app_config SET mcp_bindings = CAST(:bindings AS JSONB) WHERE id = :id"),
            {"bindings": json.dumps(new_bindings, ensure_ascii=False), "id": row_id},
        )
    return total


def upgrade() -> None:
    fernet = _load_fernet()
    _verify_fernet_roundtrip(fernet)
    conn = op.get_bind()

    total = 0
    total += _migrate_api_tool_providers(conn, fernet)
    total += _migrate_mcp_providers(conn, fernet)
    total += _migrate_app_config_mcp_bindings(conn, fernet)

    print(f"[d5e6f7a8b9c2] 历史凭证加密迁移完成，共加密 {total} 个字段")


def downgrade() -> None:
    # 凭证加密为单向迁移：解密需要 Fernet 密钥，且回滚会破坏数据可解密性。
    raise NotImplementedError(
        "历史凭证加密迁移不可逆；如需回滚请通过备份恢复，"
        "并确保 MODEL_KEY_ENCRYPTION_KEY 与原迁移时一致。"
    )
