"""会话工作区授权服务（单一权威入口）。

管理「用户批准的会话级额外工作目录」：Agent 的本机文件操作默认限制在静态安全根
（缺省用户主目录）内；当任务需要操作其他目录（如 D 盘项目）时，Agent 调用
`os_workspace_scope` 发起授权（高风险工具、每次调用必确认），用户批准后把该目录
写入本服务，会话内该目录即获得与安全根一致的治理能力（写前快照、回收站、删除守卫）。

消费方：
- 工具层 `providers/host_os/worker_client.call_host_worker` 注入 `session_scopes`；
- worker 侧 `_allowed_scope_roots` 按「安全根 ∪ 会话授权根」校验（最终硬边界，
  条目不存在的自动失效）。

设计：docs/superpowers/specs/2026-10-04-session-workspace-scope-design.md
"""
from __future__ import annotations

import logging
import re
from datetime import UTC, datetime, timedelta

from injector import inject

from internal.exception import NotFoundException, ValidateErrorException
from internal.model import SessionWorkspaceScope
from pkg.sqlalchemy import SQLAlchemy
from .base_service import BaseService

logger = logging.getLogger(__name__)

# 会话授权默认有效期：12 小时（覆盖长会话；到期自动失效，需要时重新授权）
DEFAULT_TTL_SECONDS = 12 * 3600
# 单会话授权目录数量上限（防止无限扩张；超出时提示先撤销旧目录）
MAX_ACTIVE_SCOPES_PER_SESSION = 8

_WIN_ABS_PATH_RE = re.compile(r"^[A-Za-z]:[\\/]")


def _utcnow_naive() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def _is_absolute_path(path: str) -> bool:
    """绝对路径判定：服务端跑在容器内，不能依赖本机 os.path.isabs 判断 Windows 路径。"""
    return bool(_WIN_ABS_PATH_RE.match(path)) or path.startswith("/")


@inject
class SessionScopeService(BaseService):
    """会话工作区授权的授权/查询/撤销（账号 + 会话 + 目录 维度）。"""

    def __init__(self, db: SQLAlchemy = None):
        self.db = db

    def grant(
        self,
        *,
        account_id,
        session_id: str,
        scope_root: str,
        granted_via: str = "",
        ttl_seconds: int | None = None,
    ) -> SessionWorkspaceScope:
        """授权某目录在会话内可用；幂等——重复授权刷新有效期并恢复 granted。

        仅做格式校验（绝对路径）；目录存在性由 worker 侧过滤兜底
        （服务端在容器内无法可靠判断用户机器路径），不存在时不生效也不报错。
        """
        normalized_root = str(scope_root or "").strip()
        if not normalized_root:
            raise ValidateErrorException("scope_root 不能为空")
        if not _is_absolute_path(normalized_root):
            raise ValidateErrorException("scope_root 必须是绝对路径")
        session = str(session_id or "").strip()
        if not session:
            raise ValidateErrorException("session_id 不能为空")
        ttl = int(ttl_seconds or DEFAULT_TTL_SECONDS)
        expires_at = _utcnow_naive() + timedelta(seconds=max(ttl, 60))

        existing = (
            self.db.session.query(SessionWorkspaceScope)
            .filter(
                SessionWorkspaceScope.account_id == account_id,
                SessionWorkspaceScope.session_id == session,
                SessionWorkspaceScope.scope_root == normalized_root,
            )
            .one_or_none()
        )
        if existing is None:
            active_count = (
                self.db.session.query(SessionWorkspaceScope)
                .filter(
                    SessionWorkspaceScope.account_id == account_id,
                    SessionWorkspaceScope.session_id == session,
                    SessionWorkspaceScope.status == "granted",
                    SessionWorkspaceScope.expires_at > _utcnow_naive(),
                )
                .count()
            )
            if active_count >= MAX_ACTIVE_SCOPES_PER_SESSION:
                raise ValidateErrorException(
                    f"本会话已授权 {active_count} 个目录（上限 {MAX_ACTIVE_SCOPES_PER_SESSION}），"
                    "请先撤销不再需要的目录再申请新目录"
                )
            with self.db.auto_commit():
                record = self.create(
                    SessionWorkspaceScope,
                    account_id=account_id,
                    session_id=session,
                    scope_root=normalized_root,
                    status="granted",
                    granted_via=str(granted_via or "")[:255],
                    expires_at=expires_at,
                )
            logger.info(
                "会话工作区授权新增 account=%s session=%s root=%s",
                account_id, session, normalized_root,
            )
            return record

        with self.db.auto_commit():
            existing.status = "granted"
            existing.expires_at = expires_at
            existing.granted_via = str(granted_via or "")[:255]
            existing.updated_at = _utcnow_naive()
        logger.info(
            "会话工作区授权刷新 account=%s session=%s root=%s",
            account_id, session, normalized_root,
        )
        return existing

    def list_active_roots(self, *, account_id, session_id: str) -> list[str]:
        """该会话当前有效的授权目录（status=granted 且未过期）。查询失败按空列表处理。"""
        session = str(session_id or "").strip()
        if not session or account_id is None:
            return []
        try:
            rows = (
                self.db.session.query(SessionWorkspaceScope)
                .filter(
                    SessionWorkspaceScope.account_id == account_id,
                    SessionWorkspaceScope.session_id == session,
                    SessionWorkspaceScope.status == "granted",
                    SessionWorkspaceScope.expires_at > _utcnow_naive(),
                )
                .order_by(SessionWorkspaceScope.created_at)
                .all()
            )
        except Exception:
            logger.warning("查询会话工作区授权失败，按无授权处理", exc_info=True)
            return []
        return [str(row.scope_root) for row in rows]

    def list_scopes(self, *, account_id, session_id: str | None = None) -> list[SessionWorkspaceScope]:
        """列出授权记录（可按会话过滤），供排查与撤销入口使用。"""
        query = self.db.session.query(SessionWorkspaceScope).filter(
            SessionWorkspaceScope.account_id == account_id
        )
        if session_id:
            query = query.filter(SessionWorkspaceScope.session_id == str(session_id))
        return query.order_by(SessionWorkspaceScope.created_at.desc()).all()

    def revoke(self, *, scope_id, account_id) -> SessionWorkspaceScope:
        """撤销一条授权（幂等）。"""
        record = (
            self.db.session.query(SessionWorkspaceScope)
            .filter(
                SessionWorkspaceScope.id == scope_id,
                SessionWorkspaceScope.account_id == account_id,
            )
            .one_or_none()
        )
        if record is None:
            raise NotFoundException("会话工作区授权记录不存在")
        if record.status != "revoked":
            with self.db.auto_commit():
                record.status = "revoked"
                record.updated_at = _utcnow_naive()
        return record
