"""add billing membership redeem code tables

Revision ID: c4d5e6f7a8b9
Revises: b3c4d5e6f7a8
Create Date: 2026-06-12 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


revision = 'c4d5e6f7a8b9'
down_revision = 'b3c4d5e6f7a8'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'plan',
        sa.Column('id', sa.UUID(), server_default=sa.text('uuid_generate_v4()'), nullable=False),
        sa.Column('code', sa.String(length=128), nullable=False),
        sa.Column('name', sa.String(length=255), nullable=False),
        sa.Column('description', sa.String(length=1024), server_default=sa.text("''::character varying"), nullable=False),
        sa.Column('duration_days', sa.BigInteger(), server_default=sa.text('0'), nullable=False),
        sa.Column('grant_token_credits', sa.BigInteger(), server_default=sa.text('0'), nullable=False),
        sa.Column('price', sa.Numeric(10, 2), server_default=sa.text('0.00'), nullable=False),
        sa.Column('status', sa.String(length=64), server_default=sa.text("'active'::character varying"), nullable=False),
        sa.Column('sort_order', sa.BigInteger(), server_default=sa.text('0'), nullable=False),
        sa.Column('updated_at', sa.DateTime(), server_default=sa.text('CURRENT_TIMESTAMP(0)'), nullable=False),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('CURRENT_TIMESTAMP(0)'), nullable=False),
        sa.PrimaryKeyConstraint('id', name='pk_plan_id'),
    )
    op.create_index('plan_code_idx', 'plan', ['code'], unique=True)
    op.create_index('plan_status_idx', 'plan', ['status'])

    op.create_table(
        'plan_entitlement',
        sa.Column('id', sa.UUID(), server_default=sa.text('uuid_generate_v4()'), nullable=False),
        sa.Column('plan_id', sa.UUID(), nullable=False),
        sa.Column('feature_key', sa.String(length=128), nullable=False),
        sa.Column('feature_value', sa.String(length=1024), server_default=sa.text("''::character varying"), nullable=False),
        sa.Column('value_type', sa.String(length=64), server_default=sa.text("'string'::character varying"), nullable=False),
        sa.Column('updated_at', sa.DateTime(), server_default=sa.text('CURRENT_TIMESTAMP(0)'), nullable=False),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('CURRENT_TIMESTAMP(0)'), nullable=False),
        sa.PrimaryKeyConstraint('id', name='pk_plan_entitlement_id'),
    )
    op.create_index('plan_entitlement_plan_feature_idx', 'plan_entitlement', ['plan_id', 'feature_key'], unique=True)

    op.create_table(
        'membership',
        sa.Column('id', sa.UUID(), server_default=sa.text('uuid_generate_v4()'), nullable=False),
        sa.Column('account_id', sa.UUID(), nullable=False),
        sa.Column('plan_id', sa.UUID(), nullable=False),
        sa.Column('status', sa.String(length=64), server_default=sa.text("'active'::character varying"), nullable=False),
        sa.Column('started_at', sa.DateTime(), server_default=sa.text('CURRENT_TIMESTAMP(0)'), nullable=False),
        sa.Column('expires_at', sa.DateTime(), nullable=False),
        sa.Column('source', sa.String(length=64), server_default=sa.text("''::character varying"), nullable=False),
        sa.Column('source_id', sa.UUID(), nullable=True),
        sa.Column('updated_at', sa.DateTime(), server_default=sa.text('CURRENT_TIMESTAMP(0)'), nullable=False),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('CURRENT_TIMESTAMP(0)'), nullable=False),
        sa.PrimaryKeyConstraint('id', name='pk_membership_id'),
    )
    op.create_index('membership_account_status_idx', 'membership', ['account_id', 'status'])
    op.create_index('membership_account_expires_idx', 'membership', ['account_id', 'expires_at'])
    op.create_index('membership_source_idx', 'membership', ['source', 'source_id'])

    op.create_table(
        'credit_account',
        sa.Column('id', sa.UUID(), server_default=sa.text('uuid_generate_v4()'), nullable=False),
        sa.Column('account_id', sa.UUID(), nullable=False),
        sa.Column('balance', sa.BigInteger(), server_default=sa.text('0'), nullable=False),
        sa.Column('total_granted', sa.BigInteger(), server_default=sa.text('0'), nullable=False),
        sa.Column('total_consumed', sa.BigInteger(), server_default=sa.text('0'), nullable=False),
        sa.Column('updated_at', sa.DateTime(), server_default=sa.text('CURRENT_TIMESTAMP(0)'), nullable=False),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('CURRENT_TIMESTAMP(0)'), nullable=False),
        sa.PrimaryKeyConstraint('id', name='pk_credit_account_id'),
    )
    op.create_index('credit_account_account_id_idx', 'credit_account', ['account_id'], unique=True)

    op.create_table(
        'credit_transaction',
        sa.Column('id', sa.UUID(), server_default=sa.text('uuid_generate_v4()'), nullable=False),
        sa.Column('account_id', sa.UUID(), nullable=False),
        sa.Column('amount', sa.BigInteger(), nullable=False),
        sa.Column('balance_after', sa.BigInteger(), nullable=False),
        sa.Column('transaction_type', sa.String(length=64), nullable=False),
        sa.Column('source', sa.String(length=64), server_default=sa.text("''::character varying"), nullable=False),
        sa.Column('source_id', sa.UUID(), nullable=True),
        sa.Column('description', sa.String(length=1024), server_default=sa.text("''::character varying"), nullable=False),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('CURRENT_TIMESTAMP(0)'), nullable=False),
        sa.PrimaryKeyConstraint('id', name='pk_credit_transaction_id'),
    )
    op.create_index('credit_transaction_account_created_idx', 'credit_transaction', ['account_id', 'created_at'])
    op.create_index('credit_transaction_source_idx', 'credit_transaction', ['source', 'source_id'])

    op.create_table(
        'redeem_code_batch',
        sa.Column('id', sa.UUID(), server_default=sa.text('uuid_generate_v4()'), nullable=False),
        sa.Column('name', sa.String(length=255), nullable=False),
        sa.Column('plan_id', sa.UUID(), nullable=False),
        sa.Column('quantity', sa.BigInteger(), nullable=False),
        sa.Column('expires_at', sa.DateTime(), nullable=True),
        sa.Column('created_by', sa.UUID(), nullable=True),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('CURRENT_TIMESTAMP(0)'), nullable=False),
        sa.PrimaryKeyConstraint('id', name='pk_redeem_code_batch_id'),
    )
    op.create_index('redeem_code_batch_plan_id_idx', 'redeem_code_batch', ['plan_id'])

    op.create_table(
        'redeem_code',
        sa.Column('id', sa.UUID(), server_default=sa.text('uuid_generate_v4()'), nullable=False),
        sa.Column('batch_id', sa.UUID(), nullable=True),
        sa.Column('plan_id', sa.UUID(), nullable=False),
        sa.Column('code_hash', sa.String(length=255), nullable=False),
        sa.Column('code_mask', sa.String(length=64), nullable=False),
        sa.Column('status', sa.String(length=64), server_default=sa.text("'unused'::character varying"), nullable=False),
        sa.Column('redeemed_by', sa.UUID(), nullable=True),
        sa.Column('redeemed_at', sa.DateTime(), nullable=True),
        sa.Column('expires_at', sa.DateTime(), nullable=True),
        sa.Column('disabled_at', sa.DateTime(), nullable=True),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('CURRENT_TIMESTAMP(0)'), nullable=False),
        sa.PrimaryKeyConstraint('id', name='pk_redeem_code_id'),
    )
    op.create_index('redeem_code_hash_idx', 'redeem_code', ['code_hash'], unique=True)
    op.create_index('redeem_code_batch_status_idx', 'redeem_code', ['batch_id', 'status'])
    op.create_index('redeem_code_redeemed_by_idx', 'redeem_code', ['redeemed_by'])


def downgrade():
    op.drop_index('redeem_code_redeemed_by_idx', table_name='redeem_code')
    op.drop_index('redeem_code_batch_status_idx', table_name='redeem_code')
    op.drop_index('redeem_code_hash_idx', table_name='redeem_code')
    op.drop_table('redeem_code')
    op.drop_index('redeem_code_batch_plan_id_idx', table_name='redeem_code_batch')
    op.drop_table('redeem_code_batch')
    op.drop_index('credit_transaction_source_idx', table_name='credit_transaction')
    op.drop_index('credit_transaction_account_created_idx', table_name='credit_transaction')
    op.drop_table('credit_transaction')
    op.drop_index('credit_account_account_id_idx', table_name='credit_account')
    op.drop_table('credit_account')
    op.drop_index('membership_source_idx', table_name='membership')
    op.drop_index('membership_account_expires_idx', table_name='membership')
    op.drop_index('membership_account_status_idx', table_name='membership')
    op.drop_table('membership')
    op.drop_index('plan_entitlement_plan_feature_idx', table_name='plan_entitlement')
    op.drop_table('plan_entitlement')
    op.drop_index('plan_status_idx', table_name='plan')
    op.drop_index('plan_code_idx', table_name='plan')
    op.drop_table('plan')
