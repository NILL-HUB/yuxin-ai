"""upgrade context management phase h

Revision ID: f2a3b4c5d6e8
Revises: d1e2f3a4b5d7, e1f2a3b4c5d7
Create Date: 2026-06-23 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = 'f2a3b4c5d6e8'
down_revision = ('d1e2f3a4b5d7', 'e1f2a3b4c5d7')
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('conversation', sa.Column('distant_summaries', postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'[]'::jsonb"), nullable=False))
    op.add_column('conversation', sa.Column('last_summarized_message_index', sa.Integer(), server_default=sa.text("0"), nullable=False))


def downgrade():
    op.drop_column('conversation', 'last_summarized_message_index')
    op.drop_column('conversation', 'distant_summaries')
