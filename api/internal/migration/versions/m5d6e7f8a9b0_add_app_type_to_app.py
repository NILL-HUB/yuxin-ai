"""add app_type to app

Revision ID: m5d6e7f8a9b0
Revises: l4b5c6d7e8f9
Create Date: 2026-07-04 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'm5d6e7f8a9b0'
down_revision = 'l4b5c6d7e8f9'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('app', schema=None) as batch_op:
        batch_op.add_column(
            sa.Column(
                'app_type',
                sa.String(length=32),
                nullable=False,
                server_default=sa.text("'chatbot'::character varying"),
            )
        )
    op.create_index('app_app_type_idx', 'app', ['app_type'])


def downgrade():
    op.drop_index('app_app_type_idx', table_name='app')
    with op.batch_alter_table('app', schema=None) as batch_op:
        batch_op.drop_column('app_type')
