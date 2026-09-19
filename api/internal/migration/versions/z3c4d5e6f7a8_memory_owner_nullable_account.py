"""make memory owner account column nullable for admin/agent subjects

设计依据：docs/superpowers/specs/2026-09-15-admin-agent-governance-design.md §8。

P3b（y2b3c4d5e6f8）已补 owner_type/owner_admin_user_id/owner_agent_id，读路径按主体过滤；
但写入侧仍被 ``owner_account_id NOT NULL`` 阻塞——admin / Agent 主体该列恒为 NULL，
``LedgerWriter._upsert_vector`` 因此在 account 为空时主动跳过 pgvector 写入，
形成「图节点已建、投影行缺失」的键值互补破坏。

本迁移解除该阻塞，并把约束语义从「列级非空」升级为「按主体类型非空」：

    owner_type='user'  ⇒ owner_account_id      IS NOT NULL
    owner_type='admin' ⇒ owner_admin_user_id   IS NOT NULL

向量分表 ``user_memory_embedding_{dim}`` 按维度动态建表，故同样用 information_schema 扫描；
新建分表由 EmbeddingTableRouter 的 DDL 直接带 CHECK（ADMIN-P3c-1 Task 2）。

Revision ID: z3c4d5e6f7a8
Revises: y2b3c4d5e6f8
"""
from alembic import op
import sqlalchemy as sa

revision = "z3c4d5e6f7a8"
down_revision = "y2b3c4d5e6f8"
branch_labels = None
depends_on = None

_USER_MEMORY_EMBEDDING_PREFIX = "user_memory_embedding_"


def _check_name(table: str) -> str:
    return f"ck_{table}_owner_subject"


def _add_subject_check(table: str) -> None:
    op.execute(
        f"ALTER TABLE {table} ADD CONSTRAINT {_check_name(table)} CHECK ("
        "    (owner_type = 'user' AND owner_account_id IS NOT NULL)"
        " OR (owner_type = 'admin' AND owner_admin_user_id IS NOT NULL)"
        ")"
    )


def _drop_subject_check(table: str) -> None:
    op.execute(f"ALTER TABLE {table} DROP CONSTRAINT IF EXISTS {_check_name(table)}")


def _embedding_tables(bind) -> list[str]:
    rows = bind.execute(
        sa.text(
            "SELECT table_name FROM information_schema.tables "
            "WHERE table_schema = 'public' AND table_name LIKE :prefix"
        ),
        {"prefix": f"{_USER_MEMORY_EMBEDDING_PREFIX}%"},
    ).fetchall()
    return [name for (name,) in rows]


def upgrade():
    # 1) 主表：解非空 + 补按主体类型非空
    op.execute("ALTER TABLE user_memory ALTER COLUMN owner_account_id DROP NOT NULL")
    _drop_subject_check("user_memory")
    _add_subject_check("user_memory")

    # 2) 已存在的向量分表同法（动态表名，故用扫描）
    bind = op.get_bind()
    for table_name in _embedding_tables(bind):
        op.execute(
            f"ALTER TABLE {table_name} ALTER COLUMN owner_account_id DROP NOT NULL"
        )
        _drop_subject_check(table_name)
        _add_subject_check(table_name)


def downgrade():
    # 回退到「列级非空」前必须先确认不存在 admin/Agent 主体行——
    # 否则 SET NOT NULL 会失败，且即便强删也会丢归属语义；此处显式拒绝而非静默删数据。
    # 主表与全部分表都要查：任一表存在 admin 行即拒绝，避免分表落到裸 PG 报错。
    bind = op.get_bind()
    shard_tables = _embedding_tables(bind)
    admin_rows = bind.execute(
        sa.text("SELECT count(*) FROM user_memory WHERE owner_type = 'admin'")
    ).scalar()
    for table_name in shard_tables:
        admin_rows += bind.execute(
            sa.text(f"SELECT count(*) FROM {table_name} WHERE owner_type = 'admin'")
        ).scalar()
    if admin_rows:
        raise RuntimeError(
            f"存在 {admin_rows} 行 owner_type='admin' 的记忆，无法回退 owner_account_id NOT NULL"
        )

    for table_name in shard_tables:
        _drop_subject_check(table_name)
        op.execute(
            f"ALTER TABLE {table_name} ALTER COLUMN owner_account_id SET NOT NULL"
        )

    _drop_subject_check("user_memory")
    op.execute("ALTER TABLE user_memory ALTER COLUMN owner_account_id SET NOT NULL")
