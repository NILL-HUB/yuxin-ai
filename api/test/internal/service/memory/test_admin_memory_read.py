"""ADMIN-P4 T4：admin 记忆读 service 测试。

被测对象 ``AdminMemoryReadService`` 只做两件事：
1. 用 ``MemoryOwnerKey.for_admin(admin_user_id, agent_id)`` 构造主体，产出
   Cypher 归属谓词（``neo4j_filter_condition``），绑定 ``neo4j_props()`` 参数；
2. 对 Neo4j 查询结果做轻量组装，**任何异常/驱动不可用一律 fail-open**
   （返回空结构，绝不让管理页因记忆引擎故障而 500）。

测试用 fake driver 捕获 ``session.run`` 的 query + params，断言主体绑定正确。
"""
from __future__ import annotations

import pytest

from internal.entity.memory_owner_entity import NEO4J_ADMIN_LEVEL_AGENT_SENTINEL


class _FakeRecord:
    def __init__(self, data):
        self._data = data

    def get(self, key, default=None):
        return self._data.get(key, default)


class _FakeResult:
    def __init__(self, records):
        self._records = records

    def single(self):
        return self._records[0] if self._records else None

    def data(self):
        return [dict(r._data) for r in self._records]


class _FakeSession:
    def __init__(self, queries, script):
        self.queries = queries
        self._script = list(script)

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def run(self, query, **params):
        self.queries.append((query, params))
        if self._script:
            return _FakeResult([_FakeRecord(self._script.pop(0))])
        return _FakeResult([])


class _FakeDriver:
    def __init__(self, script=None):
        self.queries = []
        self._script = list(script or [])

    def session(self):
        return _FakeSession(self.queries, self._script)


def _service(driver):
    from internal.service.memory.admin_memory_read import AdminMemoryReadService

    return AdminMemoryReadService(neo4j_driver=driver)


class TestMemoryStats:
    def test_binds_admin_and_agent_identity(self):
        """stats 的所有查询都必须绑定 admin_user_id + agent_id 归属谓词。"""
        admin_id = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
        agent_id = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"
        driver = _FakeDriver(
            script=[
                {"total": 3},
                {"total": 2},
                {"total": 1},
                {
                    "id": "e1",
                    "content": "最近片段",
                    "created_at": "2026-09-20T00:00:00+00:00",
                },
            ]
        )
        result = _service(driver).memory_stats(
            admin_user_id=admin_id, agent_id=agent_id
        )

        assert len(driver.queries) == 4, "stats 应发出 4 个查询"
        for query, params in driver.queries:
            assert "admin_user_id = $admin_user_id" in query
            assert "agent_id = $agent_id" in query
            assert params["admin_user_id"] == admin_id
            assert params["agent_id"] == agent_id

        # 查询语义：全节点计数 / Episode 计数 / Skill 计数 / 最近片段抽样
        assert "MATCH (n) WHERE" in driver.queries[0][0]
        assert "MATCH (n:Episode)" in driver.queries[1][0]
        assert "MATCH (n:Skill)" in driver.queries[2][0]
        assert "ORDER BY" in driver.queries[3][0] and "LIMIT 5" in driver.queries[3][0]

        assert result == {
            "total_nodes": 3,
            "episodes": 2,
            "skills": 1,
            "recent_memories": [
                {"id": "e1", "content": "最近片段", "created_at": "2026-09-20T00:00:00+00:00"}
            ],
        }

    def test_admin_level_without_agent_uses_sentinel(self):
        """不指定 agent 时，归属参数回落到管理员级哨兵。"""
        admin_id = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
        driver = _FakeDriver(script=[{"total": 0}, {"total": 0}, {"total": 0}])
        _service(driver).memory_stats(admin_user_id=admin_id)

        for _, params in driver.queries:
            assert params["admin_user_id"] == admin_id
            assert params["agent_id"] == NEO4J_ADMIN_LEVEL_AGENT_SENTINEL

    def test_driver_unavailable_fails_open(self):
        """驱动不可用 → 空结构，不抛异常。"""
        result = _service(None).memory_stats(
            admin_user_id="aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
        )
        assert result == {
            "total_nodes": 0,
            "episodes": 0,
            "skills": 0,
            "recent_memories": [],
        }

    def test_neo4j_error_fails_open(self, monkeypatch):
        """查询抛异常 → 空结构，不向路由冒泡 500。"""
        admin_id = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
        driver = _FakeDriver()

        class _BoomSession:
            def run(self, query, **params):
                raise RuntimeError("neo4j down")

        monkeypatch.setattr(driver, "session", lambda: _BoomSession())
        result = _service(driver).memory_stats(admin_user_id=admin_id)
        assert result["total_nodes"] == 0
        assert result["recent_memories"] == []


class TestListMemories:
    def test_paginates_and_filters_by_subject(self):
        admin_id = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
        agent_id = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"
        driver = _FakeDriver(
            script=[
                {"total": 25},
                {
                    "id": "e2",
                    "title": "摘要标题",
                    "content": "正文",
                    "updated_at": "2026-09-20T00:00:00+00:00",
                },
            ]
        )
        result = _service(driver).list_memories(
            admin_user_id=admin_id, agent_id=agent_id, page=3, page_size=10
        )

        count_query, count_params = driver.queries[0]
        page_query, page_params = driver.queries[1]
        assert "MATCH (n:Episode) WHERE" in count_query
        assert "admin_user_id = $admin_user_id" in count_query
        assert "agent_id = $agent_id" in count_query
        assert "MATCH (n:Episode) WHERE" in page_query
        assert "ORDER BY n.updated_at DESC" in page_query
        assert "SKIP $skip" in page_query and "LIMIT $limit" in page_query
        assert page_params["skip"] == 20
        assert page_params["limit"] == 10
        assert count_params["admin_user_id"] == admin_id
        assert page_params["agent_id"] == agent_id

        assert result["total"] == 25
        assert result["items"] == [
            {"id": "e2", "title": "摘要标题", "content": "正文", "updated_at": "2026-09-20T00:00:00+00:00"}
        ]

    def test_bad_page_defaults(self):
        """page/page_size 非法值回落到安全默认。"""
        driver = _FakeDriver(script=[{"total": 0}])
        result = _service(driver).list_memories(
            admin_user_id="aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
            page=0,
            page_size=-1,
        )
        assert result["total"] == 0
        assert result["items"] == []

    def test_driver_unavailable_fails_open(self):
        result = _service(None).list_memories(
            admin_user_id="aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
        )
        assert result == {"items": [], "total": 0}
