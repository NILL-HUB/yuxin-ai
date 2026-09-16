"""管理端 Agent 执行身份与自动化级别（设计 §5）。

为什么不用 ``Account`` 伪装：管理员与用户端账号已彻底解耦（
``admin_user.account_id`` 恒为 NULL），用 Account 伪装会让下游所有
"按 account 隔离"的逻辑误判主体。

为什么不沿用 ``_SystemBorneAccount``：现有 4 个管理端 AI 辅助端点用
``_SystemBorneAccount(id=None)`` 丢弃了管理员身份，无法做板块授权，
也回答不了"谁让 AI 改了什么"。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Mapping
from uuid import UUID


class AutomationLevel(str, Enum):
    """板块自动化级别（与权限正交的第二维度，设计 §5.1）。"""

    SUPERVISED = "supervised"   # 需人工授权：产出变更草稿，点「应用」才落库
    AUTONOMOUS = "autonomous"   # 全自动：靠审计 + 回收站 + 快照兜底
    BLOCKED = "blocked"         # 禁用：即使有权限也不执行（应急熔断）


@dataclass(frozen=True)
class AdminAgentPrincipal:
    """管理端 Agent 的显式执行身份。

    全链路显式传参，不做隐式上下文读取（易漏、难测）。
    """

    admin_user_id: UUID                        # 发起管理员（人类责任人）
    agent_id: UUID                             # 执行该操作的 Agent
    agent_name: str                            # 审计展示用
    effective_permissions: frozenset[str]      # 已算好的三重交集（§4.1）
    automation_policy: Mapping[str, AutomationLevel] = field(default_factory=dict)

    def has_permission(self, permission_code: str) -> bool:
        return permission_code in self.effective_permissions

    def automation_level_for(self, board: str) -> AutomationLevel:
        """取某板块的自动化级别。

        fail closed：未配置的板块一律 ``SUPERVISED``。
        避免"忘记配置 = 全自动"。
        """
        level = self.automation_policy.get(board)
        if level is None:
            return AutomationLevel.SUPERVISED
        if isinstance(level, AutomationLevel):
            return level
        try:
            return AutomationLevel(level)
        except ValueError:
            # 非法取值同样 fail closed 到 supervised
            return AutomationLevel.SUPERVISED
