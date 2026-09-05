"""add commerce distribution tables and credit pools

Revision ID: c0e1d2f3a4b6
Revises: a5b6c7d8e9f0
Create Date: 2026-08-28 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


revision = 'c0e1d2f3a4b6'
down_revision = 'a5b6c7d8e9f0'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('plan', sa.Column('plan_type', sa.String(length=32), server_default=sa.text("'membership'::character varying"), nullable=False))
    op.add_column('plan', sa.Column('auto_renew_threshold_percent', sa.BigInteger(), server_default=sa.text('5'), nullable=False))

    op.add_column('credit_account', sa.Column('permanent_credit', sa.BigInteger(), server_default=sa.text('0'), nullable=False))
    op.add_column('credit_account', sa.Column('quota_credit', sa.BigInteger(), server_default=sa.text('0'), nullable=False))
    op.execute("UPDATE credit_account SET permanent_credit = COALESCE(balance, 0) WHERE COALESCE(balance, 0) > 0")
    op.drop_column('credit_account', 'balance')

    op.create_table(
        'referral_code',
        sa.Column('id', sa.UUID(), server_default=sa.text('uuid_generate_v4()'), nullable=False),
        sa.Column('account_id', sa.UUID(), nullable=False),
        sa.Column('code', sa.String(length=64), nullable=False),
        sa.Column('updated_at', sa.DateTime(), server_default=sa.text('CURRENT_TIMESTAMP(0)'), nullable=False),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('CURRENT_TIMESTAMP(0)'), nullable=False),
        sa.PrimaryKeyConstraint('id', name='pk_referral_code_id'),
        sa.UniqueConstraint('account_id', name='uq_referral_code_account_id'),
        sa.UniqueConstraint('code', name='uq_referral_code_code'),
    )

    op.create_table(
        'distribution_relation',
        sa.Column('id', sa.UUID(), server_default=sa.text('uuid_generate_v4()'), nullable=False),
        sa.Column('invitee_account_id', sa.UUID(), nullable=False),
        sa.Column('inviter_account_id', sa.UUID(), nullable=False),
        sa.Column('bound_at', sa.DateTime(), server_default=sa.text('CURRENT_TIMESTAMP(0)'), nullable=False),
        sa.Column('source', sa.String(length=32), server_default=sa.text("'register'::character varying"), nullable=False),
        sa.Column('updated_by', sa.UUID(), nullable=True),
        sa.Column('updated_at', sa.DateTime(), server_default=sa.text('CURRENT_TIMESTAMP(0)'), nullable=False),
        sa.PrimaryKeyConstraint('id', name='pk_distribution_relation_id'),
        sa.UniqueConstraint('invitee_account_id', name='uq_distribution_relation_invitee'),
    )
    op.create_index('distribution_relation_inviter_idx', 'distribution_relation', ['inviter_account_id'])

    op.create_table(
        'balance_account',
        sa.Column('id', sa.UUID(), server_default=sa.text('uuid_generate_v4()'), nullable=False),
        sa.Column('account_id', sa.UUID(), nullable=False),
        sa.Column('balance', sa.Numeric(12, 2), server_default=sa.text('0'), nullable=False),
        sa.Column('total_recharged', sa.Numeric(12, 2), server_default=sa.text('0'), nullable=False),
        sa.Column('total_commission', sa.Numeric(12, 2), server_default=sa.text('0'), nullable=False),
        sa.Column('total_withdrawn', sa.Numeric(12, 2), server_default=sa.text('0'), nullable=False),
        sa.Column('total_purchased', sa.Numeric(12, 2), server_default=sa.text('0'), nullable=False),
        sa.Column('high_rate_locked', sa.Boolean(), server_default=sa.text('false'), nullable=False),
        sa.Column('updated_at', sa.DateTime(), server_default=sa.text('CURRENT_TIMESTAMP(0)'), nullable=False),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('CURRENT_TIMESTAMP(0)'), nullable=False),
        sa.PrimaryKeyConstraint('id', name='pk_balance_account_id'),
        sa.UniqueConstraint('account_id', name='uq_balance_account_account_id'),
    )

    op.create_table(
        'balance_transaction',
        sa.Column('id', sa.UUID(), server_default=sa.text('uuid_generate_v4()'), nullable=False),
        sa.Column('account_id', sa.UUID(), nullable=False),
        sa.Column('amount', sa.Numeric(12, 2), nullable=False),
        sa.Column('balance_after', sa.Numeric(12, 2), nullable=False),
        sa.Column('amount_type', sa.String(length=32), nullable=False),
        sa.Column('rate', sa.Numeric(5, 2), nullable=True),
        sa.Column('source', sa.String(length=32), server_default=sa.text("''::character varying"), nullable=False),
        sa.Column('source_id', sa.UUID(), nullable=True),
        sa.Column('description', sa.String(length=1024), server_default=sa.text("''::character varying"), nullable=False),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('CURRENT_TIMESTAMP(0)'), nullable=False),
        sa.PrimaryKeyConstraint('id', name='pk_balance_transaction_id'),
    )
    op.create_index('balance_transaction_account_created_idx', 'balance_transaction', ['account_id', 'created_at'])
    op.create_index('uq_balance_transaction_source_type', 'balance_transaction', ['source', 'source_id', 'amount_type'], unique=True)

    op.create_table(
        'withdrawal_request',
        sa.Column('id', sa.UUID(), server_default=sa.text('uuid_generate_v4()'), nullable=False),
        sa.Column('account_id', sa.UUID(), nullable=False),
        sa.Column('amount', sa.Numeric(12, 2), nullable=False),
        sa.Column('status', sa.String(length=32), server_default=sa.text("'pending'::character varying"), nullable=False),
        sa.Column('reviewed_by', sa.UUID(), nullable=True),
        sa.Column('reviewed_at', sa.DateTime(), nullable=True),
        sa.Column('review_note', sa.String(length=1024), server_default=sa.text("''::character varying"), nullable=False),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('CURRENT_TIMESTAMP(0)'), nullable=False),
        sa.PrimaryKeyConstraint('id', name='pk_withdrawal_request_id'),
    )
    op.create_index('withdrawal_request_account_idx', 'withdrawal_request', ['account_id'])
    op.create_index('withdrawal_request_status_idx', 'withdrawal_request', ['status'])

    op.create_table(
        'payment_provider_config',
        sa.Column('id', sa.UUID(), server_default=sa.text('uuid_generate_v4()'), nullable=False),
        sa.Column('provider', sa.String(length=32), nullable=False),
        sa.Column('name', sa.String(length=64), server_default=sa.text("''::character varying"), nullable=False),
        sa.Column('configs', sa.JSON(), server_default=sa.text("'{}'::json"), nullable=False),
        sa.Column('enabled', sa.Boolean(), server_default=sa.text('false'), nullable=False),
        sa.Column('updated_by', sa.UUID(), nullable=True),
        sa.Column('updated_at', sa.DateTime(), server_default=sa.text('CURRENT_TIMESTAMP(0)'), nullable=False),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('CURRENT_TIMESTAMP(0)'), nullable=False),
        sa.PrimaryKeyConstraint('id', name='pk_payment_provider_config_id'),
        sa.UniqueConstraint('provider', name='uq_payment_provider_config_provider'),
    )

    op.create_table(
        'purchase_order',
        sa.Column('id', sa.UUID(), server_default=sa.text('uuid_generate_v4()'), nullable=False),
        sa.Column('order_no', sa.String(length=64), nullable=False),
        sa.Column('account_id', sa.UUID(), nullable=False),
        sa.Column('plan_id', sa.UUID(), nullable=False),
        sa.Column('plan_type', sa.String(length=32), nullable=False),
        sa.Column('amount', sa.Numeric(12, 2), server_default=sa.text('0'), nullable=False),
        sa.Column('pay_method', sa.String(length=32), nullable=False),
        sa.Column('order_source', sa.String(length=32), server_default=sa.text("'normal'::character varying"), nullable=False),
        sa.Column('status', sa.String(length=32), server_default=sa.text("'pending'::character varying"), nullable=False),
        sa.Column('transaction_id', sa.String(length=255), nullable=True),
        sa.Column('paid_at', sa.DateTime(), nullable=True),
        sa.Column('refund_at', sa.DateTime(), nullable=True),
        sa.Column('client_ip', sa.String(length=64), server_default=sa.text("''::character varying"), nullable=False),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('CURRENT_TIMESTAMP(0)'), nullable=False),
        sa.Column('updated_at', sa.DateTime(), server_default=sa.text('CURRENT_TIMESTAMP(0)'), nullable=False),
        sa.PrimaryKeyConstraint('id', name='pk_purchase_order_id'),
        sa.UniqueConstraint('order_no', name='uq_purchase_order_order_no'),
    )
    op.create_index('purchase_order_account_status_idx', 'purchase_order', ['account_id', 'status'])
    op.create_index('purchase_order_status_idx', 'purchase_order', ['status'])
    op.create_index('purchase_order_source_idx', 'purchase_order', ['order_source'])

    op.create_table(
        'return_request',
        sa.Column('id', sa.UUID(), server_default=sa.text('uuid_generate_v4()'), nullable=False),
        sa.Column('account_id', sa.UUID(), nullable=False),
        sa.Column('order_id', sa.UUID(), nullable=False),
        sa.Column('amount', sa.Numeric(12, 2), nullable=False),
        sa.Column('reason', sa.String(length=1024), server_default=sa.text("''::character varying"), nullable=False),
        sa.Column('status', sa.String(length=32), server_default=sa.text("'pending'::character varying"), nullable=False),
        sa.Column('reviewed_by', sa.UUID(), nullable=True),
        sa.Column('reviewed_at', sa.DateTime(), nullable=True),
        sa.Column('review_note', sa.String(length=1024), server_default=sa.text("''::character varying"), nullable=False),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('CURRENT_TIMESTAMP(0)'), nullable=False),
        sa.PrimaryKeyConstraint('id', name='pk_return_request_id'),
        sa.UniqueConstraint('order_id', name='uq_return_request_order_id'),
    )
    op.create_index('return_request_account_idx', 'return_request', ['account_id'])
    op.create_index('return_request_status_idx', 'return_request', ['status'])

    op.create_table(
        'auto_renewal',
        sa.Column('id', sa.UUID(), server_default=sa.text('uuid_generate_v4()'), nullable=False),
        sa.Column('account_id', sa.UUID(), nullable=False),
        sa.Column('plan_id', sa.UUID(), nullable=False),
        sa.Column('plan_type', sa.String(length=32), nullable=False),
        sa.Column('pay_method', sa.String(length=32), server_default=sa.text("'balance'::character varying"), nullable=False),
        sa.Column('status', sa.String(length=32), server_default=sa.text("'active'::character varying"), nullable=False),
        sa.Column('next_renew_at', sa.DateTime(), nullable=True),
        sa.Column('last_renewed_at', sa.DateTime(), nullable=True),
        sa.Column('renew_count', sa.BigInteger(), server_default=sa.text('0'), nullable=False),
        sa.Column('fail_count', sa.BigInteger(), server_default=sa.text('0'), nullable=False),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('CURRENT_TIMESTAMP(0)'), nullable=False),
        sa.Column('updated_at', sa.DateTime(), server_default=sa.text('CURRENT_TIMESTAMP(0)'), nullable=False),
        sa.PrimaryKeyConstraint('id', name='pk_auto_renewal_id'),
    )
    op.create_index('auto_renewal_account_idx', 'auto_renewal', ['account_id'])
    op.create_index('auto_renewal_status_idx', 'auto_renewal', ['status'])


def downgrade():
    op.drop_index('auto_renewal_status_idx', table_name='auto_renewal')
    op.drop_index('auto_renewal_account_idx', table_name='auto_renewal')
    op.drop_table('auto_renewal')
    op.drop_index('return_request_status_idx', table_name='return_request')
    op.drop_index('return_request_account_idx', table_name='return_request')
    op.drop_table('return_request')
    op.drop_index('purchase_order_source_idx', table_name='purchase_order')
    op.drop_index('purchase_order_status_idx', table_name='purchase_order')
    op.drop_index('purchase_order_account_status_idx', table_name='purchase_order')
    op.drop_table('purchase_order')
    op.drop_table('payment_provider_config')
    op.drop_index('withdrawal_request_status_idx', table_name='withdrawal_request')
    op.drop_index('withdrawal_request_account_idx', table_name='withdrawal_request')
    op.drop_table('withdrawal_request')
    op.drop_index('uq_balance_transaction_source_type', table_name='balance_transaction')
    op.drop_index('balance_transaction_account_created_idx', table_name='balance_transaction')
    op.drop_table('balance_transaction')
    op.drop_table('balance_account')
    op.drop_index('distribution_relation_inviter_idx', table_name='distribution_relation')
    op.drop_table('distribution_relation')
    op.drop_table('referral_code')
    op.add_column('credit_account', sa.Column('balance', sa.BigInteger(), server_default=sa.text('0'), nullable=False))
    op.execute("UPDATE credit_account SET balance = COALESCE(permanent_credit, 0) WHERE COALESCE(permanent_credit, 0) > 0")
    op.drop_column('credit_account', 'quota_credit')
    op.drop_column('credit_account', 'permanent_credit')
    op.drop_column('plan', 'auto_renew_threshold_percent')
    op.drop_column('plan', 'plan_type')