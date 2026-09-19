"""B4 SpreadActivation 单元测试。"""

from uuid import uuid4

import pytest

from internal.service.memory.spread_activation import SpreadActivation


class TestSpreadActivation:
    def test_activate_should_degrade_to_empty_without_driver(self):
        """无 Neo4j 驱动时应降级返回空列表。"""
        spread = SpreadActivation(neo4j_driver=None)
        result = spread.activate([str(uuid4())], top_k=20)

        assert isinstance(result, list)
        assert result == []

    def test_activate_should_accept_empty_seed_list(self):
        """空种子列表应返回空结果。"""
        spread = SpreadActivation(neo4j_driver=None)
        result = spread.activate([], top_k=20)

        assert result == []

    def test_activate_should_clamp_top_k(self):
        """top_k 超大不应抛异常。"""
        spread = SpreadActivation(neo4j_driver=None)
        # 不应抛异常
        result = spread.activate([str(uuid4())], top_k=10000)
        assert isinstance(result, list)


class TestSpreadActivationOwnerScope:
    """缺口一（ADMIN-P3c-4）：图扩展按主体谓词约束。

    用户态不传 owner_key 时与历史逐字节等价；传 owner_key 时 Cypher 含主体谓词。
    """

    class _Session:
        def __init__(self, spread):
            self._spread = spread
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

    def test_cypher_multi_hop_omits_owner_predicate_without_owner(self):
        """不传 owner_key 时 Cypher 无主体谓词（与历史一致）。"""
        spread = SpreadActivation(neo4j_driver=None)
        session = self._Session(spread)
        spread._cypher_multi_hop(self._Driver(session), [str(uuid4())], 5)

        assert session.calls
        cypher, params = session.calls[0]
        assert "user_id" not in cypher
        assert "admin_user_id" not in cypher

    def test_cypher_multi_hop_binds_owner_predicate_with_owner(self):
        """传 owner_key 时 Cypher 含主体谓词并绑定属性。"""
        spread = SpreadActivation(neo4j_driver=None)
        session = self._Session(spread)
        uid = str(uuid4())

        spread._cypher_multi_hop(self._Driver(session), [str(uuid4())], 5, owner_key=uid)

        cypher, params = session.calls[0]
        assert "user_id = $user_id" in cypher
        assert params["user_id"] == uid

    def test_cypher_multi_hop_admin_binds_admin_props(self):
        """admin 主体下 Cypher 绑定 admin_user_id + agent_id。"""
        spread = SpreadActivation(neo4j_driver=None)
        session = self._Session(spread)
        admin_id = str(uuid4())

        spread._cypher_multi_hop(
            self._Driver(session), [str(uuid4())], 5, owner_key=f"admin:{admin_id}"
        )

        cypher, params = session.calls[0]
        assert "admin_user_id = $admin_user_id" in cypher
        assert params["admin_user_id"] == admin_id
        assert params["agent_id"] == "__admin_level__"
