"""B1 HebbianDecay 单元测试。"""

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from internal.model.memory_models import MemoryEdge
from internal.service.memory.hebbian_decay import HebbianDecay


def _make_edge(
    *,
    weight: float = 1.0,
    last_accessed_at: datetime | None = None,
    cooccurrence_count: int = 0,
    access_count: int = 0,
) -> MemoryEdge:
    """构造测试用 MemoryEdge。"""
    now = datetime.now(UTC)
    return MemoryEdge(
        source_id=uuid4(),
        target_id=uuid4(),
        relation_type="KNOWS",
        weight=weight,
        last_accessed_at=last_accessed_at or now,
        cooccurrence_count=cooccurrence_count,
        access_count=access_count,
        created_at=now,
    )


class TestHebbianDecayComputeWeight:
    def test_recent_edge_should_retain_high_weight(self):
        """刚刚访问的边权重应接近 base_weight。"""
        decay = HebbianDecay()
        now = datetime.now(UTC)
        edge = _make_edge(weight=1.0, last_accessed_at=now)

        w = decay.compute_weight(edge, now=now)

        assert 0.9 <= w <= 1.0

    def test_old_edge_should_decay(self):
        """30 天未访问的边权重应明显衰减。"""
        decay = HebbianDecay()
        now = datetime.now(UTC)
        edge = _make_edge(
            weight=1.0,
            last_accessed_at=now - timedelta(days=30),
        )

        w = decay.compute_weight(edge, now=now)

        assert 0.0 <= w < 0.5

    def test_cooccurrence_should_boost_weight(self):
        """共现计数高的边权重应有强化。"""
        decay = HebbianDecay()
        now = datetime.now(UTC)
        edge_low = _make_edge(
            weight=0.5,
            last_accessed_at=now,
            cooccurrence_count=0,
        )
        edge_high = _make_edge(
            weight=0.5,
            last_accessed_at=now,
            cooccurrence_count=10,
        )

        w_low = decay.compute_weight(edge_low, now=now)
        w_high = decay.compute_weight(edge_high, now=now)

        assert w_high >= w_low

    def test_weight_should_be_non_negative(self):
        """权重不应为负。"""
        decay = HebbianDecay()
        now = datetime.now(UTC)
        edge = _make_edge(
            weight=0.1,
            last_accessed_at=now - timedelta(days=365),
        )

        w = decay.compute_weight(edge, now=now)

        assert w >= 0.0


class TestHebbianDecayBatchUpdate:
    def test_batch_update_should_return_tier_counts_when_no_edges(self):
        """空列表应返回各层级 0 计数。"""
        from internal.model.memory_models import StorageTier

        decay = HebbianDecay()
        result = decay.batch_update_weights([], neo4j_driver=None)

        # 返回 {StorageTier.HOT: 0, StorageTier.WARM: 0, StorageTier.COLD: 0}
        assert result[StorageTier.HOT] == 0
        assert result[StorageTier.WARM] == 0
        assert result[StorageTier.COLD] == 0

    def test_batch_update_should_degrade_gracefully_without_driver(self):
        """无 Neo4j 驱动时应降级返回而不抛异常。"""
        from internal.model.memory_models import StorageTier

        decay = HebbianDecay()
        edges = [_make_edge() for _ in range(3)]

        result = decay.batch_update_weights(edges, neo4j_driver=None)

        # 无驱动时返回 tier 计数字典（全 0），不抛异常
        assert isinstance(result, dict)
        assert StorageTier.HOT in result
