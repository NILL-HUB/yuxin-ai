"""赫布权重衰减器（HebbianDecay）。

根据时间衰减、共现增强、干扰惩罚动态计算边的综合权重，并据此决定存储层级
（HOT / WARM / COLD）。支撑记忆系统的自然遗忘与层级迁移机制。

公式:
    weight = base_weight * exp(-effective_lambda * Δt) + alpha * cooccurrence_count
             - beta * interference_count
    其中 Δt 为自 last_accessed_at 起的天数。

衰减豁免（记忆写入优化）:
    effective_lambda = lambda_decay * exemption_factor
    - preference/identity/aversion：强豁免（×0.1，近不遗忘）
    - habit/goal/capability：中等豁免（×0.5，缓慢遗忘）
    - meta_instruction 或无类别：不豁免（×1.0，按原速率遗忘）

降级策略:
    - Neo4j 不可用时，batch_update_weights 返回全 0 计数并记 warning 日志
    - 单条边计算异常时跳过该边，不影响其他边

设计参考:
    docs/prd/memory-system/02-storage-and-retrieval.md §5.2
    docs/prd/memory-system/execution/03-track-b-storage-retrieval.md B1
    docs/prd/memory-write-optimization-design.md §5 衰减豁免
"""

from __future__ import annotations

import logging
import math
from datetime import datetime, timezone
from typing import Optional

from internal.config.memory_settings import settings
from internal.model.memory_models import ExplicitCategory, MemoryEdge, StorageTier

logger = logging.getLogger(__name__)


# 衰减豁免系数映射表
_DECAY_EXEMPTION_MAP: dict[str, float] = {
    # 强豁免：近不遗忘
    ExplicitCategory.PREFERENCE.value: 0.1,
    ExplicitCategory.IDENTITY.value: 0.1,
    ExplicitCategory.AVERSION.value: 0.1,
    # 中等豁免：缓慢遗忘
    ExplicitCategory.HABIT.value: 0.5,
    ExplicitCategory.GOAL.value: 0.5,
    ExplicitCategory.CAPABILITY.value: 0.5,
    # 不豁免：按原速率
    ExplicitCategory.META_INSTRUCTION.value: 1.0,
}


