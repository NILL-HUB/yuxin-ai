"""智能审批运行时策略。

对齐 Hermes `approvals.smart_policy`：管理员在 `tool_governance_policy` 中把某个
工具标记为 `require_confirmation=false` 后，同一工具的高风险调用可自动放行，
不再每次弹确认卡片。危险工具永远不允许自动放行。
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Any

from injector import inject

from internal.model.tool_governance_entity import ToolGovernancePolicy
from pkg.sqlalchemy import SQLAlchemy

logger = logging.getLogger(__name__)


@inject
@dataclass
class SmartApprovalPolicyService:
    db: SQLAlchemy

    _DAEMON_DANGEROUS_MARKERS = (
        "--privileged",
        "--network host",
        "--net=host",
        "--pid host",
        "--pid=host",
        "--ipc host",
        "--ipc=host",
        "--cap-add all",
        "--cap-add=all",
        "--device /dev/",
    )

    @staticmethod
    def contains_dangerous_container_command(command: str) -> bool:
        """检测 docker/podman 高危 daemon 操作，命中时禁止自动放行。

        对齐 Hermes daemon-redirect 审批门的产品意图：容器/守护进程级危险操作
        （特权模式、宿主网络/进程/IPC、全部 capability、设备直通、挂载根目录）
        即使工具级策略关闭确认也不自动放行。
        """
        lowered = str(command or "").lower()
        if not re.search(r"\b(?:docker|podman)\s+(?:run|exec|create)\b", lowered):
            return False
        if any(marker in lowered for marker in SmartApprovalPolicyService._DAEMON_DANGEROUS_MARKERS):
            return True
        if re.search(r"(?:-v|--volume)\s+/[\s:]", lowered):
            return True
        if re.search(r"--mount\s+type=bind,[^\s]*src=/", lowered):
            return True
        return False

    def should_auto_approve(
        self,
        tool_name: str,
        *,
        account_id: str | None = None,
        tool_input: dict[str, Any] | None = None,
    ) -> bool:
        """命中管理员配置的免确认策略时返回 True。"""
        normalized = str(tool_name or "").strip()
        if not normalized:
            return False
        command = self._extract_command_text(tool_input)
        if command and self.contains_dangerous_container_command(command):
            return False
        try:
            policy = (
                self.db.session.query(ToolGovernancePolicy)
                .filter(
                    ToolGovernancePolicy.tool_name == normalized,
                    ToolGovernancePolicy.enabled.is_(True),
                    ToolGovernancePolicy.require_confirmation.is_(False),
                )
                .order_by(ToolGovernancePolicy.created_at.desc())
                .first()
            )
        except Exception:
            logger.warning("查询智能审批策略失败，tool_name=%s", normalized, exc_info=True)
            return False
        if policy is None:
            return False
        if str(policy.risk_level or "").lower() == "dangerous":
            return False
        return True

    @staticmethod
    def _extract_command_text(tool_input: dict[str, Any] | None) -> str:
        if not isinstance(tool_input, dict):
            return ""
        for key in ("command", "script", "task", "code", "cmd"):
            value = tool_input.get(key)
            if isinstance(value, str):
                return value
        return ""
