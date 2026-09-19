"""PostExecutionHook 主体化（ADMIN-P3c-4 缺口十四b）。

不变量：`_fetch_recent_episodes` 的 Episode 归属从硬编码 `user_id` 属性改为
`MemoryOwnerKey` 访问器——用户态 `parse(裸uuid)` 产物 == 历史 `user_id`
字面量（逐字节等价）；admin 态走 `admin_user_id` + `agent_id`。
"""

from uuid import uuid4

from internal.service.memory.post_execution_hook import PostExecutionHook


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


class _FakeEmergence:
    def __init__(self, driver):
        self._driver = driver

    def _get_driver(self):
        return self._driver


def _hook() -> PostExecutionHook:
    return PostExecutionHook()


class TestFetchRecentEpisodesOwnerScope:
    def test_user_binds_user_id_literal(self):
        """用户态：Episode 查询绑定 == 历史 user_id 字面量。"""
        session = _RecordingSession()
        hook = _hook()
        uid = str(uuid4())

        result = hook._fetch_recent_episodes(_FakeEmergence(_Driver(session)), uid)

        assert result == []
        assert session.calls, "应有一次查询"
        cypher, params = session.calls[0]
        assert "MATCH (e:Episode" in cypher
        assert params["user_id"] == uid

    def test_admin_binds_admin_props(self):
        """admin 态：Episode 查询按 admin 属性（非 user_id）。"""
        session = _RecordingSession()
        hook = _hook()
        admin_id = str(uuid4())

        hook._fetch_recent_episodes(_FakeEmergence(_Driver(session)), f"admin:{admin_id}")

        cypher, params = session.calls[0]
        assert "e.admin_user_id = $admin_user_id" in cypher
        assert "e.agent_id = $agent_id" in cypher
        assert params["admin_user_id"] == admin_id
        assert params["agent_id"] == "__admin_level__"
