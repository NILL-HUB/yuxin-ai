"""ProfileGraphService 主体化（ADMIN-P3c-4 缺口四）。

不变量：所有方法把参数「user_id 字符串」语义升级为「主体键字符串」——
用户态 `parse(裸uuid)` 产物 == 历史 `user_id` 字面量（逐字节等价）；
admin 态（`admin:{uuid}` / `admin:{uuid}:{uuid}`）走 `admin_user_id` + `agent_id`
属性级分离（与 Neo4j 写侧同源）。
"""

from uuid import uuid4

import pytest

from internal.service.memory.profile_graph import ProfileGraphService


class _RecordingSession:
    def __init__(self, single_result=None, records=None):
        self._single_result = single_result
        self._records = list(records or [])
        self.calls = []

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def run(self, cypher, parameters=None, **binds):
        params = dict(parameters or {})
        params.update(binds)
        self.calls.append((cypher, params))
        if "RETURN count(*)" in cypher or "RETURN size(" in cypher:
            return _SingleResult(self._single_result)
        if "RETURN e.explicit_category AS category" in cypher:
            return _RecordsResult(self._records)
        if "RETURN collect(DISTINCT n)" in cypher or "RETURN n" in cypher:
            return _RecordsResult(self._records)
        return _RecordsResult(self._records)


class _SingleResult:
    def __init__(self, value):
        self._value = value

    def single(self):
        return self._value

    def consume(self):
        return None


class _RecordsResult:
    def __init__(self, records):
        self._records = records

    def __iter__(self):
        return iter(self._records)

    def consume(self):
        return None


class _Driver:
    def __init__(self, session):
        self._session = session

    def session(self):
        return self._session


def _service(session) -> ProfileGraphService:
    return ProfileGraphService(neo4j_driver=_Driver(session))


def _make_service(monkeypatch, session):
    return _service(session)


class TestGetProfileTextOwnerScope:
    def test_user_binds_user_id_literal(self, monkeypatch):
        """用户态：get_profile_text(裸uuid) 绑定 == 历史 user_id 字面量。"""
        session = _RecordingSession()
        service = _make_service(monkeypatch, session)
        uid = str(uuid4())

        assert service.get_profile_text(uid) == ""
        assert session.calls, "应有一次查询"
        cypher, params = session.calls[0]
        assert "n.user_id = $user_id" in cypher
        assert params["user_id"] == uid

    def test_admin_binds_admin_props(self, monkeypatch):
        """admin 态：get_profile_text(admin:uuid) 绑定 admin_user_id + agent_id（哨兵）。"""
        session = _RecordingSession()
        service = _make_service(monkeypatch, session)
        admin_id = str(uuid4())

        assert service.get_profile_text(f"admin:{admin_id}") == ""
        cypher, params = session.calls[0]
        assert "n.admin_user_id = $admin_user_id" in cypher
        assert "n.agent_id = $agent_id" in cypher
        assert params["admin_user_id"] == admin_id
        assert params["agent_id"] == "__admin_level__"

    def test_admin_agent_binds_real_agent(self, monkeypatch):
        """admin+agent 态：agent_id 绑定真实 UUID。"""
        session = _RecordingSession()
        service = _make_service(monkeypatch, session)
        admin_id, agent_id = str(uuid4()), str(uuid4())

        service.get_profile_text(f"admin:{admin_id}:{agent_id}")
        cypher, params = session.calls[0]
        assert params["admin_user_id"] == admin_id
        assert params["agent_id"] == agent_id


class TestEnsureUserOwnerScope:
    def test_user_merges_on_id(self, monkeypatch):
        """用户态：ensure_user 保持 MERGE (u:User {id: $user_id})。"""
        session = _RecordingSession()
        service = _make_service(monkeypatch, session)
        uid = str(uuid4())

        service.ensure_user(uid)
        cypher, params = session.calls[0]
        assert "MERGE (u:User {id: $user_id})" in cypher
        assert params["user_id"] == uid

    def test_admin_merges_on_admin_props(self, monkeypatch):
        """admin 态：ensure_user 改 MERGE (u:User {admin_user_id, agent_id})。"""
        session = _RecordingSession()
        service = _make_service(monkeypatch, session)
        admin_id = str(uuid4())

        service.ensure_user(f"admin:{admin_id}")
        cypher, params = session.calls[0]
        assert "MERGE (u:User {admin_user_id: $admin_user_id, agent_id: $agent_id})" in cypher
        assert params["admin_user_id"] == admin_id
        assert params["agent_id"] == "__admin_level__"


class TestSyncExplicitEpisodesOwnerScope:
    def test_user_queries_episode_by_user_id(self, monkeypatch):
        """用户态：Episode 查询绑定 user_id 字面量。"""
        session = _RecordingSession()
        service = _make_service(monkeypatch, session)
        uid = str(uuid4())

        result = service.sync_from_explicit_episodes(uid)
        assert result["user"] is True
        # calls[0]=ensure_user, calls[1]=Episode 查询
        cypher, params = session.calls[1]
        assert "MATCH (e:Episode" in cypher
        assert params["user_id"] == uid

    def test_admin_queries_episode_by_admin_props(self, monkeypatch):
        """admin 态：Episode 查询按 admin 属性（非 user_id）。"""
        session = _RecordingSession()
        service = _make_service(monkeypatch, session)
        admin_id = str(uuid4())

        result = service.sync_from_explicit_episodes(f"admin:{admin_id}")
        assert result["user"] is True
        cypher, params = session.calls[1]
        assert "MATCH (e:Episode" in cypher
        assert "e.admin_user_id = $admin_user_id" in cypher
        assert "e.agent_id = $agent_id" in cypher
        assert params["admin_user_id"] == admin_id


class TestMarkUserInactiveOwnerScope:
    def test_user_matches_user_node(self, monkeypatch):
        """用户态：mark_user_inactive 匹配 User {id}。"""
        session = _RecordingSession()
        service = _make_service(monkeypatch, session)
        uid = str(uuid4())

        service.mark_user_inactive(uid)
        cypher, params = session.calls[0]
        assert "MATCH (u:User {id: $user_id})" in cypher
        assert params["user_id"] == uid

    def test_admin_matches_admin_user_node(self, monkeypatch):
        """admin 态：mark_user_inactive 匹配 admin 属性 User 节点。"""
        session = _RecordingSession()
        service = _make_service(monkeypatch, session)
        admin_id = str(uuid4())

        service.mark_user_inactive(f"admin:{admin_id}")
        cypher, params = session.calls[0]
        assert "MATCH (u:User {admin_user_id: $admin_user_id, agent_id: $agent_id})" in cypher
        assert params["admin_user_id"] == admin_id
