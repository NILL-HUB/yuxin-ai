"""add agent metadata to app

Revision ID: d1e2f3a4b5c8
Revises: d1e2f3a4b5c7
Create Date: 2026-06-15 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = 'd1e2f3a4b5c8'
down_revision = 'd1e2f3a4b5c7'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('app', schema=None) as batch_op:
        batch_op.add_column(
            sa.Column(
                'agent_metadata',
                postgresql.JSONB(astext_type=sa.Text()),
                server_default=sa.text("'{}'::jsonb"),
                nullable=False,
            )
        )


def downgrade():
    with op.batch_alter_table('app', schema=None) as batch_op:
        batch_op.drop_column('agent_metadata')
