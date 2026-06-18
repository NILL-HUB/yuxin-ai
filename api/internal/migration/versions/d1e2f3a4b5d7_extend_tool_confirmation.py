"""extend tool_confirmation with risk context fields

Revision ID: d1e2f3a4b5d7
Revises: d1e2f3a4b5d6
Create Date: 2026-06-18 00:01:00.000000
"""
from alembic import op
import sqlalchemy as sa


revision = 'd1e2f3a4b5d7'
down_revision = 'd1e2f3a4b5d6'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('tool_confirmation', sa.Column('target_system', sa.String(length=255), nullable=True, server_default=sa.text("''::character varying")))
    op.add_column('tool_confirmation', sa.Column('target_environment', sa.String(length=64), nullable=True, server_default=sa.text("''::character varying")))
    op.add_column('tool_confirmation', sa.Column('execution_summary', sa.Text(), nullable=True, server_default=sa.text("''::text")))
    op.add_column('tool_confirmation', sa.Column('impact_scope', sa.Text(), nullable=True, server_default=sa.text("''::text")))
    op.add_column('tool_confirmation', sa.Column('rollback_strategy', sa.Text(), nullable=True, server_default=sa.text("''::text")))
    op.add_column('tool_confirmation', sa.Column('audit_hint', sa.Text(), nullable=True, server_default=sa.text("''::text")))


def downgrade():
    op.drop_column('tool_confirmation', 'audit_hint')
    op.drop_column('tool_confirmation', 'rollback_strategy')
    op.drop_column('tool_confirmation', 'impact_scope')
    op.drop_column('tool_confirmation', 'execution_summary')
    op.drop_column('tool_confirmation', 'target_environment')
    op.drop_column('tool_confirmation', 'target_system')
