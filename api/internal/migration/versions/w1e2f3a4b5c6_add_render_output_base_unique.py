"""add partial unique index for render output knowledge base

设计依据：docs/superpowers/specs/2026-09-16-video-production-p4-design.md §4.1/§4.2。

成品库是「每用户唯一、系统托管」的归集处：用户不应能随手建多个「成品库」。
仅靠代码里的 get_or_create 无法防并发创建（两个请求同时查不到就各建一个），
故用 PostgreSQL 部分唯一索引兜底。

为什么是「部分」唯一索引而非普通唯一约束：
    created_from='manual_upload' 等取值在同一账号下是允许重复的（用户可建多个
    素材库），只有 render_output 要求每账号至多一个。全表唯一约束会把
    正常的多库场景误判为冲突。

Revision ID: w1e2f3a4b5c6
Revises: v0d1e2f3a4b5
"""
from alembic import op
import sqlalchemy as sa  # noqa: F401  （迁移风格一致性）

revision = "w1e2f3a4b5c6"
down_revision = "v0d1e2f3a4b5"
branch_labels = None
depends_on = None


def upgrade():
    op.create_index(
        "knowledge_base_render_output_uniq",
        "knowledge_base",
        ["owner_account_id"],
        unique=True,
        postgresql_where=sa.text("created_from = 'render_output'"),
    )


def downgrade():
    op.drop_index("knowledge_base_render_output_uniq", table_name="knowledge_base")
