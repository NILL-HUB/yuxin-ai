"""rename assistant agent app to 小钰

Revision ID: k5f6a7b8c9d0
Revises: j4e5f6a7b8c9
Create Date: 2026-09-11 00:00:00.000000

品牌更名：钰心AI → 钰见我（品牌），助手身份 → 小钰。

assistant agent 应用同时承担两个角色：
- 会话记录里的 agent_name（展示为助手身份）；
- assistant_agent_resolver 按 app.name 查询的**权威解析键**。

因此 app 表中历史名为「钰心AI / 钰见我」的 assistant agent 记录必须同步改名为
「小钰」，否则按名解析会在改名后失败（生产环境依赖 DB 名称解析；本地可能仅靠
环境变量 ASSISTANT_AGENT_ID 兜底，不受影响）。

幂等：仅当不存在同名「小钰」记录时才更新，避免唯一约束冲突。
"""
from alembic import op
import sqlalchemy as sa

revision = "k5f6a7b8c9d0"
down_revision = "j4e5f6a7b8c9"
branch_labels = None
depends_on = None

OLD_NAMES = ("钰心AI", "钰见我")
NEW_NAME = "小钰"


def upgrade():
    conn = op.get_bind()
    exists = conn.execute(
        sa.text("SELECT COUNT(*) FROM app WHERE name = :name"), {"name": NEW_NAME}
    ).scalar()
    if exists:
        return
    conn.execute(
        sa.text(
            "UPDATE app SET name = :new_name "
            "WHERE name = ANY(:old_names) "
            "AND id = (SELECT id FROM app WHERE name = ANY(:old_names) ORDER BY created_at ASC LIMIT 1)"
        ),
        {"new_name": NEW_NAME, "old_names": list(OLD_NAMES)},
    )


def downgrade():
    conn = op.get_bind()
    conn.execute(
        sa.text("UPDATE app SET name = :old_name WHERE name = :new_name"),
        {"old_name": OLD_NAMES[0], "new_name": NEW_NAME},
    )
