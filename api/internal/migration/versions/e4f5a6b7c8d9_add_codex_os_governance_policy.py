"""add codex_os run_os_task governance policy

Revision ID: e4f5a6b7c8d9
Revises: e3f4a5b6c7d8
Create Date: 2026-08-12 00:00:00.000000

为 Codex OS 自动化内置工具配置高风险治理策略：
- risk_level=high
- require_confirmation=true
- enabled=true
"""
from alembic import op
import sqlalchemy as sa


revision = "e4f5a6b7c8d9"
down_revision = "e3f4a5b6c7d8"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        sa.text(
            """
            INSERT INTO tool_governance_policy
                (tool_id, tool_name, source_type, provider_id, risk_level,
                 visibility, allowed_pools, enabled, max_invocations_per_request,
                 cooldown_seconds, require_confirmation, description, updated_at, created_at)
            VALUES
                ('builtin:codex_os:run_os_task', 'run_os_task', 'builtin', 'codex_os',
                 'high', 'private', '[]'::jsonb, true, 5, 0, true,
                 'Codex OS 自动化：必须 preview + 用户确认后才能执行',
                 NOW(), NOW())
            ON CONFLICT DO NOTHING
            """
        )
    )


def downgrade() -> None:
    op.execute(
        sa.text(
            """
            DELETE FROM tool_governance_policy
            WHERE tool_id = 'builtin:codex_os:run_os_task'
            """
        )
    )
