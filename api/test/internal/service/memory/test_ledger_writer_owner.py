"""写入侧主体双写测试（设计 §8：先双写，读路径不变）。

不变量：
1. 用户主体路径写入的三新列必须与旧 `owner_account_id` **一致**（owner_type='user'）；
2. 旧列仍照写（读路径零变化的前提）；
3. 无法解析主体时**不写**且不抛（与既有 `UUID(str(...))` 失败即跳过的行为一致）。

前 4 个用例是主体键 → 列值的纯函数映射契约；后 2 个用例真正覆盖
`LedgerWriter._upsert_vector` 的写库分支（用替身 db/session 与替身 router），
断言新建 `UserMemory(...)` 时三新列确实被写入——纯函数测试无法证明这一点。
"""
from uuid import UUID, uuid4

import pytest

from internal.entity.memory_owner_entity import MemoryOwnerKey
from internal.service.memory.ledger_writer import LedgerWriter


def test_user_owner_writes_matching_new_columns():
    account_id = uuid4()
    key = MemoryOwnerKey.for_user(account_id)

    kwargs = key.pg_kwargs()

    assert kwargs["owner_type"] == "user"
    assert kwargs["owner_account_id"] == account_id
    assert kwargs["owner_admin_user_id"] is None
    assert kwargs["owner_agent_id"] is None


def test_admin_owner_keeps_account_column_empty():
    admin_id, agent_id = uuid4(), uuid4()
    key = MemoryOwnerKey.for_admin(admin_id, agent_id=agent_id)

    kwargs = key.pg_kwargs()

    assert kwargs["owner_type"] == "admin"
    assert kwargs["owner_account_id"] is None
    assert kwargs["owner_admin_user_id"] == admin_id
    assert kwargs["owner_agent_id"] == agent_id


def test_resolve_owner_key_from_legacy_user_id():
    """系统路径从 `event.user_id`（str）还原主体键。"""
    account_id = uuid4()

    key = MemoryOwnerKey.from_legacy_user_id(str(account_id))

    assert key.owner_account_id == account_id
    assert key.to_key() == str(account_id)


def test_resolve_owner_key_rejects_non_uuid():
    from internal.entity.memory_owner_entity import MemoryOwnerKeyError

    with pytest.raises(MemoryOwnerKeyError):
        MemoryOwnerKey.from_legacy_user_id("platform")


# =========================================================
# 替身：db/session（可编程 execute 结果）+ 向量路由
# =========================================================


class _FakeResult:
    def __init__(self, rows):
        self._rows = rows

    def first(self):
        return self._rows[0] if self._rows else None

    def all(self):
        return list(self._rows)

    def __iter__(self):
        return iter(self._rows)


class _FakeSession:
    """记录 add/execute/commit，并按 sql 片段返回可编程结果。"""

    def __init__(self):
        self.added = []
        self.executed = []
        self.committed = 0
        self.rolled_back = 0
        self.flushed = 0
        self.select_results = {}

    def execute(self, sql, params=None):
        sql_str = str(sql)
        self.executed.append((sql_str, params))
        for frag, rows in self.select_results.items():
            if frag in sql_str:
                return _FakeResult(rows)
        return _FakeResult([])

    def add(self, obj):
        self.added.append(obj)

    def flush(self):
        self.flushed += 1

    def commit(self):
        self.committed += 1

    def rollback(self):
        self.rolled_back += 1


class _FakeDB:
    def __init__(self):
        self.session = _FakeSession()


class _StubRouter:
    """替身向量路由：固定维度、建表必成功。"""

    def resolve_system_default_dimension(self):
        return 1536

    def ensure_tables_for_dimension(self, dimension):
        return True

    def get_user_memory_table_name(self, dimension):
        return f"user_memory_embedding_{dimension}"


def _patch_router(monkeypatch):
    from internal.service.embedding_table_router import EmbeddingTableRouter

    monkeypatch.setattr(
        EmbeddingTableRouter, "get_instance", staticmethod(lambda db=None: _StubRouter())
    )


def _make_db():
    db = _FakeDB()
    # 无已有投影行 → 走新建分支；无其它维度分表残留
    db.session.select_results["SELECT id FROM user_memory"] = []
    db.session.select_results["SELECT tablename FROM pg_tables"] = []
    return db


# =========================================================
# 真实写库分支：三新列必须被写入，旧列保留
# =========================================================


def test_upsert_vector_writes_owner_type_columns(monkeypatch):
    """新建投影行时三新列与旧 owner_account_id 双写（用户主体）。"""
    _patch_router(monkeypatch)
    db = _make_db()
    writer = LedgerWriter(db=db)
    account_id = uuid4()
    node_id = str(uuid4())

    memory_id = writer._upsert_vector(
        point_id=node_id,
        vector=[0.1] * 8,
        payload={"content": "内容", "user_id": str(account_id), "event_type": "episode"},
    )

    assert memory_id is not None
    assert len(db.session.added) == 1
    added = db.session.added[0]
    # 三新列
    assert added.owner_type == "user"
    assert added.owner_admin_user_id is None
    assert added.owner_agent_id is None
    # 旧列保留原值（双写，不替换），且是 UUID 实例而非字符串
    assert added.owner_account_id == account_id
    assert isinstance(added.owner_account_id, UUID)
    # 向量分表写入照旧
    assert any("INSERT INTO user_memory_embedding_" in e[0] for e in db.session.executed)
    assert db.session.committed >= 1
    # 分表 INSERT 同样必须双写三新列（列已在 Task 2 建好，写入端必须消费，
    # 否则 `owner_admin_user_id` / `owner_agent_id` 永远是 NULL，
    # `owner_type` 只是靠 DEFAULT 'user' 侥幸正确 —— 属"只建列不写列"断链）
    insert_execs = [
        (sql, params)
        for sql, params in db.session.executed
        if "INSERT INTO user_memory_embedding_" in sql
    ]
    assert len(insert_execs) == 1
    insert_sql, insert_params = insert_execs[0]
    for column in ("owner_type", "owner_admin_user_id", "owner_agent_id"):
        assert column in insert_sql, f"分表 INSERT 缺列 {column}"
        # ON CONFLICT 分支也要同步归属列，命中时不至于留下旧归属
        assert f"{column} = EXCLUDED.{column}" in insert_sql, (
            f"分表 ON CONFLICT 未同步列 {column}"
        )
    assert insert_params["owner_type"] == "user"
    assert insert_params["owner_admin_user_id"] is None
    assert insert_params["owner_agent_id"] is None
    assert insert_params["owner_id"] == str(account_id)


def test_upsert_vector_skips_write_when_owner_unparsable(monkeypatch):
    """主体无法解析（如历史 'platform'）→ 不写任何行且不抛错。"""
    _patch_router(monkeypatch)
    db = _make_db()
    writer = LedgerWriter(db=db)

    memory_id = writer._upsert_vector(
        point_id=str(uuid4()),
        vector=[0.1] * 8,
        payload={"content": "内容", "user_id": "platform", "event_type": "episode"},
    )

    assert memory_id is None
    assert db.session.added == []
    assert not any("INSERT INTO user_memory_embedding_" in e[0] for e in db.session.executed)
    assert db.session.committed == 0
