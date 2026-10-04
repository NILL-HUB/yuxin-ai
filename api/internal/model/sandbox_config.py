"""沙箱配置模型。

Admin 端运行时切换沙箱后端的基础：``sandbox_config`` 表记录各**能力域**
（code_interpreter / skill_exec / workflow_code）下各后端（baidu_cfc /
e2b_cloud / http_sandbox / disabled）的配置项与激活状态。

- 同一能力域内同一时间只有一个后端激活（`is_active`）
- `configs` 只存白名单键（模板名 / 超时 / endpoint 等），**不含密钥**
- `credentials` 存后端凭证（**加密 JSONB**，键=env 名），可由 Admin 配置；
  运行时经 `SandboxConfigService.resolve_credentials` 解密（DB 优先 → env 兜底），接口只回掩码
- 运行时唯一读取入口：`SandboxConfigService.resolve_runtime(capability)`
"""
from datetime import UTC, datetime

from sqlalchemy import (
    UUID,
    Boolean,
    Column,
    DateTime,
    Index,
    JSON,
    PrimaryKeyConstraint,
    String,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB

from pkg.sqlalchemy import Base


def _utcnow_naive() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


class SandboxConfig(Base):
    __tablename__ = "sandbox_config"
    __table_args__ = (
        PrimaryKeyConstraint("id", name="pk_sandbox_config_id"),
        UniqueConstraint("capability", "backend", name="uq_sandbox_config_capability_backend"),
        Index("ix_sandbox_config_capability_is_active", "capability", "is_active"),
    )

    id = Column(UUID, nullable=False, server_default=text("uuid_generate_v4()"))
    # 能力域：code_interpreter / skill_exec / workflow_code
    capability = Column(String(32), nullable=False, server_default=text("''::character varying"))
    # 后端名：baidu_cfc / e2b_cloud / http_sandbox / disabled
    backend = Column(String(32), nullable=False, server_default=text("''::character varying"))
    # 展示名（Admin 界面用）
    label = Column(String(64), nullable=False, server_default=text("''::character varying"))
    # 后端配置项（JSON，白名单键；**不含密钥**）
    configs = Column(JSON, nullable=False, server_default=text("'{}'::json"))
    # 后端凭证（加密 JSONB，键=env 名，如 E2B_API_KEY；值经 tool_credential_encryptor 加密）
    # 运行时经 SandboxConfigService.resolve_credentials 解密（DB 优先 → env 兜底）；接口只回掩码
    credentials = Column(JSONB, nullable=False, server_default=text("'{}'::jsonb"))
    # 是否激活：同一能力域内仅一个后端可激活
    is_active = Column(Boolean, nullable=False, server_default=text("false"))
    created_at = Column(DateTime, nullable=False, server_default=text("CURRENT_TIMESTAMP(0)"))
    # 注意：`onupdate` 是 ORM 层写入（生成 SET updated_at）。
    # 不可用 `server_onupdate`——PostgreSQL 没有 MySQL 式 ON UPDATE 语义，
    # 无触发器时 DB 不会自动刷新该列（历史 bug：全表 updated_at 停在创建时间，
    # 而 `get_active_backend` 依赖 updated_at 排序定位最新激活行）。
    updated_at = Column(
        DateTime,
        nullable=False,
        server_default=text("CURRENT_TIMESTAMP(0)"),
        default=_utcnow_naive,
        onupdate=_utcnow_naive,
    )
