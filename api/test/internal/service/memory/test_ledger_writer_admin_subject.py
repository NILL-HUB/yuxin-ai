"""写入侧 admin 主体判别性用例（ADMIN-P3c-1）。

不变量：
1. admin 主体必须能写入 PG 投影行（owner_account_id 为 NULL，admin_user 列有值）；
2. admin 主体写入的 Neo4j 归属属性必须是 admin_user_id（+ agent_id），**不含 user_id**；
3. 用户主体行为与改造前逐字节等价（owner_account_id 有值、user_id 属性）；
4. 主体无法解析（非 UUID 的 user_id）仍跳过，不抛错。

判别性说明：用例 1 在改造前**必失败**——`_upsert_vector` 把「owner_account_id
为空」当作「主体非法」而跳过写入。改造后跳过条件改为「主体无法解析」。
"""
from uuid import UUID, uuid4

import pytest

from internal.entity.memory_owner_entity import (
    NEO4J_ADMIN_LEVEL_AGENT_SENTINEL,
    MemoryOwnerKey,
)
from internal.service.memory.ledger_writer import LedgerWriter


class _FakeResult:
    def __init__(self, rows, rowcount=1):
        self._rows = rows
        # UPDATE/DELETE 路径读 rowcount（invalidate_agent_curated 依赖它判断是否有权限）
        self.rowcount = rowcount

    def first(self):
        return self._rows[0] if self._rows else None

    def all(self):
        return list(self._rows)

    def __iter__(self):
        return iter(self._rows)


class _FakeSession:
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
    def resolve_system_default_dimension(self):
        return 1536

    def ensure_tables_for_dimension(self, dimension):
        return True

    def get_user_memory_table_name(self, dimension):
        return f"user_memory_embedding_{dimension}"


def _wire(monkeypatch):
    from internal.service.embedding_table_router import EmbeddingTableRouter

    monkeypatch.setattr(
        EmbeddingTableRouter, "get_instance", staticmethod(lambda db=None: _StubRouter())
    )
    db = _FakeDB()
    db.session.select_results["SELECT id FROM user_memory"] = []
    db.session.select_results["SELECT tablename FROM pg_tables"] = []
    return db


def test_admin_owner_writes_projection_row(monkeypatch):
    """admin 主体：投影行必须落库（此前会被跳过）。"""
    db = _wire(monkeypatch)
    writer = LedgerWriter(db=db)
    admin_id, agent_id = uuid4(), uuid4()
    node_id = str(uuid4())

    memory_id = writer._upsert_vector(
        point_id=node_id,
        vector=[0.1] * 8,
        payload={"content": "管理员记忆", "event_type": "episode"},
        owner_key=MemoryOwnerKey.for_admin(admin_id, agent_id=agent_id),
    )

    assert memory_id is not None, "admin 主体不得被跳过"
    assert len(db.session.added) == 1
    added = db.session.added[0]
    assert added.owner_type == "admin"
    assert added.owner_account_id is None
    assert added.owner_admin_user_id == admin_id
    assert added.owner_agent_id == agent_id

    insert_execs = [
        (sql, params)
        for sql, params in db.session.executed
        if "INSERT INTO user_memory_embedding_" in sql
    ]
    assert len(insert_execs) == 1
    insert_params = insert_execs[0][1]
    assert insert_params["owner_id"] is None, "admin 主体的 owner_account_id 绑定必须为 None"
    assert insert_params["owner_type"] == "admin"
    assert insert_params["owner_admin_user_id"] == admin_id
    assert insert_params["owner_agent_id"] == agent_id


def test_admin_level_owner_writes_null_agent_column(monkeypatch):
    """管理员级（无 agent）：PG 的 agent 列仍为 NULL（哨兵只用于 Neo4j）。"""
    db = _wire(monkeypatch)
    writer = LedgerWriter(db=db)
    admin_id = uuid4()

    memory_id = writer._upsert_vector(
        point_id=str(uuid4()),
        vector=[0.1] * 8,
        payload={"content": "管理员级", "event_type": "episode"},
        owner_key=MemoryOwnerKey.for_admin(admin_id),
    )

    assert memory_id is not None
    added = db.session.added[0]
    assert added.owner_admin_user_id == admin_id
    assert added.owner_agent_id is None


def test_user_owner_still_writes_account_column(monkeypatch):
    db = _wire(monkeypatch)
    writer = LedgerWriter(db=db)
    account_id = uuid4()

    memory_id = writer._upsert_vector(
        point_id=str(uuid4()),
        vector=[0.1] * 8,
        payload={"content": "用户记忆", "user_id": str(account_id), "event_type": "episode"},
    )

    assert memory_id is not None
    added = db.session.added[0]
    assert added.owner_type == "user"
    assert added.owner_account_id == account_id
    assert isinstance(added.owner_account_id, UUID)


def test_unparsable_user_id_still_skipped(monkeypatch):
    """非 UUID 的 user_id（历史脏值）无法解析主体 → 跳过不抛。"""
    db = _wire(monkeypatch)
    writer = LedgerWriter(db=db)

    memory_id = writer._upsert_vector(
        point_id=str(uuid4()),
        vector=[0.1] * 8,
        payload={"content": "x", "user_id": "platform", "event_type": "episode"},
    )

    assert memory_id is None
    assert db.session.added == []
