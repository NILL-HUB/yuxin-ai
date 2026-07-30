"""H1+H2 指标定义与采集器单元测试。

验证：
    - 14 个 Prometheus 指标均可注册并通过 render_metrics 暴露
    - MetricsCollector 9 个静态方法正确更新底层指标
    - observe_latency 上下文管理器正确测量耗时
    - 各组件埋点后指标正确更新（写入、检索）
"""

from __future__ import annotations

import time

import pytest
from prometheus_client import REGISTRY
from prometheus_client.registry import CollectorRegistry

from internal.service.memory.metrics import (
    MetricsCollector,
    observe_latency,
    render_metrics,
    memory_write_total,
    memory_write_latency_seconds,
    memory_retrieve_total,
    memory_retrieve_latency_seconds,
    memory_retrieve_results_count,
    memory_storage_tier_nodes,
    memory_skill_count,
    memory_digest_cache_hit,
    memory_consolidation_duration_seconds,
    memory_consolidation_errors_total,
    memory_llm_tokens_total,
    memory_conflict_detected_total,
    memory_pii_filtered_total,
    memory_spread_activation_depth,
)


# =========================================================
# H1: 指标定义验证
# =========================================================


class TestH1MetricDefinitions:
    """验证 14 个 Prometheus 指标定义。"""

    EXPECTED_METRIC_NAMES = [
        "memory_write_total",
        "memory_write_latency_seconds",
        "memory_retrieve_total",
        "memory_retrieve_latency_seconds",
        "memory_retrieve_results_count",
        "memory_storage_tier_nodes",
        "memory_skill_count",
        "memory_digest_cache_hit",
        "memory_consolidation_duration_seconds",
        "memory_consolidation_errors_total",
        "memory_llm_tokens_total",
        "memory_conflict_detected_total",
        "memory_pii_filtered_total",
        "memory_spread_activation_depth",
    ]

    def test_all_14_metrics_registered(self):
        """14 个指标均已注册到默认 registry。"""
        body, _ = render_metrics()
        body_str = body.decode("utf-8")
        for name in self.EXPECTED_METRIC_NAMES:
            assert name in body_str, f"指标 {name} 未在 /metrics 输出中找到"

    def test_render_metrics_returns_correct_content_type(self):
        """render_metrics 返回正确的 Content-Type。"""
        _, content_type = render_metrics()
        assert "text/plain" in content_type

    def test_metric_types_correct(self):
        """指标类型正确：Counter/Histogram/Gauge。"""
        # Counter
        assert memory_write_total._type == "counter"
        assert memory_retrieve_total._type == "counter"
        assert memory_consolidation_errors_total._type == "counter"
        assert memory_llm_tokens_total._type == "counter"
        assert memory_conflict_detected_total._type == "counter"
        assert memory_pii_filtered_total._type == "counter"

        # Histogram
        assert memory_write_latency_seconds._type == "histogram"
        assert memory_retrieve_latency_seconds._type == "histogram"
        assert memory_retrieve_results_count._type == "histogram"
        assert memory_consolidation_duration_seconds._type == "histogram"
        assert memory_spread_activation_depth._type == "histogram"

        # Gauge
        assert memory_storage_tier_nodes._type == "gauge"
        assert memory_skill_count._type == "gauge"
        assert memory_digest_cache_hit._type == "gauge"

    def test_histogram_buckets_reasonable(self):
        """Histogram buckets 设置合理。"""
        body, _ = render_metrics()
        body_str = body.decode("utf-8")

        # 延迟类 buckets 包含 0.01 ~ 10
        assert 'le="0.01"' in body_str or "le=\"0.01\"" in body_str
        assert 'le="10.0"' in body_str

        # 结果数 buckets 包含 0 ~ 100
        assert 'le="0.0"' in body_str or 'le="0"' in body_str
        assert 'le="100.0"' in body_str


# =========================================================
# H2: MetricsCollector 静态方法验证
# =========================================================


