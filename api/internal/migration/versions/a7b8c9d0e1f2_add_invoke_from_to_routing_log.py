"""add invoke_from to routing_log

Revision ID: a7b8c9d0e1f2
Revises: x9y0z1a2b3c4
Create Date: 2026-08-07 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


revision = 'a7b8c9d0e1f2'
down_revision = 'x9y0z1a2b3c4'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        'routing_log',
        sa.Column(
            'invoke_from',
            sa.String(length=32),
            server_default=sa.text("''::character varying"),
            nullable=False,
        ),
    )


def downgrade():
    op.drop_column('routing_log', 'invoke_from')
