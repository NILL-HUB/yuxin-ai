"""WriteTimeConflictResolver 主体化（ADMIN-P3c-4 缺口十四a）。

不变量：`_query_candidates` 的 Cypher 归属从硬编码 `user_id` 属性改为
`MemoryOwnerKey` 访问器——用户态 `parse(裸uuid)` 产物 == 历史 `user_id`
字面量（逐字节等价）；admin 态（`admin:{uuid}`）走 `admin_user_id` + `agent_id`
属性级分离。
"""

from uuid import uuid4

from internal.service.memory.write_time_conflict_resolver import WriteTimeConflictResolver


class _StubEmbeddings:
    def __init__(self, *args, **kwargs):
        pass


class _RecordingSession:
    def __init__(self):
        self.calls = []

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def run(self, cypher, parameters=None, **binds):
        params = dict(parameters or {})
        params.update(binds)
        self.calls.append((cypher, params))
        return iter([])


class _Driver:
    def __init__(self, session):
        self._session = session

    def session(self):
        return self._session


def _resolver() -> WriteTimeConflictResolver:
    return WriteTimeConflictResolver(embeddings_service=_StubEmbeddings())


class TestQueryCandidatesOwnerScope:
    def test_user_binds_user_id_literal(self):
        """用户态：候选查询绑定 == 历史 user_id 字面量。"""
        session = _RecordingSession()
        resolver = _resolver()
        uid = str(uuid4())

        result = resolver._query_candidates(_Driver(session), uid, "Python")

        assert result == []
        assert session.calls, "应有一次查询"
        cypher, params = session.calls[0]
        assert "MATCH (e:Entity {name: $subject, user_id: $user_id})" in cypher
        assert "admin_user_id" not in cypher
        assert params["user_id"] == uid
        assert params["subject"] == "Python"

    def test_admin_binds_admin_props(self):
        """admin 态：候选查询按 admin 属性（非 user_id）。"""
        session = _RecordingSession()
        resolver = _resolver()
        admin_id = str(uuid4())

        resolver._query_candidates(_Driver(session), f"admin:{admin_id}", "Python")

        cypher, params = session.calls[0]
        assert "e.admin_user_id = $admin_user_id" in cypher
        assert "e.agent_id = $agent_id" in cypher
        assert params["admin_user_id"] == admin_id
        assert params["agent_id"] == "__admin_level__"

    def test_admin_agent_binds_real_agent(self):
        """admin+agent 态：agent_id 绑定真实 UUID。"""
        session = _RecordingSession()
        resolver = _resolver()
        admin_id, agent_id = str(uuid4()), str(uuid4())

        resolver._query_candidates(_Driver(session), f"admin:{admin_id}:{agent_id}", "Go")

        cypher, params = session.calls[0]
        assert params["admin_user_id"] == admin_id
        assert params["agent_id"] == agent_id
