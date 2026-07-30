"""记忆系统 Prometheus 指标定义与采集器（H1 + H2）。

定义 14 个 Prometheus 指标，覆盖四层监控：
    - Layer 1 RED（Rate/Errors/Duration）：写入与检索
    - Layer 2 USE（Utilization/Saturation/Errors）：存储层
    - Layer 3：巩固与 LLM 调用
    - Layer 4：业务事件（冲突、PII、扩展激活）

MetricsCollector 提供静态方法封装底层指标更新；observe_latency 为同步上下文
管理器（项目为同步 Flask 架构），自动测量操作耗时并记录到指定指标。

设计参考:
    docs/prd/memory-system/execution/09-track-h-monitoring-test.md H1/H2
"""

from __future__ import annotations

import logging
import time
from contextlib import contextmanager
from typing import Callable, Optional

from prometheus_client import (
    Counter,
    Gauge,
    Histogram,
    generate_latest,
    CONTENT_TYPE_LATEST,
    REGISTRY,
)

logger = logging.getLogger(__name__)


# =========================================================
# H1: 14 个 Prometheus 指标定义
# =========================================================

# Histogram buckets
_LATENCY_BUCKETS = (0.01, 0.05, 0.1, 0.5, 1.0, 5.0, 10.0)
_RESULTS_COUNT_BUCKETS = (0, 5, 10, 20, 50, 100)
_SPREAD_DEPTH_BUCKETS = (0, 1, 2, 3, 5, 8, 12)


# ---- Layer 1: RED（写入与检索） ----
memory_write_total = Counter(
    "memory_write_total",
    "记忆写入总数",
)
memory_write_latency_seconds = Histogram(
    "memory_write_latency_seconds",
    "记忆写入延迟（秒）",
    buckets=_LATENCY_BUCKETS,
)
memory_retrieve_total = Counter(
    "memory_retrieve_total",
    "记忆检索总数",
)
memory_retrieve_latency_seconds = Histogram(
    "memory_retrieve_latency_seconds",
    "记忆检索延迟（秒）",
    buckets=_LATENCY_BUCKETS,
)
memory_retrieve_results_count = Histogram(
    "memory_retrieve_results_count",
    "单次检索返回结果数量分布",
    buckets=_RESULTS_COUNT_BUCKETS,
)

# ---- Layer 2: USE（存储层） ----
memory_storage_tier_nodes = Gauge(
    "memory_storage_tier_nodes",
    "各存储层级节点数",
    labelnames=("tier",),
)
memory_skill_count = Gauge(
    "memory_skill_count",
    "已涌现技能总数",
)
memory_digest_cache_hit = Gauge(
    "memory_digest_cache_hit",
    "Digest 缓存命中率（0-1 滚动值）",
)

# ---- Layer 3: 巩固与 LLM 调用 ----
memory_consolidation_duration_seconds = Histogram(
    "memory_consolidation_duration_seconds",
    "巩固阶段总耗时（秒）",
    buckets=_LATENCY_BUCKETS,
)
memory_consolidation_errors_total = Counter(
    "memory_consolidation_errors_total",
    "巩固阶段错误总数",
)
memory_llm_tokens_total = Counter(
    "memory_llm_tokens_total",
    "LLM 调用 token 消耗",
    labelnames=("model", "operation"),
)

# ---- Layer 4: 业务事件 ----
memory_conflict_detected_total = Counter(
    "memory_conflict_detected_total",
    "检测到的冲突总数",
    labelnames=("type",),
)
memory_pii_filtered_total = Counter(
    "memory_pii_filtered_total",
    "PII 过滤命中总数",
)
memory_spread_activation_depth = Histogram(
    "memory_spread_activation_depth",
    "扩展激活遍历深度分布",
    buckets=_SPREAD_DEPTH_BUCKETS,
)

# ---- Layer 5: 显式陈述检测与写时冲突解决（记忆写入优化） ----
memory_explicit_detection_total = Counter(
    "memory_explicit_detection_total",
    "显式陈述检测总数",
    labelnames=("category", "stage"),
)
memory_conflict_resolved_total = Counter(
    "memory_conflict_resolved_total",
    "写时冲突解决总数",
    labelnames=("type",),
)


# =========================================================
# H2: MetricsCollector 静态方法封装
# =========================================================


