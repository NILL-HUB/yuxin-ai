"""drop routing_rules from model_tier_policy

Revision ID: f0a1b2c3d4e5
Revises: e8f9a0b1c2d3
Create Date: 2026-08-30 10:00:00.000000
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = 'f0a1b2c3d4e5'
down_revision = 'e8f9a0b1c2d3'
branch_labels = None
depends_on = None


def upgrade():
    op.drop_column('model_tier_policy', 'routing_rules')


def downgrade():
    op.add_column('model_tier_policy', sa.Column(
        'routing_rules', JSONB(),
        server_default=sa.text("'{}'::jsonb"), nullable=False,
    ))