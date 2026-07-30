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