class MetricsCollector:
    """记忆系统指标采集器。

    所有方法均为静态方法，封装对底层 Prometheus 指标的更新操作。
    异常时仅记录日志不抛出，确保监控埋点不影响业务流程。
    """

    # ---- Layer 1: 写入与检索 ----

    @staticmethod
    def record_write(latency_seconds: float) -> None:
        """记录一次记忆写入。"""
        try:
            memory_write_total.inc()
            memory_write_latency_seconds.observe(max(0.0, float(latency_seconds)))
        except Exception:
            logger.warning("record_write 指标更新失败", exc_info=True)

    @staticmethod
    def record_retrieve(latency_seconds: float, results_count: int) -> None:
        """记录一次记忆检索。"""
        try:
            memory_retrieve_total.inc()
            memory_retrieve_latency_seconds.observe(max(0.0, float(latency_seconds)))
            memory_retrieve_results_count.observe(max(0, int(results_count)))
        except Exception:
            logger.warning("record_retrieve 指标更新失败", exc_info=True)

    # ---- Layer 2: 存储层 ----

    @staticmethod
    def update_storage_tier(tier: str, count: int) -> None:
        """更新某存储层级节点数。"""
        try:
            memory_storage_tier_nodes.labels(tier=tier).set(max(0, int(count)))
        except Exception:
            logger.warning("update_storage_tier 指标更新失败", exc_info=True)

    @staticmethod
    def update_skill_count(count: int) -> None:
        """更新已涌现技能总数。"""
        try:
            memory_skill_count.set(max(0, int(count)))
        except Exception:
            logger.warning("update_skill_count 指标更新失败", exc_info=True)

    @staticmethod
    def record_digest_cache(hit: bool) -> None:
        """记录 Digest 缓存命中/未命中，并滚动更新命中率 Gauge。

        使用简单的累计命中率近似：命中数 / 总请求数。由于 Gauge 需要反映
        滚动值，这里用模块级计数器维护。
        """
        global _digest_hit_count, _digest_total_count
        try:
            _digest_total_count += 1
            if hit:
                _digest_hit_count += 1
            ratio = _digest_hit_count / _digest_total_count if _digest_total_count > 0 else 0.0
            memory_digest_cache_hit.set(ratio)
        except Exception:
            logger.warning("record_digest_cache 指标更新失败", exc_info=True)

    # ---- Layer 3: 巩固与 LLM ----

    @staticmethod
    def record_consolidation_phase(duration_seconds: float, error: bool = False) -> None:
        """记录巩固阶段。"""
        try:
            memory_consolidation_duration_seconds.observe(max(0.0, float(duration_seconds)))
            if error:
                memory_consolidation_errors_total.inc()
        except Exception:
            logger.warning("record_consolidation_phase 指标更新失败", exc_info=True)

    @staticmethod
    def record_llm_tokens(model: str, operation: str, tokens: int) -> None:
        """记录 LLM token 消耗。"""
        try:
            memory_llm_tokens_total.labels(model=model, operation=operation).inc(
                max(0, int(tokens))
            )
        except Exception:
            logger.warning("record_llm_tokens 指标更新失败", exc_info=True)

    # ---- Layer 4: 业务事件 ----

    @staticmethod
    def record_conflict(conflict_type: str) -> None:
        """记录冲突检测。"""
        try:
            memory_conflict_detected_total.labels(type=conflict_type).inc()
        except Exception:
            logger.warning("record_conflict 指标更新失败", exc_info=True)

    @staticmethod
    def record_pii() -> None:
        """记录 PII 过滤命中。"""
        try:
            memory_pii_filtered_total.inc()
        except Exception:
            logger.warning("record_pii 指标更新失败", exc_info=True)

    @staticmethod
    def record_spread_depth(depth: int) -> None:
        """记录扩展激活遍历深度。"""
        try:
            memory_spread_activation_depth.observe(max(0, int(depth)))
        except Exception:
            logger.warning("record_spread_depth 指标更新失败", exc_info=True)

    # ---- Layer 5: 显式陈述检测与写时冲突解决 ----

    @staticmethod
    def record_explicit_detection(category: str, stage: str) -> None:
        """记录显式陈述检测。

        Args:
            category: 显式陈述分类（preference/habit/identity/aversion/goal/meta_instruction/capability）
            stage: 检测阶段（regex_hit/llm_confirmed/fallback）
        """
        try:
            memory_explicit_detection_total.labels(
                category=category, stage=stage
            ).inc()
        except Exception:
            logger.warning("record_explicit_detection 指标更新失败", exc_info=True)

    @staticmethod
    def record_conflict_resolved(conflict_type: str) -> None:
        """记录写时冲突解决。

        Args:
            conflict_type: 冲突类型（supersede/contradiction/complement）
        """
        try:
            memory_conflict_resolved_total.labels(type=conflict_type).inc()
        except Exception:
            logger.warning("record_conflict_resolved 指标更新失败", exc_info=True)


# Digest 缓存命中统计计数器（模块级，供 record_digest_cache 滚动计算命中率）
_digest_hit_count: int = 0
_digest_total_count: int = 0


# =========================================================
# H2: observe_latency 同步上下文管理器
# =========================================================


@contextmanager
def observe_latency(record_fn: Callable[[float], None]):
    """自动测量操作耗时的同步上下文管理器。

    项目为同步 Flask 架构，使用同步 contextmanager 而非 asynccontextmanager。

    用法：
        with observe_latency(lambda s: MetricsCollector.record_write(s)):
            ledger_writer.write_full_path(event)
    """
    start = time.perf_counter()
    try:
        yield
    finally:
        try:
            record_fn(time.perf_counter() - start)
        except Exception:
            logger.warning("observe_latency 记录耗时失败", exc_info=True)


def render_metrics() -> tuple[bytes, str]:
    """渲染 Prometheus 格式指标文本。

    Returns:
        ``(body_bytes, content_type)``
    """
    return generate_latest(REGISTRY), CONTENT_TYPE_LATEST


__all__ = [
    "MetricsCollector",
    "observe_latency",
    "render_metrics",
    # 指标对象（供测试直接断言）
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
    "memory_explicit_detection_total",
    "memory_conflict_resolved_total",
]
