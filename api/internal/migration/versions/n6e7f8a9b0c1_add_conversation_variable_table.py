"""add conversation_variable table

Revision ID: n6e7f8a9b0c1
Revises: m5d6e7f8a9b0
Create Date: 2026-07-04 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision = 'n6e7f8a9b0c1'
down_revision = 'm5d6e7f8a9b0'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'conversation_variable',
        sa.Column('id', sa.UUID(), nullable=False, server_default=sa.text('uuid_generate_v4()')),
        sa.Column('conversation_id', sa.UUID(), nullable=False),
        sa.Column('name', sa.String(length=255), nullable=False),
        sa.Column(
            'value_type',
            sa.String(length=32),
            nullable=False,
            server_default=sa.text("'string'::character varying"),
        ),
        sa.Column(
            'value',
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'null'::jsonb"),
        ),
        sa.Column(
            'updated_at',
            sa.DateTime(),
            nullable=False,
            server_default=sa.text('CURRENT_TIMESTAMP(0)'),
            server_onupdate=sa.text('CURRENT_TIMESTAMP(0)'),
        ),
        sa.Column(
            'created_at',
            sa.DateTime(),
            nullable=False,
            server_default=sa.text('CURRENT_TIMESTAMP(0)'),
        ),
        sa.ForeignKeyConstraint(
            ['conversation_id'], ['conversation.id'],
            name='fk_conversation_variable_conversation_id_conversation',
            ondelete='CASCADE',
        ),
        sa.PrimaryKeyConstraint('id', name='pk_conversation_variable_id'),
    )
    op.create_index(
        'conversation_variable_conversation_id_idx',
        'conversation_variable',
        ['conversation_id'],
    )
    op.create_index(
        'conversation_variable_name_idx',
        'conversation_variable',
        ['conversation_id', 'name'],
        unique=True,
    )


def downgrade():
    op.drop_index('conversation_variable_name_idx', table_name='conversation_variable')
    op.drop_index('conversation_variable_conversation_id_idx', table_name='conversation_variable')
    op.drop_table('conversation_variable')
