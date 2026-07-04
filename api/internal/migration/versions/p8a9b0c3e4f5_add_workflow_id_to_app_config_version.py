"""add workflow_id to app_config_version

Revision ID: p8a9b0c3e4f5
Revises: o7f8a9b0c2d3
Create Date: 2026-07-04

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'p8a9b0c3e4f5'
down_revision = 'o7f8a9b0c2d3'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        'app_config_version',
        sa.Column('workflow_id', sa.UUID(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column('app_config_version', 'workflow_id')