class HebbianDecay:
    """赫布权重衰减器。

    不使用 ``@inject``：无注入依赖，配置从 ``settings.decay`` 读取，
    Neo4j 驱动在 ``batch_update_weights`` 时由调用方传入。
    """

    def __init__(self, config=None) -> None:
        """初始化衰减器。

        Args:
            config: DecayConfig 实例，为 None 时使用 settings.decay
        """
        if config is not None:
            self._config = config
        else:
            # 使用 memory_settings 中的 DecayConfig
            self._config = settings.decay

    # =========================================================
    # 权重计算与层级判定
    # =========================================================

    def compute_weight(
        self,
        edge: MemoryEdge,
        now: Optional[datetime] = None,
        explicit_category: Optional[str] = None,
    ) -> float:
        """计算边的当前综合权重（含衰减豁免）。

        公式: weight = base_weight * exp(-effective_lambda * Δt)
                       + alpha * cooccurrence_count
                       - beta * interference_count

        衰减豁免:
            effective_lambda = lambda_decay * exemption_factor
            - preference/identity/aversion：×0.1（强豁免）
            - habit/goal/capability：×0.5（中等豁免）
            - meta_instruction 或无类别：×1.0（不豁免）

        Args:
            edge: 记忆边（含 base_weight、last_accessed_at、cooccurrence_count）
            now: 当前时间，None 时使用 UTC 当前时刻
            explicit_category: 显式陈述类别（preference/habit/identity/aversion/
                goal/meta_instruction/capability），None 时从 edge.properties 读取，
                用于衰减豁免计算

        Returns:
            裁剪到 [0.0, 1.0] 区间的综合权重
        """
        if now is None:
            now = datetime.now(timezone.utc)

        # 确保 last_accessed_at 带时区
        last_accessed = edge.last_accessed_at
        if last_accessed.tzinfo is None:
            last_accessed = last_accessed.replace(tzinfo=timezone.utc)
        if now.tzinfo is None:
            now = now.replace(tzinfo=timezone.utc)

        # Δt 天数
        delta_seconds = (now - last_accessed).total_seconds()
        delta_days = max(delta_seconds / 86400.0, 0.0)

        # 衰减豁免：effective_lambda = lambda_decay * exemption_factor
        lambda_decay = self._config.lambda_decay
        # 优先使用显式传入的 explicit_category，其次从 edge.properties 读取
        category = explicit_category or (
            edge.properties.get("explicit_category") if edge.properties else None
        )
        exemption_factor = self._get_exemption_factor(category)
        effective_lambda = lambda_decay * exemption_factor
        decay_factor = math.exp(-effective_lambda * delta_days)

        # base_weight 默认从 edge.weight 读取
        base_weight = float(edge.weight or 1.0)

        # 共现增强
        alpha = self._config.alpha_cooccurrence
        cooccurrence = float(getattr(edge, "cooccurrence_count", 0) or 0)

        # 干扰惩罚（interference_count 未在 MemoryEdge 中显式定义，用 access_count 近似）
        beta = self._config.beta_interference
        # MemoryEdge 没有 interference_count 字段，使用 0 作为默认
        interference = 0.0

        weight = (
            base_weight * decay_factor
            + alpha * cooccurrence
            - beta * interference
        )

        # 裁剪到 [0.0, 1.0]
        return max(0.0, min(1.0, weight))

    @staticmethod
    def _get_exemption_factor(category: Optional[str]) -> float:
        """获取衰减豁免系数。

        Args:
            category: 显式陈述类别字符串

        Returns:
            豁免系数 [0.1, 1.0]，未知类别返回 1.0（不豁免）
        """
        if not category:
            return 1.0
        return _DECAY_EXEMPTION_MAP.get(category, 1.0)

    def determine_tier(self, weight: float) -> StorageTier:
        """根据权重判定存储层级。

        规则:
            - weight > hot_threshold  → HOT
            - weight > warm_threshold → WARM
            - 其他                     → COLD
        """
        hot_threshold = self._config.hot_threshold
        warm_threshold = self._config.warm_threshold
        if weight > hot_threshold:
            return StorageTier.HOT
        if weight > warm_threshold:
            return StorageTier.WARM
        return StorageTier.COLD

    # =========================================================
    # 批量更新
    # =========================================================

    def batch_update_weights(
        self,
        edges: list[MemoryEdge],
        neo4j_driver=None,
        batch_size: int = 500,
    ) -> dict:
        """批量更新 Neo4j 边权重和节点 tier。

        按 batch_size 分组，对每批执行 UNWIND Cypher 批量 SET。

        Args:
            edges: 待更新的边列表
            neo4j_driver: Neo4j 驱动，None 时尝试从 current_app 获取
            batch_size: 每批处理数量

        Returns:
            各层级迁移计数 ``{StorageTier.HOT: n, StorageTier.WARM: m, StorageTier.COLD: k}``
        """
        tier_counts: dict[StorageTier, int] = {
            StorageTier.HOT: 0,
            StorageTier.WARM: 0,
            StorageTier.COLD: 0,
        }

        if not edges:
            return tier_counts

        # 获取驱动
        if neo4j_driver is None:
            neo4j_driver = self._get_driver()

        if neo4j_driver is None:
            logger.warning("batch_update_weights: Neo4j 不可用，跳过批量更新")
            return tier_counts

        now = datetime.utcnow()

        # 分批处理
        for start_idx in range(0, len(edges), batch_size):
            batch = edges[start_idx : start_idx + batch_size]
            updates = []

            for edge in batch:
                try:
                    weight = self.compute_weight(edge, now)
                    tier = self.determine_tier(weight)
                    tier_counts[tier] += 1
                    updates.append(
                        {
                            "edge_id": str(edge.edge_id),
                            "source_id": str(edge.source_id),
                            "target_id": str(edge.target_id),
                            "weight": weight,
                            "tier": tier.value,
                            "now": now.isoformat(),
                        }
                    )
                except Exception:
                    logger.warning(
                        "batch_update_weights: 边权重计算失败 edge_id=%s",
                        edge.edge_id,
                        exc_info=True,
                    )
                    continue

            if not updates:
                continue

            try:
                self._batch_cypher_update(neo4j_driver, updates)
            except Exception:
                logger.warning(
                    "batch_update_weights: Cypher 批量更新失败（batch %d-%d）",
                    start_idx,
                    start_idx + len(batch),
                    exc_info=True,
                )

        return tier_counts

    # =========================================================
    # 内部方法
    # =========================================================

    def manual_decay(self, memory_id: str, decay_factor: float = 0.5) -> float:
        """手动降低单条记忆的权重（D4 decay_memory 端点使用）。

        Args:
            memory_id: 记忆节点 ID
            decay_factor: 衰减因子（0.0-1.0），值越大衰减越严重

        Returns:
            衰减后的新权重，失败返回 0.0
        """
        driver = self._get_driver()
        if driver is None:
            logger.warning("manual_decay: Neo4j 不可用")
            return 0.0

        try:
            decay_factor = max(0.0, min(1.0, decay_factor))
            with driver.session() as session:
                # 读取当前权重
                record = session.run(
                    """
                    MATCH (n) WHERE (n:MemoryNode OR n:Episode OR n:Entity) AND (n.node_id = $memory_id OR n.id = $memory_id)
                    RETURN n.weight AS weight
                    """,
                    memory_id=memory_id,
                ).single()

                if record is None:
                    return 0.0

                current_weight = record.get("weight", 1.0)
                new_weight = current_weight * (1.0 - decay_factor)
                new_weight = max(0.0, new_weight)

                # 写入新权重
                session.run(
                    """
                    MATCH (n) WHERE (n:MemoryNode OR n:Episode OR n:Entity) AND (n.node_id = $memory_id OR n.id = $memory_id)
                    SET n.weight = $new_weight,
                        n.last_accessed_at = datetime()
                    """,
                    memory_id=memory_id,
                    new_weight=new_weight,
                ).consume()

            return new_weight
        except Exception:
            logger.error("manual_decay: 执行失败 memory=%s", memory_id, exc_info=True)
            return 0.0

    def _batch_cypher_update(self, driver, updates: list[dict]) -> None:
        """执行 Cypher 批量 SET 语句。

        更新边的 weight、storage_tier、last_accessed_at，
        同时更新源/目标节点的 tier。
        """
        cypher = """
        UNWIND $updates AS u
        MATCH (s {node_id: u.source_id})-[r]->(t {node_id: u.target_id})
        WHERE r.edge_id = u.edge_id
        SET r.weight = u.weight,
            r.storage_tier = u.tier,
            r.last_accessed_at = u.now
        SET s.storage_tier = CASE
            WHEN u.tier = 'hot' THEN 'hot'
            WHEN u.tier = 'warm' THEN 'warm'
            ELSE 'cold'
        END
        """
        with driver.session() as session:
            session.run(cypher, {"updates": updates}).consume()

    def _get_driver(self):
        """获取 Neo4j 驱动，不可用时返回 None。"""
        try:
            from flask import current_app

            driver = current_app.extensions.get("neo4j")
            if driver is not None:
                return driver
        except RuntimeError:
            pass
        try:
            from internal.extension.neo4j_extension import get_driver

            return get_driver()
        except Exception:
            logger.warning("_get_driver: 获取 Neo4j 驱动失败", exc_info=True)
            return None
