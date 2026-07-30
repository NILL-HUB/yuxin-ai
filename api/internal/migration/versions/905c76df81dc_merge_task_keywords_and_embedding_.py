"""merge task_keywords and embedding_constraints heads

Revision ID: 905c76df81dc
Revises: a3b4c5d6e7f8, e9f0a1b2c3d4
Create Date: 2026-07-27 14:12:22.647343

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '905c76df81dc'
down_revision = ('a3b4c5d6e7f8', 'e9f0a1b2c3d4')
branch_labels = None
depends_on = None


def upgrade():
    pass


def downgrade():
    pass
