"""会话工作区授权模型。

文件操作默认限制在静态安全根（`OS_AUTOMATION_SAFE_ROOT`，缺省用户主目录）内。
当用户需要在其他目录（如 D 盘项目）让 Agent 工作时，经「授权确认」把该目录登记为
当前会话的工作区授权根；worker 侧按 `安全根 ∪ 会话授权根` 校验，授权范围内享受与
安全根一致的治理能力（写前快照、回收站、删除守卫、changes/recovery_hint）。

治理要点：
- 授权必须由用户显式批准（`os_workspace_scope` 工具属高风险且每次调用必确认）；
- 授权按会话（conversation_id）隔离，带过期时间，平台可撤销；
- worker 侧只接受「绝对路径、真实存在、是目录」的条目，条目不存在时自动失效。

设计见 docs/superpowers/specs/2026-10-04-session-workspace-scope-design.md。
"""
from datetime import UTC, datetime

from sqlalchemy import Column, DateTime, Index, String, text
from sqlalchemy.dialects.postgresql import UUID

from pkg.sqlalchemy import Base


def _utcnow_naive() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


class SessionWorkspaceScope(Base):
    """会话工作区授权记录（账号 + 会话 + 目录 唯一）。"""

    __tablename__ = "session_workspace_scope"

    id = Column(UUID, primary_key=True, server_default=text("uuid_generate_v4()"))
    account_id = Column(UUID, nullable=False)
    # 平台会话 ID（conversation_id）：授权只在该会话内生效
    session_id = Column(String(255), nullable=False)
    # 授权目录（宿主机绝对路径，如 D:\proj-x；存在性由 worker 侧过滤兜底）
    scope_root = Column(String(1024), nullable=False)
    # granted / revoked
    status = Column(String(16), nullable=False, server_default=text("'granted'::character varying"))
    # 授权来源说明（工具名 / 确认 ID，用于审计）
    granted_via = Column(String(255), nullable=False, server_default=text("''::character varying"))
    expires_at = Column(DateTime, nullable=False)
    created_at = Column(DateTime, nullable=False, server_default=text("CURRENT_TIMESTAMP(0)"))
    updated_at = Column(
        DateTime,
        nullable=False,
        server_default=text("CURRENT_TIMESTAMP(0)"),
        server_onupdate=text("CURRENT_TIMESTAMP(0)"),
        default=_utcnow_naive,
    )

    __table_args__ = (
        Index("session_workspace_scope_account_idx", "account_id"),
        Index("session_workspace_scope_session_idx", "session_id"),
        Index(
            "session_workspace_scope_unique_idx",
            "account_id",
            "session_id",
            "scope_root",
            unique=True,
        ),
    )
