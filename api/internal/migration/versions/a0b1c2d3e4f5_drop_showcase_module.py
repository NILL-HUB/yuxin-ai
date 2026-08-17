"""drop showcase module

Revision ID: a0b1c2d3e4f5
Revises: d4e5f6a7b8c9
Create Date: 2026-08-17 00:00:00.000000

移除案例展示板块：删除 showcase_case 表及 showcase 权限点。
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "a0b1c2d3e4f5"
down_revision = "d4e5f6a7b8c9"
branch_labels = None
depends_on = None


SHOWCASE_PERMISSION_CODES = (
    "showcase:read",
    "showcase:approve",
    "showcase:update",
)


def upgrade():
    op.drop_table("showcase_case")

    conn = op.get_bind()
    for code in SHOWCASE_PERMISSION_CODES:
        permission_id = conn.execute(
            sa.text("SELECT id FROM permission WHERE code = :code"),
            {"code": code},
        ).scalar_one_or_none()
        if permission_id is not None:
            conn.execute(
                sa.text("DELETE FROM role_permission WHERE permission_id = :permission_id"),
                {"permission_id": permission_id},
            )
            conn.execute(
                sa.text("DELETE FROM permission WHERE id = :permission_id"),
                {"permission_id": permission_id},
            )


def downgrade():
    op.create_table(
        "showcase_case",
        sa.Column("id", sa.UUID(), server_default=sa.text("uuid_generate_v4()"), nullable=False),
        sa.Column("conversation_id", sa.UUID(), nullable=False),
        sa.Column("account_id", sa.UUID(), nullable=False),
        sa.Column("title", sa.String(length=200), server_default=sa.text("''::character varying"), nullable=False),
        sa.Column("summary", sa.Text(), server_default=sa.text("''::text"), nullable=False),
        sa.Column("query", sa.Text(), server_default=sa.text("''::text"), nullable=False),
        sa.Column("answer", sa.Text(), server_default=sa.text("''::text"), nullable=False),
        sa.Column("tags", postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'[]'::jsonb"), nullable=False),
        sa.Column("rating", sa.Integer(), server_default=sa.text("5"), nullable=False),
        sa.Column("status", sa.String(length=32), server_default=sa.text("'pending'::character varying"), nullable=False),
        sa.Column("reject_reason", sa.Text(), server_default=sa.text("''::text"), nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP(0)"), nullable=False),
        sa.Column("approved_at", sa.DateTime(), nullable=True),
        sa.Column("approved_by", sa.UUID(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP(0)"), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_showcase_case_id"),
    )
    op.create_index("showcase_case_conversation_id_idx", "showcase_case", ["conversation_id"])
    op.create_index("showcase_case_account_id_idx", "showcase_case", ["account_id"])
    op.create_index("showcase_case_status_idx", "showcase_case", ["status"])

    conn = op.get_bind()
    for code, resource, action, name in (
        ("showcase:read", "showcase", "read", "查看案例展示"),
        ("showcase:approve", "showcase", "approve", "审核案例展示"),
        ("showcase:update", "showcase", "update", "管理案例展示"),
    ):
        conn.execute(
            sa.text(
                "INSERT INTO permission (id, code, name, resource, action, description) "
                "VALUES (uuid_generate_v4(), :code, :name, :resource, :action, '') "
                "ON CONFLICT (code) DO NOTHING"
            ),
            {"code": code, "name": name, "resource": resource, "action": action},
        )
