"""会话工作区授权请求工具。

Agent 的本机文件操作默认限制在静态安全根内。当任务需要操作安全根之外的目录
（如 D 盘项目）时，其他工具会返回 `needs_scope_grant`，Agent 用本工具发起授权：
它属于高风险工具且**每次调用都需要用户确认**（授权是用户的显式行为），
用户批准后该目录写入当前会话的工作区授权，本会话内获得与安全根一致的治理能力
（写前快照、回收站、删除守卫、changes/recovery_hint）。

设计：docs/superpowers/specs/2026-10-04-session-workspace-scope-design.md
"""

from __future__ import annotations

import json
import logging
from typing import Any

from langchain_core.tools import BaseTool
from pydantic import BaseModel, Field


logger = logging.getLogger(__name__)


class OsWorkspaceScopeInput(BaseModel):
    """会话工作区授权请求输入。"""

    path: str = Field(
        ...,
        description="要申请授权的目录（宿主机绝对路径，如 D:\\proj-x 或 /data/proj）",
    )
    reason: str = Field(
        "",
        description="申请原因，会展示给用户（如：需要在该目录构建并运行项目）",
    )


def _normalize_text(value: Any) -> str:
    return str(value or "").strip()


class OsWorkspaceScopeTool(BaseTool):
    """申请会话工作区授权（用户确认后生效）。"""

    name: str = "os_workspace_scope"
    description: str = (
        "申请把某个目录加入**当前会话**的工作区授权（用户会收到授权确认弹窗）："
        "批准后本会话内 `os_file_task` / `os_recycle_bin` / `os_snapshot` / `os_terminal` "
        "可在该目录正常工作，并享受与安全根一致的治理（写前快照、回收站、删除守卫）。"
        "触发时机：上述工具返回 needs_scope_grant（目标目录在安全根与会话授权根之外）时，"
        "用本工具申请该目录，用户批准后**重试原操作**；不要改用电脑控制或尝试绕过。"
        "每次调用都需要用户确认（授权是用户的显式行为），不要用本工具申请安全根内的目录。"
    )
    args_schema: type[BaseModel] = OsWorkspaceScopeInput
    requester: str = ""
    session_id: str = ""

    def _run(self, **kwargs: Any) -> str:
        path = _normalize_text(kwargs.get("path"))
        reason = _normalize_text(kwargs.get("reason"))
        if not path:
            return json.dumps({"ok": False, "error": "path 不能为空"}, ensure_ascii=False)
        try:
            from app.http.module import injector
            from internal.service.session_scope_service import SessionScopeService

            record = injector.get(SessionScopeService).grant(
                account_id=_normalize_text(self.requester),
                session_id=_normalize_text(self.session_id),
                scope_root=path,
                granted_via="os_workspace_scope",
            )
        except Exception as exc:
            logger.warning("会话工作区授权失败: %s", exc, exc_info=True)
            return json.dumps(
                {"ok": False, "error": f"授权失败: {exc}"},
                ensure_ascii=False,
                default=str,
            )
        return json.dumps(
            {
                "ok": True,
                "scope_root": path,
                "reason": reason,
                "expires_at": str(getattr(record, "expires_at", "")),
                "message": (
                    f"用户已批准：目录 {path} 已加入本会话工作区授权。"
                    "请重试之前的操作（若该目录在本机不存在，授权会被自动忽略）。"
                ),
            },
            ensure_ascii=False,
            default=str,
        )

    async def _arun(self, **kwargs: Any) -> str:
        return self._run(**kwargs)


def os_workspace_scope(**kwargs: Any) -> BaseTool:
    """工厂函数：返回会话工作区授权请求工具。"""
    return OsWorkspaceScopeTool(
        requester=_normalize_text(kwargs.get("requester")),
        session_id=_normalize_text(kwargs.get("session_id")),
    )
