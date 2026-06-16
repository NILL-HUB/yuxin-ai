"""add orchestration feature flag

Revision ID: d1e2f3a4b5d2
Revises: d1e2f3a4b5d1
Create Date: 2026-06-16 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


revision = 'd1e2f3a4b5d2'
down_revision = 'd1e2f3a4b5d1'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'orchestration_feature_flag',
        sa.Column(
            'id',
            sa.UUID(),
            server_default=sa.text('uuid_generate_v4()'),
            nullable=False,
        ),
        sa.Column('code', sa.String(length=128), nullable=False),
        sa.Column('name', sa.String(length=128), nullable=False),
        sa.Column(
            'description',
            sa.Text(),
            server_default=sa.text("''"),
            nullable=False,
        ),
        sa.Column(
            'enabled',
            sa.Boolean(),
            server_default=sa.text('false'),
            nullable=False,
        ),
        sa.Column('risk_level', sa.String(length=64), nullable=False),
        sa.Column('fallback_behavior', sa.String(length=128), nullable=False),
        sa.Column('updated_by', sa.UUID(), nullable=True),
        sa.Column(
            'updated_at',
            sa.DateTime(),
            server_default=sa.text('CURRENT_TIMESTAMP(0)'),
            nullable=False,
        ),
        sa.Column(
            'created_at',
            sa.DateTime(),
            server_default=sa.text('CURRENT_TIMESTAMP(0)'),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint('id', name='pk_orchestration_feature_flag_id'),
        sa.UniqueConstraint('code', name='uq_orchestration_feature_flag_code'),
    )
    op.create_index(
        'orchestration_feature_flag_code_idx',
        'orchestration_feature_flag',
        ['code'],
    )


def downgrade():
    op.drop_index(
        'orchestration_feature_flag_code_idx',
        table_name='orchestration_feature_flag',
    )
    op.drop_table('orchestration_feature_flag')
