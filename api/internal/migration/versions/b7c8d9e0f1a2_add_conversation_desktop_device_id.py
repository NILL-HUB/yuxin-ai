"""add conversation desktop_device_id

会话级设备绑定：手机/Web 显式选择设备后，把设备标识绑到会话上，
本机工具（os_* / computer / browser）按会话绑定的设备解析 bridge；
显式清空时解绑，回到「默认设备 > 最近在线」的自动解析。

设计：docs/superpowers/specs/2026-10-03-mobile-remote-control-multi-device-design.md
计划：docs/superpowers/plans/2026-10-03-mobile-p0-device-list-and-binding.md

Revision ID: b7c8d9e0f1a2
Revises: d5f6a7b8c9e0
"""

from alembic import op
import sqlalchemy as sa

revision = "b7c8d9e0f1a2"
down_revision = "d5f6a7b8c9e0"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "conversation",
        sa.Column(
            "desktop_device_id",
            sa.String(length=128),
            nullable=True,
            comment="会话绑定的桌面设备（desktop_device.device_id；NULL=自动解析）",
        ),
    )


def downgrade() -> None:
    op.drop_column("conversation", "desktop_device_id")
