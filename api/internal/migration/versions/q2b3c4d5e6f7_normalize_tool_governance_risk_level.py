"""normalize tool governance risk_level enum

Revision ID: q2b3c4d5e6f7
Revises: p1a2b3c4d5e6
Create Date: 2026-09-14 00:00:00.000000

统一工具治理风险等级枚举。

背景：管理端曾使用 `low/medium/high/critical`，而运行时治理使用
`safe/low/medium/high/sensitive/dangerous`。`critical` 不在运行时枚举内，
经 `normalize_tool_metadata` 会被静默降级为 `medium`，导致管理员配置的
高风险工具在治理阶段2/3被放行。

处理：
1. `critical` → `dangerous`（语义对齐：均为最高危档，不可自动触发）。
2. 兜底：任何不在运行时枚举内的历史脏值统一回退为 `medium`
   （与运行时归一化默认值一致，避免遗留非法值继续影响治理判定）。

运行时枚举唯一事实源：api/internal/entity/tool_inventory_entity.py 的 RiskLevel。
"""
from alembic import op
import sqlalchemy as sa

revision = "q2b3c4d5e6f7"
down_revision = "p1a2b3c4d5e6"
branch_labels = None
depends_on = None

_VALID_RISK_LEVELS = ("safe", "low", "medium", "high", "sensitive", "dangerous")


def upgrade() -> None:
    op.execute(
        sa.text(
            """
            UPDATE tool_governance_policy
            SET risk_level = 'dangerous', updated_at = NOW()
            WHERE risk_level = 'critical'
            """
        )
    )
    valid_literal = ", ".join(f"'{level}'" for level in _VALID_RISK_LEVELS)
    op.execute(
        sa.text(
            f"""
            UPDATE tool_governance_policy
            SET risk_level = 'medium', updated_at = NOW()
            WHERE risk_level NOT IN ({valid_literal})
            """
        )
    )


def downgrade() -> None:
    # 不可逆：critical 与 dangerous 已合并，无法区分原始取值。
    # 仅在明确需要回滚枚举语义时手工处理，此处保持数据不变。
    pass
