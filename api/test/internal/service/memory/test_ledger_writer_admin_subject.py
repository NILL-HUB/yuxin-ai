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


# =========================================================
# Neo4j 写路径主体化（episode / entity / access / cooccur）
# =========================================================


class _CapturingSession:
    def __init__(self, sink):
        self._sink = sink

    def run(self, cypher, params=None, **kwargs):
        self._sink.append((cypher, params if params is not None else kwargs))
        return self

    def single(self):
        return None

    def consume(self):
        return self

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class _CapturingDriver:
    def __init__(self):
        self.calls = []

    def session(self):
        return _CapturingSession(self.calls)


def _writer_with_driver(monkeypatch, driver=None):
    """返回 (writer, driver)；driver 必须是**同一个实例**被反复返回——
    否则被测代码里的 ``self._get_driver()`` 会拿到新实例，断言看不到任何调用。"""
    db = _wire(monkeypatch)
    writer = LedgerWriter(db=db)
    stable = driver or _CapturingDriver()
    monkeypatch.setattr(writer, "_get_driver", lambda: stable)
    return writer, stable


def _event(user_id="acc-raw"):
    from internal.model.memory_models import EventSource, MemoryEvent

    return MemoryEvent(content="内容", source=EventSource.USER_MESSAGE, user_id=user_id)


def test_episode_node_user_owner_keeps_user_id_prop(monkeypatch):
    """用户态逐字节等价：属性名仍是 user_id，值仍是原始字符串。"""
    from datetime import UTC, datetime

    writer, driver = _writer_with_driver(monkeypatch)
    writer._create_episode_node(driver, _event(), datetime.now(UTC))

    cypher, params = driver.calls[0]
    assert "SET e += $owner_props" in cypher
    assert params["owner_props"] == {"user_id": "acc-raw"}
    assert "user_id: $user_id" not in cypher, "归属改由 owner_props 注入"


def test_episode_node_admin_owner_writes_admin_props(monkeypatch):
    from datetime import UTC, datetime

    writer, driver = _writer_with_driver(monkeypatch)
    admin_id, agent_id = uuid4(), uuid4()
    writer._create_episode_node(
        driver, _event("ignored"), datetime.now(UTC),
        owner=MemoryOwnerKey.for_admin(admin_id, agent_id=agent_id),
    )

    _cypher, params = driver.calls[0]
    props = params["owner_props"]
    assert props["admin_user_id"] == str(admin_id)
    assert props["agent_id"] == str(agent_id)
    assert "user_id" not in props, "admin 节点不得带 user_id（属性分离）"


def test_merge_entity_pattern_includes_owner(monkeypatch):
    """MERGE 键必须含归属，否则不同主体同名实体被合并（跨主体污染）。"""
    from datetime import UTC, datetime

    writer, driver = _writer_with_driver(monkeypatch)
    admin_id = uuid4()
    writer._merge_entity_node(
        driver, {"name": "实体", "type": "t", "summary": ""}, datetime.now(UTC),
        owner=MemoryOwnerKey.for_admin(admin_id),
    )

    cypher, params = driver.calls[0]
    assert "MERGE (e:Entity:MemoryNode {name: $name" in cypher
    assert "admin_user_id: $admin_user_id" in cypher
    assert "agent_id: $agent_id" in cypher
    assert params["admin_user_id"] == str(admin_id)
    assert params["agent_id"] == NEO4J_ADMIN_LEVEL_AGENT_SENTINEL
    assert "user_id" not in params


def test_merge_entity_user_owner_keeps_user_pattern(monkeypatch):
    from datetime import UTC, datetime

    writer, driver = _writer_with_driver(monkeypatch)
    writer._merge_entity_node(
        driver, {"name": "实体", "type": "t", "summary": ""}, datetime.now(UTC),
        fallback_user_id="acc-raw",
    )

    cypher, params = driver.calls[0]
    assert "user_id: $user_id" in cypher
    assert params["user_id"] == "acc-raw"


def test_increment_entity_access_admin_owner(monkeypatch):
    from datetime import UTC, datetime

    writer, driver = _writer_with_driver(monkeypatch)
    admin_id = uuid4()
    writer._increment_entity_access(
        driver, "实体", datetime.now(UTC),
        owner=MemoryOwnerKey.for_admin(admin_id),
    )

    cypher, params = driver.calls[0]
    assert "MATCH (e:Entity {name: $name" in cypher
    assert "admin_user_id: $admin_user_id" in cypher
    assert params["admin_user_id"] == str(admin_id)


def test_increment_cooccurrence_admin_scopes_both_ends(monkeypatch):
    from datetime import UTC, datetime

    writer, driver = _writer_with_driver(monkeypatch)
    admin_id = uuid4()
    writer._increment_cooccurrence(
        driver, "甲", "乙", datetime.now(UTC),
        owner=MemoryOwnerKey.for_admin(admin_id),
    )

    cypher, params = driver.calls[0]
    # 两个端点（a/b）都必须受主体约束——任一漏掉都会跨主体匹配
    assert cypher.count("admin_user_id: $admin_user_id") == 2
    assert cypher.count("agent_id: $agent_id") == 2
    assert "user_id" not in params
    assert params["admin_user_id"] == str(admin_id)


def test_write_full_path_admin_writes_admin_nodes(monkeypatch):
    """端到端：write_full_path 传 admin 主体键时，Episode/Entity 都落 admin 归属。"""
    writer, driver = _writer_with_driver(monkeypatch)
    admin_id = uuid4()

    writer._write_full_path_impl(
        event=_event("ignored"),
        entities=[{"name": "E1", "type": "t", "summary": ""}],
        relations=[],
        embedding=[0.1] * 8,
        owner_key=MemoryOwnerKey.for_admin(admin_id),
    )

    episode_calls = [c for c in driver.calls if "Episode:MemoryNode" in c[0]]
    assert episode_calls, "应写 Episode 节点"
    assert episode_calls[0][1]["owner_props"]["admin_user_id"] == str(admin_id)
    entity_calls = [c for c in driver.calls if "Entity:MemoryNode" in c[0]]
    assert entity_calls, "应写 Entity 节点"
    assert entity_calls[0][1]["admin_user_id"] == str(admin_id)
    assert "user_id" not in entity_calls[0][1]


def test_write_full_path_user_owner_keeps_user_id(monkeypatch):
    """用户态：不传主体键时，归属仍是 event.user_id（零变化）。"""
    writer, driver = _writer_with_driver(monkeypatch)

    writer._write_full_path_impl(
        event=_event("acc-raw"),
        entities=[{"name": "E1", "type": "t", "summary": ""}],
        relations=[],
        embedding=[0.1] * 8,
    )

    episode_calls = [c for c in driver.calls if "Episode:MemoryNode" in c[0]]
    assert episode_calls[0][1]["owner_props"] == {"user_id": "acc-raw"}
