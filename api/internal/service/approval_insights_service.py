"""审批历史分析服务。

把 `approval_mining` 的纯算法接到 `tool_confirmation` 表：管理员可查看
“哪些高风险工具值得配置免重复授权 / 哪些请求模式被连续拒绝”，只做
dry-run 建议，不自动修改任何策略。
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from injector import inject

from internal.core.agent.adapters.hermes.approval_mining import (
    ConfirmationRecord,
    as_serializable,
    mine_approval_history,
)
from internal.model import ToolConfirmation
from pkg.sqlalchemy import SQLAlchemy

logger = logging.getLogger(__name__)


@inject
@dataclass
class ApprovalInsightsService:
    db: SQLAlchemy

    def analyze_recent(
        self,
        *,
        account_id: str | None = None,
        days: int = 90,
        limit: int = 2000,
    ) -> dict:
        """分析最近审批记录，返回 allowlist 建议与熔断信号。"""
        query = self.db.session.query(ToolConfirmation)
        if account_id:
            query = query.filter(ToolConfirmation.owner_account_id == account_id)
        cutoff = datetime.now(UTC).replace(tzinfo=None) - timedelta(days=max(1, days))
        query = query.filter(ToolConfirmation.created_at >= cutoff)
        rows = query.order_by(ToolConfirmation.created_at.desc()).limit(max(1, limit)).all()

        records = [
            ConfirmationRecord(
                tool_name=str(row.tool_name or ""),
                status=str(row.status or ""),
                tool_input=dict(row.tool_input or {}),
                execution_summary=str(row.execution_summary or ""),
                reason=str(row.reason or ""),
                created_at=row.created_at,
            )
            for row in rows
        ]
        result = mine_approval_history(records)
        return as_serializable(result)
