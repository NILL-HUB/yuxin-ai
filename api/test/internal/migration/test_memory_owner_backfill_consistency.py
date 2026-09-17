"""存量回填一致性守卫（设计 §8：存量全标 owner_type='user'，行为零变化）。

在**真实数据库**上校验（无 DB 时自动跳过，不制造假绿）：
1. `user_memory` 无 `owner_type IS NULL` 行；
2. 所有存量行 `owner_type='user'` 且 `owner_account_id IS NOT NULL`；
3. `owner_type` 非 'user' 的行数为 0（本计划不写 admin 记忆）；
4. 向量分表同样已补列且存量行归属与主表一致。

第 4 条单独列出，是因为分表是**动态表名**（`user_memory_embedding_{dim}`），
迁移只能靠 `information_schema` 扫描补列——最容易被漏掉的一环；
且分表 `owner_type` 有 `NOT NULL DEFAULT 'user'`，若扫描漏表会静默
"看起来正常"，必须显式断言表与列都落地。

为什么必须在真库上跑：这些是**迁移产物**的事实，静态文件断言只能证明
DDL 文本写了什么，证明不了库里的行是否真被回填。
"""
import pytest


def _engine():
    """返回可连的同步引擎；无可用 PostgreSQL 时返回 None（调用方 skip）。"""
    from sqlalchemy import create_engine

    from config import Config

    uri = getattr(Config(), "SQLALCHEMY_DATABASE_URI", "") or ""
    if not uri.startswith("postgresql"):
        return None
    try:
        engine = create_engine(uri)
        with engine.connect():
            pass
        return engine
    except Exception:
        return None


@pytest.fixture()
def engine():
    engine = _engine()
    if engine is None:
        pytest.skip("无可用 PostgreSQL，跳过存量一致性校验")
    yield engine
    engine.dispose()


def _shard_tables(conn) -> list[str]:
    from sqlalchemy import text

    rows = conn.execute(
        text(
            "SELECT table_name FROM information_schema.tables "
            "WHERE table_schema = 'public' AND table_name LIKE 'user_memory_embedding_%'"
        )
    ).all()
    return [r[0] for r in rows]


def test_no_null_owner_type_rows(engine):
    from sqlalchemy import text

    with engine.connect() as conn:
        count = conn.execute(
            text("SELECT count(*) FROM user_memory WHERE owner_type IS NULL")
        ).scalar()
    assert count == 0, "存量回填后不应存在 owner_type 为空的行"


def test_existing_rows_are_user_scoped(engine):
    from sqlalchemy import text

    with engine.connect() as conn:
        count = conn.execute(
            text(
                "SELECT count(*) FROM user_memory "
                "WHERE owner_type = 'user' AND owner_account_id IS NOT NULL"
            )
        ).scalar()
        total = conn.execute(text("SELECT count(*) FROM user_memory")).scalar()
    assert count == total, "所有存量行都应是 user 主体且保留 owner_account_id"


def test_only_user_scoped_memory_exists(engine):
    from sqlalchemy import text

    with engine.connect() as conn:
        count = conn.execute(
            text("SELECT count(*) FROM user_memory WHERE owner_type <> 'user'")
        ).scalar()
    assert count == 0, "本计划不写入 admin 记忆，出现即说明双写逻辑越界"


def test_embedding_shards_have_owner_columns_backfilled(engine):
    """分表（动态表名）必须同样补列，且存量行归属与主表一致。

    分表列由迁移的 `information_schema` 扫描补齐；漏表时因有 `DEFAULT 'user'`
    而不会报错，故必须显式断言「表存在 → 列存在 → 无 NULL → 全为 user」。
    """
    from sqlalchemy import text

    with engine.connect() as conn:
        shards = _shard_tables(conn)
        assert shards, "未发现任何 user_memory 向量分表，无法校验分表补列"

        for table in shards:
            columns = {
                r[0]
                for r in conn.execute(
                    text(
                        "SELECT column_name FROM information_schema.columns "
                        "WHERE table_schema = 'public' AND table_name = :t"
                    ),
                    {"t": table},
                ).all()
            }
            for column in ("owner_type", "owner_admin_user_id", "owner_agent_id"):
                assert column in columns, f"{table} 缺列 {column}（迁移扫描漏表）"

            null_count = conn.execute(
                text(f"SELECT count(*) FROM {table} WHERE owner_type IS NULL")
            ).scalar()
            assert null_count == 0, f"{table} 存在 owner_type 为空的行"

            non_user = conn.execute(
                text(f"SELECT count(*) FROM {table} WHERE owner_type <> 'user'")
            ).scalar()
            assert non_user == 0, f"{table} 出现非 user 主体行"