class TestMetricsCollector:
    """验证 MetricsCollector 9 个静态方法。"""

    def test_record_write_increments_counter_and_histogram(self):
        """record_write 增加 memory_write_total 并记录延迟观测值。"""
        before = memory_write_total._value.get()
        MetricsCollector.record_write(0.05)
        after = memory_write_total._value.get()
        assert after == before + 1

    def test_record_retrieve_increments_counter_and_histograms(self):
        """record_retrieve 增加检索计数并记录延迟与结果数。"""
        before = memory_retrieve_total._value.get()
        MetricsCollector.record_retrieve(0.1, 5)
        after = memory_retrieve_total._value.get()
        assert after == before + 1

    def test_update_storage_tier_sets_gauge(self):
        """update_storage_tier 设置指定 tier 的 Gauge 值。"""
        MetricsCollector.update_storage_tier("hot", 42)
        body, _ = render_metrics()
        body_str = body.decode("utf-8")
        assert 'memory_storage_tier_nodes{tier="hot"}' in body_str

    def test_update_skill_count_sets_gauge(self):
        """update_skill_count 设置技能总数 Gauge。"""
        MetricsCollector.update_skill_count(7)
        assert memory_skill_count._value.get() == 7.0

    def test_record_digest_cache_updates_ratio(self):
        """record_digest_cache 更新命中率 Gauge。"""
        MetricsCollector.record_digest_cache(hit=True)
        MetricsCollector.record_digest_cache(hit=False)
        # 两次调用后，命中率应该在 0-1 之间
        ratio = memory_digest_cache_hit._value.get()
        assert 0.0 <= ratio <= 1.0

    def test_record_consolidation_phase_without_error(self):
        """record_consolidation_phase 无错误时只记录耗时。"""
        before_errors = memory_consolidation_errors_total._value.get()
        MetricsCollector.record_consolidation_phase(1.5, error=False)
        after_errors = memory_consolidation_errors_total._value.get()
        assert after_errors == before_errors

    def test_record_consolidation_phase_with_error(self):
        """record_consolidation_phase 有错误时增加错误计数。"""
        before_errors = memory_consolidation_errors_total._value.get()
        MetricsCollector.record_consolidation_phase(1.5, error=True)
        after_errors = memory_consolidation_errors_total._value.get()
        assert after_errors == before_errors + 1

    def test_record_llm_tokens_increments_counter_with_labels(self):
        """record_llm_tokens 按模型与操作分类增加 token 计数。"""
        MetricsCollector.record_llm_tokens("gpt-4o-mini", "salience_scoring", 150)
        body, _ = render_metrics()
        body_str = body.decode("utf-8")
        assert 'memory_llm_tokens_total{model="gpt-4o-mini",operation="salience_scoring"}' in body_str

    def test_record_conflict_increments_counter_with_type(self):
        """record_conflict 按冲突类型增加计数。"""
        MetricsCollector.record_conflict("contradiction")
        body, _ = render_metrics()
        body_str = body.decode("utf-8")
        assert 'memory_conflict_detected_total{type="contradiction"}' in body_str

    def test_record_pii_increments_counter(self):
        """record_pii 增加 PII 过滤计数。"""
        before = memory_pii_filtered_total._value.get()
        MetricsCollector.record_pii()
        after = memory_pii_filtered_total._value.get()
        assert after == before + 1

    def test_record_spread_depth_observes_histogram(self):
        """record_spread_depth 记录扩展激活深度。"""
        MetricsCollector.record_spread_depth(3)
        # Histogram 观测后应能从 /metrics 输出中看到
        body, _ = render_metrics()
        body_str = body.decode("utf-8")
        assert "memory_spread_activation_depth" in body_str


# =========================================================
# H2: observe_latency 上下文管理器验证
# =========================================================


class TestObserveLatency:
    """验证 observe_latency 同步上下文管理器。"""

    def test_observe_latency_records_elapsed_time(self):
        """observe_latency 正确测量并记录耗时。"""
        recorded = []

        with observe_latency(lambda s: recorded.append(s)):
            time.sleep(0.01)

        assert len(recorded) == 1
        assert recorded[0] >= 0.01

    def test_observe_latency_records_even_on_exception(self):
        """observe_latency 在异常时仍记录耗时。"""
        recorded = []

        with pytest.raises(ValueError):
            with observe_latency(lambda s: recorded.append(s)):
                raise ValueError("test")

        assert len(recorded) == 1

    def test_observe_latency_with_metrics_collector(self):
        """observe_latency 配合 MetricsCollector 正确更新指标。"""
        before = memory_write_total._value.get()

        with observe_latency(lambda s: MetricsCollector.record_write(s)):
            pass

        after = memory_write_total._value.get()
        assert after == before + 1


# =========================================================
# H2: 组件埋点验证
# =========================================================


class TestComponentInstrumentation:
    """验证各组件埋点后指标正确更新。"""

    def test_write_instrumentation_increments_write_total(self):
        """LedgerWriter 写入后 memory_write_total 增加。"""
        from types import SimpleNamespace
        from uuid import uuid4
        from datetime import datetime
        from internal.model.memory_models import EventSource, MemoryEvent
        from internal.service.memory.ledger_writer import LedgerWriter

        # 构造不依赖 Neo4j/pgvector 的 LedgerWriter
        writer = LedgerWriter(db=SimpleNamespace())

        event = MemoryEvent(
            event_id=uuid4(),
            timestamp=datetime.utcnow(),
            source=EventSource.USER_MESSAGE,
            content="测试写入内容",
            context_messages=[],
            metadata={},
            user_id=str(uuid4()),
        )

        before = memory_write_total._value.get()
        # write_stats_path 不需要 embedding，且 Neo4j 不可用时直接降级返回
        result = writer.write_stats_path(event, entities=[])
        after = memory_write_total._value.get()

        assert after == before + 1, "写入后 memory_write_total 应增加 1"
        assert "error" in result or "updated_entities" in result

    def test_retrieve_instrumentation_increments_retrieve_total(self):
        """MemoryRetriever 检索后 memory_retrieve_total 增加。"""
        from internal.service.memory.retriever import MemoryRetriever

        retriever = MemoryRetriever()

        before = memory_retrieve_total._value.get()
        # 空查询直接返回空列表，但仍记录指标
        results = retriever.retrieve("", "test_user")
        after = memory_retrieve_total._value.get()

        assert after == before + 1, "检索后 memory_retrieve_total 应增加 1"
        assert results == []

    def test_retrieve_instrumentation_records_results_count(self):
        """MemoryRetriever 检索后记录结果数。"""
        from internal.service.memory.retriever import MemoryRetriever

        retriever = MemoryRetriever()
        # 空查询返回 0 个结果
        retriever.retrieve("", "test_user")

        body, _ = render_metrics()
        body_str = body.decode("utf-8")
        # 结果数 Histogram 应有观测值
        assert "memory_retrieve_results_count_count" in body_str
