"""encrypt external data source credentials and drop enterprise_knowledge

Revision ID: m7b8c9d0e1f2
Revises: l6a7b8c9d0e1
Create Date: 2026-09-12 00:00:00.000000

1. 把 external_data_source.config 中约定敏感 key 的明文值加密回填（幂等：gAAAAA 前缀跳过）。
2. 清理已下线的 enterprise_knowledge 类型数据源及其同步产物。

依赖 MODEL_KEY_ENCRYPTION_KEY；未配置则中止（与 d5e6f7a8b9c2 同款）。
downgrade 不可逆（加密与删除均无法还原），需走备份恢复。
"""
import json
import os
from typing import Any

from alembic import op
from cryptography.fernet import Fernet
from sqlalchemy import text

revision = "m7b8c9d0e1f2"
down_revision = "l6a7b8c9d0e1"
branch_labels = None
depends_on = None

_ENCRYPTED_PREFIX = "gAAAAA"
_SENSITIVE_KEYS = (
    "app_secret",
    "integration_token",
    "personal_access_token",
    "api_key",
    "token",
    "client_secret",
)


def _load_fernet() -> Fernet:
    raw_key = os.getenv("MODEL_KEY_ENCRYPTION_KEY", "").strip()
    if not raw_key:
        raise RuntimeError(
            "MODEL_KEY_ENCRYPTION_KEY 未配置，无法执行外部数据源凭证加密迁移；"
            "请配置该变量后重试。"
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


def _verify_fernet_roundtrip(fernet: Fernet) -> None:
    sample = "migration-sanity-check"
    encrypted = fernet.encrypt(sample.encode("utf-8")).decode("utf-8")
    if fernet.decrypt(encrypted.encode("utf-8")).decode("utf-8") != sample:
        raise RuntimeError("Fernet 加解密自检失败，请检查 MODEL_KEY_ENCRYPTION_KEY")


def _encrypt_config(fernet: Fernet, config: Any) -> tuple[dict, int]:
    """加密敏感 key，返回 (新 config, 加密计数)。"""
    if not isinstance(config, dict):
        return {}, 0
    count = 0
    new_config = dict(config)
    for key in _SENSITIVE_KEYS:
        value = new_config.get(key)
        if isinstance(value, str) and value and not _is_encrypted(value):
            new_config[key] = fernet.encrypt(value.encode("utf-8")).decode("utf-8")
            count += 1
    return new_config, count


def upgrade():
    fernet = _load_fernet()
    _verify_fernet_roundtrip(fernet)
    conn = op.get_bind()

    # 1. 加密历史 config
    rows = conn.execute(
        text("SELECT id, config FROM external_data_source")
    ).fetchall()
    encrypted_rows = 0
    for row in rows:
        new_config, count = _encrypt_config(fernet, row.config)
        if count == 0:
            continue
        conn.execute(
            text(
                "UPDATE external_data_source SET config = CAST(:cfg AS JSONB) WHERE id = :id"
            ),
            {"cfg": json.dumps(new_config, ensure_ascii=False), "id": row.id},
        )
        encrypted_rows += 1

    # 2. 清理 enterprise_knowledge 数据源及其同步产物
    conn.execute(
        text(
            "DELETE FROM knowledge_segment WHERE knowledge_document_id IN ("
            "  SELECT id FROM knowledge_document WHERE source_type = 'enterprise_knowledge'"
            ")"
        )
    )
    conn.execute(
        text("DELETE FROM knowledge_document WHERE source_type = 'enterprise_knowledge'")
    )
    removed = conn.execute(
        text("DELETE FROM external_data_source WHERE source_type = 'enterprise_knowledge'")
    ).rowcount

    print(
        f"[migration] 外部数据源凭证加密完成：{encrypted_rows} 行；"
        f"清理 enterprise_knowledge 数据源：{removed} 行"
    )


def downgrade():
    raise NotImplementedError(
        "该迁移不可逆（凭证加密与 enterprise_knowledge 删除均无法还原），请走备份恢复。"
    )
