"""add admin rbac tables

Revision ID: a2b3c4d5e6f7
Revises: f9a1b2c3d4e5
Create Date: 2026-06-12 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = 'a2b3c4d5e6f7'
down_revision = 'f9a1b2c3d4e5'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'admin_user',
        sa.Column('id', sa.UUID(), server_default=sa.text('uuid_generate_v4()'), nullable=False),
        sa.Column('name', sa.String(length=255), server_default=sa.text("''::character varying"), nullable=False),
        sa.Column('email', sa.String(length=255), server_default=sa.text("''::character varying"), nullable=False),
        sa.Column('avatar', sa.String(length=255), server_default=sa.text("''::character varying"), nullable=False),
        sa.Column('password', sa.String(length=255), server_default=sa.text("''::character varying"), nullable=True),
        sa.Column('password_salt', sa.String(length=255), server_default=sa.text("''::character varying"), nullable=True),
        sa.Column('status', sa.String(length=64), server_default=sa.text("'active'::character varying"), nullable=False),
        sa.Column('last_login_at', sa.DateTime(), nullable=True),
        sa.Column('last_login_ip', sa.String(length=255), server_default=sa.text("''::character varying"), nullable=False),
        sa.Column('updated_at', sa.DateTime(), server_default=sa.text('CURRENT_TIMESTAMP(0)'), nullable=False),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('CURRENT_TIMESTAMP(0)'), nullable=False),
        sa.PrimaryKeyConstraint('id', name='pk_admin_user_id'),
        sa.UniqueConstraint('email', name='uq_admin_user_email'),
    )
    op.create_index('admin_user_email_idx', 'admin_user', ['email'])
    op.create_index('admin_user_status_idx', 'admin_user', ['status'])

    op.create_table(
        'role',
        sa.Column('id', sa.UUID(), server_default=sa.text('uuid_generate_v4()'), nullable=False),
        sa.Column('name', sa.String(length=255), server_default=sa.text("''::character varying"), nullable=False),
        sa.Column('code', sa.String(length=255), server_default=sa.text("''::character varying"), nullable=False),
        sa.Column('description', sa.Text(), server_default=sa.text("''::text"), nullable=False),
        sa.Column('is_system', sa.Boolean(), server_default=sa.text('false'), nullable=False),
        sa.Column('updated_at', sa.DateTime(), server_default=sa.text('CURRENT_TIMESTAMP(0)'), nullable=False),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('CURRENT_TIMESTAMP(0)'), nullable=False),
        sa.PrimaryKeyConstraint('id', name='pk_role_id'),
        sa.UniqueConstraint('code', name='uq_role_code'),
    )
    op.create_index('role_code_idx', 'role', ['code'])
    op.create_index('role_is_system_idx', 'role', ['is_system'])

    op.create_table(
        'permission',
        sa.Column('id', sa.UUID(), server_default=sa.text('uuid_generate_v4()'), nullable=False),
        sa.Column('code', sa.String(length=255), server_default=sa.text("''::character varying"), nullable=False),
        sa.Column('name', sa.String(length=255), server_default=sa.text("''::character varying"), nullable=False),
        sa.Column('resource', sa.String(length=255), server_default=sa.text("''::character varying"), nullable=False),
        sa.Column('action', sa.String(length=255), server_default=sa.text("''::character varying"), nullable=False),
        sa.Column('description', sa.Text(), server_default=sa.text("''::text"), nullable=False),
        sa.Column('updated_at', sa.DateTime(), server_default=sa.text('CURRENT_TIMESTAMP(0)'), nullable=False),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('CURRENT_TIMESTAMP(0)'), nullable=False),
        sa.PrimaryKeyConstraint('id', name='pk_permission_id'),
        sa.UniqueConstraint('code', name='uq_permission_code'),
    )
    op.create_index('permission_code_idx', 'permission', ['code'])
    op.create_index('permission_resource_action_idx', 'permission', ['resource', 'action'])

    op.create_table(
        'admin_session',
        sa.Column('id', sa.UUID(), server_default=sa.text('uuid_generate_v4()'), nullable=False),
        sa.Column('admin_user_id', sa.UUID(), nullable=False),
        sa.Column('user_agent', sa.String(length=1024), server_default=sa.text("''::character varying"), nullable=False),
        sa.Column('last_login_ip', sa.String(length=255), server_default=sa.text("''::character varying"), nullable=False),
        sa.Column('last_active_at', sa.DateTime(), server_default=sa.text('CURRENT_TIMESTAMP(0)'), nullable=False),
        sa.Column('expires_at', sa.DateTime(), nullable=True),
        sa.Column('revoked_at', sa.DateTime(), nullable=True),
        sa.Column('updated_at', sa.DateTime(), server_default=sa.text('CURRENT_TIMESTAMP(0)'), nullable=False),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('CURRENT_TIMESTAMP(0)'), nullable=False),
        sa.ForeignKeyConstraint(['admin_user_id'], ['admin_user.id']),
        sa.PrimaryKeyConstraint('id', name='pk_admin_session_id'),
    )
    op.create_index('admin_session_admin_user_id_idx', 'admin_session', ['admin_user_id'])
    op.create_index('admin_session_expires_at_idx', 'admin_session', ['expires_at'])
    op.create_index('admin_session_revoked_at_idx', 'admin_session', ['revoked_at'])

    op.create_table(
        'admin_user_role',
        sa.Column('admin_user_id', sa.UUID(), nullable=False),
        sa.Column('role_id', sa.UUID(), nullable=False),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('CURRENT_TIMESTAMP(0)'), nullable=False),
        sa.ForeignKeyConstraint(['admin_user_id'], ['admin_user.id']),
        sa.ForeignKeyConstraint(['role_id'], ['role.id']),
        sa.PrimaryKeyConstraint('admin_user_id', 'role_id', name='pk_admin_user_role'),
    )
    op.create_index('admin_user_role_admin_user_id_idx', 'admin_user_role', ['admin_user_id'])
    op.create_index('admin_user_role_role_id_idx', 'admin_user_role', ['role_id'])

    op.create_table(
        'role_permission',
        sa.Column('role_id', sa.UUID(), nullable=False),
        sa.Column('permission_id', sa.UUID(), nullable=False),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('CURRENT_TIMESTAMP(0)'), nullable=False),
        sa.ForeignKeyConstraint(['permission_id'], ['permission.id']),
        sa.ForeignKeyConstraint(['role_id'], ['role.id']),
        sa.PrimaryKeyConstraint('role_id', 'permission_id', name='pk_role_permission'),
    )
    op.create_index('role_permission_permission_id_idx', 'role_permission', ['permission_id'])
    op.create_index('role_permission_role_id_idx', 'role_permission', ['role_id'])

    op.create_table(
        'audit_log',
        sa.Column('id', sa.UUID(), server_default=sa.text('uuid_generate_v4()'), nullable=False),
        sa.Column('admin_user_id', sa.UUID(), nullable=True),
        sa.Column('action', sa.String(length=255), server_default=sa.text("''::character varying"), nullable=False),
        sa.Column('resource_type', sa.String(length=255), server_default=sa.text("''::character varying"), nullable=False),
        sa.Column('resource_id', sa.String(length=255), server_default=sa.text("''::character varying"), nullable=False),
        sa.Column('ip', sa.String(length=255), server_default=sa.text("''::character varying"), nullable=False),
        sa.Column('user_agent', sa.String(length=1024), server_default=sa.text("''::character varying"), nullable=False),
        sa.Column('before_data', postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'{}'::jsonb"), nullable=False),
        sa.Column('after_data', postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'{}'::jsonb"), nullable=False),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('CURRENT_TIMESTAMP(0)'), nullable=False),
        sa.ForeignKeyConstraint(['admin_user_id'], ['admin_user.id']),
        sa.PrimaryKeyConstraint('id', name='pk_audit_log_id'),
    )
    op.create_index('audit_log_action_idx', 'audit_log', ['action'])
    op.create_index('audit_log_admin_user_id_idx', 'audit_log', ['admin_user_id'])
    op.create_index('audit_log_created_at_idx', 'audit_log', ['created_at'])
    op.create_index('audit_log_resource_type_idx', 'audit_log', ['resource_type'])


def downgrade():
    op.drop_index('audit_log_resource_type_idx', table_name='audit_log')
    op.drop_index('audit_log_created_at_idx', table_name='audit_log')
    op.drop_index('audit_log_admin_user_id_idx', table_name='audit_log')
    op.drop_index('audit_log_action_idx', table_name='audit_log')
    op.drop_table('audit_log')

    op.drop_index('role_permission_role_id_idx', table_name='role_permission')
    op.drop_index('role_permission_permission_id_idx', table_name='role_permission')
    op.drop_table('role_permission')

    op.drop_index('admin_user_role_role_id_idx', table_name='admin_user_role')
    op.drop_index('admin_user_role_admin_user_id_idx', table_name='admin_user_role')
    op.drop_table('admin_user_role')

    op.drop_index('admin_session_revoked_at_idx', table_name='admin_session')
    op.drop_index('admin_session_expires_at_idx', table_name='admin_session')
    op.drop_index('admin_session_admin_user_id_idx', table_name='admin_session')
    op.drop_table('admin_session')

    op.drop_index('permission_resource_action_idx', table_name='permission')
    op.drop_index('permission_code_idx', table_name='permission')
    op.drop_table('permission')

    op.drop_index('role_is_system_idx', table_name='role')
    op.drop_index('role_code_idx', table_name='role')
    op.drop_table('role')

    op.drop_index('admin_user_status_idx', table_name='admin_user')
    op.drop_index('admin_user_email_idx', table_name='admin_user')
    op.drop_table('admin_user')
