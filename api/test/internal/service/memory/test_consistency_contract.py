"""键值互补一致性契约测试（第 1~3 步收敛方案）。

覆盖:
    1. FULL/SUMMARY 图节点未创建（Neo4j 不可用）时不再写 PG 投影行
       → 根治 A 类悬空投影孤儿（embedding_node_id 指向不存在图节点）
    2. _upsert_vector 按 embedding_node_id 幂等 upsert
       → 同一 node_id 至多一条投影行（同生同灭）
    3. _delete_pgvector_row 优先按 embedding_node_id 匹配
       → 治理层（memory_id=图节点 id）能真正删掉系统路径投影行
    4. ConflictResolver _deactivate_projection_row 图失效 → 投影行置非 active
       → 被取代/废弃记忆不再被向量召回

设计说明:
    使用可编程 fake（而非 MagicMock 链），精确控制 execute/first 返回值，
    使断言能覆盖真实数据流分支。
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import pytest

from internal.model.memory_models import EventSource, MemoryEvent
from internal.service.memory.ledger_writer import LedgerWriter
from internal.service.memory.memory_governor import MemoryGovernor
from internal.service.memory.write_time_conflict_resolver import WriteTimeConflictResolver


# =========================================================
# 可编程 Fake（避免 MagicMock 链的脆弱断言）
# =========================================================


class FakeSession:
    """记录 execute/commit/rollback/add/flush 调用的 fake session。"""

    def __init__(self):
        self.executed = []          # 每次 execute 的 (sql, params)
        self.committed = 0
        self.rolled_back = 0
        self.added = []
        self.flushed = 0
        # 可编程查询结果：按 sql 片段匹配 -> 返回值列表（每元素是 (id,) 或 row）
        self.select_results = {}    # dict[str, list]
        self.update_rowcount = 1
        self._deleted_ids = []

    def execute(self, sql, params=None):
        from sqlalchemy import text

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

    def delete(self, obj):
        self._deleted_ids.append(getattr(obj, "id", None))

    def query(self, *args, **kwargs):  # pragma: no cover - 仅兼容
        raise NotImplementedError("本 fake 仅覆盖 execute 风格的调用")


class _FakeResult:
    """模拟 SQLAlchemy Result：.first() / .all() / 迭代。"""

    def __init__(self, rows):
        self._rows = rows

    def first(self):
        return self._rows[0] if self._rows else None

    def all(self):
        return list(self._rows)

    def __iter__(self):
        return iter(self._rows)


class FakeDB:
    def __init__(self):
        self.session = FakeSession()


def _make_event(user_id: str, content: str = "测试内容") -> MemoryEvent:
    return MemoryEvent(
        event_id=uuid4(),
        timestamp=datetime.now(UTC),
        source=EventSource.USER_MESSAGE,
        content=content,
        context_messages=[],
        metadata={},
        user_id=user_id,
    )


# =========================================================
# 1. 图节点未创建 → 不写投影行（A 类根治）
# =========================================================


class TestWriteSkipsProjectionWhenGraphMissing:
    def test_full_path_neo4j_unavailable_no_pg_row(self):
        """Neo4j 不可用时 FULL 不再写 PG 投影（旧行为会用 uuid4 兜底写）。"""
        db = FakeDB()
        writer = LedgerWriter(db=db)
        event = _make_event(str(uuid4()))

        # 模拟 Neo4j 驱动不可用
        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(writer, "_get_driver", lambda: None)
            result = writer.write_full_path(
                event=event,
                entities=[],
                relations=[],
                embedding=[0.1] * 16,
            )

        assert result["episode_node_id"] is None
        assert result["vector_id"] is None
        assert result["write_compensated"] is True
        assert result.get("error") == "neo4j_unavailable"
        # 关键断言：没有任何 INSERT/ADD 到 user_memory 的投影写入
        assert db.session.added == []
        # _upsert_vector 不应被调用（没有 execute user_memory 相关）
        assert not any("user_memory" in e[0] for e in db.session.executed)

    def test_summary_path_neo4j_unavailable_no_pg_row(self):
        """Neo4j 不可用时 SUMMARY 不再写 PG 投影。"""
        db = FakeDB()
        writer = LedgerWriter(db=db)
        event = _make_event(str(uuid4()))

        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(writer, "_get_driver", lambda: None)
            result = writer.write_summary_path(
                event=event,
                summary="摘要内容",
                entities=[],
                relations=[],
                embedding=[0.1] * 16,
            )

        assert result["episode_node_id"] is None
        assert result["vector_id"] is None
        assert result["write_compensated"] is True
        assert db.session.added == []


# =========================================================
# 2. _upsert_vector 按 embedding_node_id 幂等
# =========================================================


class TestUpsertVectorIdempotent:
    def test_new_node_id_creates_projection_row(self):
        """首次写入（无已有投影行）→ 新建 user_memory 行 + 写向量分表。"""
        db = FakeDB()
        # SELECT id FROM user_memory WHERE embedding_node_id=... → 无结果（新建）
        db.session.select_results["SELECT id FROM user_memory"] = []
        # SELECT tablename FROM pg_tables → 无其它分表残留
        db.session.select_results["SELECT tablename FROM pg_tables"] = []
        writer = LedgerWriter(db=db)
        user_id = str(uuid4())
        node_id = str(uuid4())

        mid = writer._upsert_vector(
            point_id=node_id,
            vector=[0.1] * 16,
            payload={"content": "内容", "user_id": user_id, "event_type": "episode"},
        )

        assert mid is not None
        # 系统路径不传 forced_memory_id：新建行 id 是独立 uuid，
        # 但 embedding_node_id 必须等于 point_id（图节点 id）
        assert mid != node_id
        # 新建分支走 add（UserMemory 实例）
        assert len(db.session.added) == 1
        added = db.session.added[0]
        assert added.embedding_node_id == node_id
        assert str(added.id) == mid
        assert added.created_from == "memory_system"
        # 至少有一次向量分表 INSERT
        assert any("INSERT INTO user_memory_embedding_" in e[0] for e in db.session.executed)
        assert db.session.committed >= 1

    def test_existing_node_id_reuses_row(self):
        """同一 node_id 已存在投影行 → 复用行（UPDATE 分支），不新增行。"""
        db = FakeDB()
        existing_id = str(uuid4())
        # 按 embedding_node_id 查到已有行
        db.session.select_results["SELECT id FROM user_memory"] = [(existing_id,)]
        db.session.select_results["SELECT tablename FROM pg_tables"] = []
        writer = LedgerWriter(db=db)
        user_id = str(uuid4())
        node_id = existing_id

        mid = writer._upsert_vector(
            point_id=node_id,
            vector=[0.2] * 16,
            payload={"content": "新内容", "user_id": user_id, "event_type": "episode"},
        )

        assert mid == existing_id  # 复用已有 id，不生成新 uuid
        # UPDATE 分支 → 不 add 新 UserMemory 行
        assert db.session.added == []
        # 执行过 UPDATE user_memory
        assert any("UPDATE user_memory" in e[0] for e in db.session.executed)

    def test_agent_curated_forced_memory_id(self):
        """agent_curated 传 forced_memory_id → 新建行 id 等于图节点 id。"""
        db = FakeDB()
        db.session.select_results["SELECT id FROM user_memory"] = []
        db.session.select_results["SELECT tablename FROM pg_tables"] = []
        writer = LedgerWriter(db=db)
        user_id = str(uuid4())
        graph_node_id = str(uuid4())  # 图节点 node_id（agent_curated 预生成）

        mid = writer._upsert_vector(
            point_id=graph_node_id,
            vector=[0.3] * 16,
            payload={
                "content": "用户偏好",
                "user_id": user_id,
                "event_type": "preference",
                "created_from": "agent_curated",
            },
            forced_memory_id=graph_node_id,
        )

        assert mid == graph_node_id
        added = db.session.added[0]
        assert str(added.id) == graph_node_id
        assert added.created_from == "agent_curated"

    def test_point_id_empty_skips_write(self):
        """point_id 为空（图节点未创建）→ 跳过写入，不产生悬空投影。"""
        db = FakeDB()
        writer = LedgerWriter(db=db)
        mid = writer._upsert_vector(
            point_id="",
            vector=[0.1] * 16,
            payload={"content": "x", "user_id": str(uuid4())},
        )
        assert mid is None
        assert db.session.added == []
        assert db.session.executed == []

    def test_forced_id_falls_back_to_legacy_row_by_id(self):
        """旧版 agent_curated 半条（id==node_id 但 embedding_node_id 空）→
        按 id 回退命中并复用，UPDATE 补齐 embedding_node_id。"""
        db = FakeDB()
        graph_node_id = str(uuid4())
        # 第一次查 embedding_node_id 无结果；第二次按 id 查到旧行
        db.session.select_results["WHERE embedding_node_id = :node_id"] = []
        db.session.select_results["WHERE id = :mid AND created_from"] = [
            (graph_node_id,)
        ]
        db.session.select_results["SELECT tablename FROM pg_tables"] = []
        writer = LedgerWriter(db=db)
        user_id = str(uuid4())

        mid = writer._upsert_vector(
            point_id=graph_node_id,
            vector=[0.4] * 16,
            payload={
                "content": "用户喜欢简洁",
                "user_id": user_id,
                "event_type": "preference",
                "created_from": "agent_curated",
            },
            forced_memory_id=graph_node_id,
        )

        assert mid == graph_node_id
        # 走 UPDATE 分支（不新增行），且 UPDATE 带 embedding_node_id 补齐
        assert db.session.added == []
        assert any(
            "UPDATE user_memory" in e[0] and "embedding_node_id = :node_id" in e[0]
            for e in db.session.executed
        )

    def test_rebuild_payload_maps_graph_node(self):
        """图节点属性 → _upsert_vector payload 映射（自愈重建用）。"""
        from internal.migration.memory_self_heal import _build_payload

        node = {
            "node_id": "abc-123",
            "user_id": "u-1",
            "content": "用户偏好简洁回答",
            "memory_type": "preference",
            "source": "agent_curated",
            "session_id": "sess-1",
        }
        payload = _build_payload(node)
        assert payload["content"] == "用户偏好简洁回答"
        assert payload["created_from"] == "agent_curated"
        assert payload["event_type"] == "preference"
        assert payload["node_id"] == "abc-123"
        assert payload["user_id"] == "u-1"

        # 非 agent_curated 来源 → memory_system
        node2 = {**node, "source": "user_message"}
        assert _build_payload(node2)["created_from"] == "memory_system"


# =========================================================
# 3. MemoryGovernor 按 embedding_node_id 联动删除
# =========================================================


class TestGovernorDeleteProjection:
    def test_delete_pgvector_row_matches_embedding_node_id(self):
        """memory_id 是图节点 id 时，应命中 embedding_node_id 对应的投影行并删除。"""
        db = FakeDB()
        governor = MemoryGovernor(db=db)
        graph_node_id = str(uuid4())
        existing = type("Row", (), {"id": str(uuid4())})()

        # 模拟 _get_db 返回 fake db，query 链返回该行
        class _Q2:
            def filter(self, *a, **k):
                return self
            def first(self):
                return existing
        db.session.query = lambda *a, **k: _Q2()

        governor._delete_pgvector_row(graph_node_id)

        # fake session.delete 记录 obj.id → 应等于该行的 id
        assert existing.id in db.session._deleted_ids
        assert db.session.committed >= 1

    def test_delete_pgvector_row_falls_back_to_id(self):
        """embedding_node_id 未命中时，回退按主键 id 匹配（agent_curated 同 id 场景）。"""
        db = FakeDB()
        governor = MemoryGovernor(db=db)
        memory_id = str(uuid4())
        existing = type("Row", (), {"id": memory_id})()
        state = {"n": 0}

        class _QS:
            def filter(self, *a, **k):
                return self
            def first(self):
                state["n"] += 1
                if state["n"] == 1:
                    return None  # embedding_node_id 未命中
                return existing  # 回退按 id 命中

        db.session.query = lambda *a, **k: _QS()

        governor._delete_pgvector_row(memory_id)

        assert existing.id in db.session._deleted_ids
        assert db.session.committed >= 1


# =========================================================
# 4. ConflictResolver 投影行联动失效
# =========================================================


class TestConflictDeactivateProjection:
    def test_deactivate_projection_row_sets_deprecated(self):
        """图节点被 supersede → 投影行置 non-active，不再被向量召回。"""
        from test.context import TestApp

        db = FakeDB()
        app = TestApp(__name__)
        app.extensions["database"] = db

        resolver = WriteTimeConflictResolver.__new__(WriteTimeConflictResolver)

        with app.app_context():
            resolver._deactivate_projection_row("node-123")

        # 应执行 UPDATE user_memory ... status='deprecated'
        assert any("UPDATE user_memory" in e[0] and "deprecated" in e[0] for e in db.session.executed)
        assert db.session.committed >= 1


# =========================================================
# 5. 幽灵用户清理（自愈式对账的"不可重建即删除"分支）
# =========================================================


class TestGhostCleanup:
    def test_load_ghost_nodes_queries_private_labels_only(self):
        """幽灵盘点扫描全部用户记忆标签（含 Skill 用于完整报告）。

        注意：盘点阶段含 Skill 是为了完整统计幽灵残留；Skill 的删除
        在 _purge_ghost_nodes 中被排除（Skill 按全局 id MERGE 可能共享）。
        """
        from internal.migration import memory_self_heal

        captured = {}

        class _FakeRec:
            def __init__(self, uid, labels, cnt):
                self._uid, self._labels, self._cnt = uid, labels, cnt
            def __getitem__(self, k):
                return {"uid": self._uid, "labels": self._labels, "cnt": self._cnt}[k]

        class _FakeResult:
            def __iter__(self):
                return iter([
                    _FakeRec("ghost-1", ["Episode", "MemoryNode"], 3),
                    _FakeRec("ghost-2", ["Entity", "MemoryNode"], 1),
                ])

        class _FakeSession:
            def run(self, cypher, **params):
                captured["cypher"] = cypher
                captured["valid"] = params.get("valid")
                return _FakeResult()
            def __enter__(self):
                return self
            def __exit__(self, *a):
                return False

        class _FakeDriver:
            def session(self):
                return _FakeSession()
            def close(self):
                pass

        import neo4j
        real_driver = neo4j.GraphDatabase.driver
        neo4j.GraphDatabase.driver = lambda *a, **k: _FakeDriver()
        try:
            ghosts = memory_self_heal._load_ghost_nodes(
                {"uri": "bolt://x", "user": "u", "password": "p"},
                {"alive-1", "alive-2"},
            )
        finally:
            neo4j.GraphDatabase.driver = real_driver

        assert len(ghosts) == 2
        assert ghosts[0]["uid"] == "ghost-1"
        assert ghosts[0]["count"] == 3
        # 盘点覆盖 MemoryNode 用户私有记忆标签 + Skill（仅统计用）
        assert "n:MemoryNode" in captured["cypher"]
        # 幽灵过滤参数传入了有效 account 集合（顺序无关）
        assert set(captured["valid"]) == {"alive-1", "alive-2"}

    def test_write_ghost_cleanup_audit_inserts_row(self):
        """审计写入应 INSERT 一条 audit_log（action=ghost_memory_cleanup）。"""
        from internal.migration import memory_self_heal

        class _FakeConn:
            def __init__(self):
                self.executed = []
            def execute(self, sql, params=None):
                self.executed.append((str(sql), params))
            def __enter__(self):
                return self
            def __exit__(self, *a):
                return False

        conn = _FakeConn()

        class _FakeEngine:
            def begin(self):
                return conn

        memory_self_heal._write_ghost_cleanup_audit(
            _FakeEngine(),
            {"deleted_nodes": 8, "ghost_users": 5},
        )

        assert len(conn.executed) == 1
        sql, params = conn.executed[0]
        assert "INSERT INTO audit_log" in sql
        assert "ghost_memory_cleanup" in sql
        assert "CAST(:after AS jsonb)" in sql
        assert params["after"] is not None
