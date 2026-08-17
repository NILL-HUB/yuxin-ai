"""merge rbac/recycle-bin and tts migration heads

Revision ID: d4e5f6a7b8c9
Revises: c1d2e3f4a5b6, f8a9b0c1d2e3
Create Date: 2026-08-17 00:00:00.000000

本地工作区同时存在 RBAC/回收站迁移链与 TTS 迁移链，
合并两个 head，保证 ``alembic upgrade head`` 可正常执行。
"""
from alembic import op


revision = "d4e5f6a7b8c9"
down_revision = ("c1d2e3f4a5b6", "f8a9b0c1d2e3")
branch_labels = None
depends_on = None


def upgrade():
    pass


def downgrade():
    pass
