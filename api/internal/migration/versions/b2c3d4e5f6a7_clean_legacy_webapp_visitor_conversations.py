"""clean up legacy webapp visitor conversations

Revision ID: b2c3d4e5f6a7
Revises: 0a1b2c3d4e6f
Create Date: 2026-09-08 00:00:00.000000

WebApp（/web-apps/<token>）已改为强制登录，visitor（匿名游客）通道下线。

背景：旧实现用浏览器 localStorage 生成的 visitor_id（随机 UUID，非真实账号）
作为会话 created_by 落库；无 visitor_id 时每次请求随机 uuid4。这些"visitor 会话"
无法归属到任何真实账号（conversation.created_by 无外键、无匹配键），登录化后
将永远不可达，属脏数据。

清理范围：
- conversation.invoke_from = 'web_app' 且 created_by 不是合法 account 的行
  （含其 message、message_agent_thought，均通过 conversation_id 关联）
- 防御性：tool_confirmation.owner_account_id 非合法 account 的行
  （正常受 FK 保护不应存在，仅历史异常数据兜底）

删除顺序先子表后父表。数据清理不可逆，downgrade 为空操作。
"""
from alembic import op
import sqlalchemy as sa


revision = "b2c3d4e5f6a7"
down_revision = "0a1b2c3d4e6f"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 1) 收集 visitor 创建的 web_app 会话（created_by 不是合法 account）
    op.execute(
        sa.text(
            """
            CREATE TEMP TABLE _visitor_webapp_conversations ON COMMIT DROP AS
            SELECT c.id
            FROM conversation c
            WHERE c.invoke_from = 'web_app'
              AND c.created_by IS NOT NULL
              AND NOT EXISTS (
                  SELECT 1 FROM account a WHERE a.id = c.created_by
              )
            """
        )
    )

    # 2) message_agent_thought（通过 conversation_id 直接关联）
    op.execute(
        sa.text(
            """
            DELETE FROM message_agent_thought
            WHERE conversation_id IN (SELECT id FROM _visitor_webapp_conversations)
            """
        )
    )

    # 3) message
    op.execute(
        sa.text(
            """
            DELETE FROM message
            WHERE conversation_id IN (SELECT id FROM _visitor_webapp_conversations)
            """
        )
    )

    # 4) conversation
    op.execute(
        sa.text(
            """
            DELETE FROM conversation
            WHERE id IN (SELECT id FROM _visitor_webapp_conversations)
            """
        )
    )

    # 5) 防御性清理：tool_confirmation 中非合法账号的归属行
    #    （正常受 owner_account_id FK 保护，仅历史异常数据兜底）
    op.execute(
        sa.text(
            """
            DELETE FROM tool_confirmation
            WHERE NOT EXISTS (
                SELECT 1 FROM account a WHERE a.id = tool_confirmation.owner_account_id
            )
            """
        )
    )


def downgrade() -> None:
    # 数据清理不可逆：无法恢复已删除的 visitor 会话
    pass
