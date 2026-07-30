"""冲突检测器（ConflictDetector）。

使用 LLM 判定记忆对之间的关系（CONTRADICTION / UPDATE / COMPLEMENT），
并根据判定结果执行相应解决操作。批量检测（batch_size=50），相似度 > 0.85
的对调 LLM 判定，置信度 > 0.7 才执行解决。

冲突类型与解决操作:
    - CONTRADICTION: 旧节点 t_invalidated_at=now + status='deprecated'
    - UPDATE:        旧节点 t_invalidated_at + SUPERSEDED_BY 边
    - COMPLEMENT:    创建双向 COMPLEMENTARY 边

降级策略:
    - Neo4j 不可用时跳过检测，返回全 0 计数
    - LLM 异常时跳过该对（不阻断整体检测）

设计参考:
    docs/prd/memory-system/03-consolidation-skill-policy-api.md §7.2
    docs/prd/memory-system/execution/04-track-c-consolidation.md C2
"""

from __future__ import annotations

import json
import logging
from datetime import datetime
from typing import Optional
from uuid import uuid4

from pydantic import BaseModel, Field

from internal.config.memory_settings import settings
from internal.model.memory_models import ConflictType, ConflictResult
from internal.service.language_model_service import LanguageModelService
from internal.service.memory.llm_activity_probe import (
    LLMActivityProbe,
    LLMActivityTimeoutError,
)
from internal.service.memory.metrics import MetricsCollector

logger = logging.getLogger(__name__)


# ============================================================
# LLM 结构化输出辅助模型
# ============================================================


class _ConflictJudgment(BaseModel):
    """LLM 冲突判定结果。"""

    type: str = Field(
        ...,
        description="冲突类型: contradiction / update / complement / none",
    )
    confidence: float = Field(
        ..., ge=0.0, le=1.0, description="置信度 0-1"
    )
    explanation: str = Field(default="", description="判定理由")


# 冲突检测 prompt 模板
_CONFLICT_DETECTION_PROMPT = """你是一个记忆冲突检测专家。请判断以下两条记忆之间的关系。

记忆 A: {memory_a}
记忆 B: {memory_b}

请判断它们之间的关系类型:
- contradiction: 两条记忆直接矛盾，不能同时为真
- update: 记忆 B 是记忆 A 的更新版本，B 更准确或更近期
- complement: 两条记忆互补，可以共存
- none: 两条记忆无关或完全相同

请返回 JSON，包含 type（类型）、confidence（置信度 0-1）、explanation（理由）。
"""


class ConflictDetector:
    """记忆冲突检测器。

    不使用 ``@inject``：无注入依赖，配置从 ``settings.consolidation`` 读取，
    Neo4j 驱动由构造函数传入或在调用时从 current_app 获取。
    LLM 通过 ``LanguageModelService.get_cheap_chat_model()`` 静态调用。
    """

    def __init__(
        self,
        neo4j_driver=None,
        config=None,
    ) -> None:
        """初始化冲突检测器。

        Args:
            neo4j_driver: Neo4j 驱动
            config: ConsolidationConfig 实例，None 时使用 settings.consolidation
        """
        self._driver = neo4j_driver
        self._config = config or settings.consolidation

    # =========================================================
    # 主入口
    # =========================================================

    def detect(self, user_id: str) -> dict:
        """批量检测用户的所有潜在冲突记忆对。

        Args:
            user_id: 用户标识

        Returns:
            ``{"count": int, "contradictions": int, "updates": int, "complements": int}``
        """
        stats = {
            "count": 0,
            "contradictions": 0,
            "updates": 0,
            "complements": 0,
        }

        driver = self._driver or self._get_driver()
        if driver is None:
            logger.warning("ConflictDetector.detect: Neo4j 不可用，跳过检测")
            return stats

        batch_size = self._config.conflict_check_batch_size

        # 查询用户的热 SemanticMemory 对（a.id < b.id）
        try:
            pairs = self._query_conflict_pairs(driver, user_id, batch_size)
        except Exception:
            logger.warning(
                "ConflictDetector.detect: 查询冲突对失败",
                exc_info=True,
            )
            return stats

        if not pairs:
            return stats

        for pair in pairs:
            try:
                conflict = self._detect_pair(
                    pair["a_id"],
                    pair["a_content"],
                    pair["b_id"],
                    pair["b_content"],
                    pair.get("a_created_at"),
                    pair.get("b_created_at"),
                )

                if conflict is None:
                    continue

                stats["count"] += 1

                # 执行解决
                self._resolve_conflict(driver, conflict, pair)

                # 累加计数
                if conflict.type == ConflictType.CONTRADICTION:
                    stats["contradictions"] += 1
                    MetricsCollector.record_conflict("contradiction")
                elif conflict.type == ConflictType.SUPERSEDE:
                    stats["updates"] += 1
                    MetricsCollector.record_conflict("update")
                elif conflict.type == ConflictType.REFINEMENT:
                    stats["complements"] += 1
                    MetricsCollector.record_conflict("complement")

            except Exception:
                logger.warning(
                    "ConflictDetector.detect: 检测单对失败 a=%s b=%s",
                    pair.get("a_id"),
                    pair.get("b_id"),
                    exc_info=True,
                )

        return stats

    # =========================================================
    # 单对检测
    # =========================================================

    def _detect_pair(
        self,
        a_id: str,
        a_content: str,
        b_id: str,
        b_content: str,
        a_ts=None,
        b_ts=None,
    ) -> Optional[ConflictResult]:
        """LLM 判定两条记忆的关系。

        置信度 < 0.7 返回 None（不处理）。

        Args:
            a_id: 记忆 A 的 ID
            a_content: 记忆 A 的内容
            b_id: 记忆 B 的 ID
            b_content: 记忆 B 的内容
            a_ts: 记忆 A 的时间戳
            b_ts: 记忆 B 的时间戳

        Returns:
            ConflictResult 或 None
        """
        prompt = _CONFLICT_DETECTION_PROMPT.format(
            memory_a=a_content[:500],
            memory_b=b_content[:500],
        )

        try:
            llm = LanguageModelService.get_feature_model("memory_conflict_detection")
            judgment = LLMActivityProbe.invoke_structured_with_probe(
                llm, _ConflictJudgment, prompt,
                feature_key="memory_conflict_detection",
            )
        except LLMActivityTimeoutError as exc:
            logger.warning(
                "_detect_pair: LLM 探针检测到死机，终止写入（不写垃圾）: %s",
                exc,
            )
            return None
        except Exception:
            logger.warning(
                "_detect_pair: LLM 判定失败 a=%s b=%s",
                a_id,
                b_id,
                exc_info=True,
            )
            return None

        # 置信度过滤
        if judgment.confidence < 0.7:
            return None

        # 类型映射
        type_map = {
            "contradiction": ConflictType.CONTRADICTION,
            "update": ConflictType.SUPERSEDE,
            "complement": ConflictType.REFINEMENT,
        }
        conflict_type = type_map.get(judgment.type.lower().strip())
        if conflict_type is None:
            return None

        return ConflictResult(
            conflict_id=uuid4(),
            type=conflict_type,
            entity_a=a_id,
            entity_b=b_id,
            similarity=judgment.confidence,
            resolution=judgment.explanation,
        )

    # =========================================================
    # 冲突解决
    # =========================================================

    def _resolve_conflict(self, driver, conflict: ConflictResult, pair: dict) -> None:
        """根据冲突类型执行解决操作。

        - CONTRADICTION: 旧节点 t_invalidated_at=now + status='deprecated'
        - UPDATE (SUPERSEDE): 旧节点 t_invalidated_at + SUPERSEDED_BY 边
        - COMPLEMENT (REFINEMENT): 创建双向 COMPLEMENTARY 边
        """
        now = datetime.utcnow()
        a_id = conflict.entity_a
        b_id = conflict.entity_b

        # 判断哪个是旧节点
        a_ts = pair.get("a_created_at")
        b_ts = pair.get("b_created_at")
        if a_ts and b_ts:
            # 比较时间戳，较早的为旧节点
            older_id = a_id if a_ts <= b_ts else b_id
            newer_id = b_id if a_ts <= b_ts else a_id
        else:
            # 无时间戳信息，默认 A 为旧节点
            older_id = a_id
            newer_id = b_id

        if conflict.type == ConflictType.CONTRADICTION:
            # 旧节点标记为废弃
            self._mark_deprecated(driver, older_id, now, conflict.resolution or "")

        elif conflict.type == ConflictType.SUPERSEDE:
            # 旧节点标记为被取代 + 创建 SUPERSEDED_BY 边
            self._mark_superseded(driver, older_id, newer_id, now)

        elif conflict.type == ConflictType.REFINEMENT:
            # 创建双向 COMPLEMENTARY 边
            self._create_complementary_edge(driver, a_id, b_id, conflict.similarity)

    # =========================================================
    # Neo4j 操作
    # =========================================================

    def _query_conflict_pairs(
        self,
        driver,
        user_id: str,
        batch_size: int,
    ) -> list[dict]:
        """查询用户的潜在冲突记忆对。

        查询 storage_tier='HOT' 或 IS NULL 的 SemanticMemory/Episode 对，
        a.node_id < b.node_id（避免重复对），LIMIT batch_size。

        过滤增强（记忆写入优化）:
            跳过已被写时冲突处理器标记的节点：
            - t_invalidated_at IS NOT NULL（已被 SUPERSEDE/CONTRADICTION 标记失效）
            - status IN ['superseded', 'deprecated']（已被标记为废弃）
        """
        cypher = """
        MATCH (a), (b)
        WHERE a.user_id = $user_id
          AND b.user_id = $user_id
          AND a.node_id < b.node_id
          AND (a.storage_tier IS NULL OR a.storage_tier IN ['hot', 'warm'])
          AND (b.storage_tier IS NULL OR b.storage_tier IN ['hot', 'warm'])
          AND a.is_active = true
          AND b.is_active = true
          AND a.content IS NOT NULL
          AND b.content IS NOT NULL
          AND a.t_invalidated_at IS NULL
          AND b.t_invalidated_at IS NULL
          AND (a.status IS NULL OR NOT (a.status IN ['superseded', 'deprecated']))
          AND (b.status IS NULL OR NOT (b.status IN ['superseded', 'deprecated']))
        WITH a, b
        LIMIT $batch_size
        RETURN a.node_id AS a_id,
               a.content AS a_content,
               a.created_at AS a_created_at,
               b.node_id AS b_id,
               b.content AS b_content,
               b.created_at AS b_created_at
        """
        with driver.session() as session:
            result = session.run(
                cypher,
                {"user_id": user_id, "batch_size": batch_size},
            )
            return [dict(record) for record in result]

    def _mark_deprecated(
        self,
        driver,
        node_id: str,
        now: datetime,
        reason: str,
    ) -> None:
        """标记节点为废弃（CONTRADICTION 解决）。"""
        cypher = """
        MATCH (n {node_id: $node_id})
        SET n.status = 'deprecated',
            n.deprecated_reason = $reason,
            n.deprecated_at = $now,
            n.t_invalidated_at = $now,
            n.is_active = false
        """
        with driver.session() as session:
            session.run(
                cypher,
                {
                    "node_id": node_id,
                    "reason": reason[:500],
                    "now": now.isoformat(),
                },
            ).consume()

    def _mark_superseded(
        self,
        driver,
        older_id: str,
        newer_id: str,
        now: datetime,
    ) -> None:
        """标记旧节点为被取代 + 创建 SUPERSEDED_BY 边（UPDATE 解决）。"""
        # 1. 旧节点标记
        cypher_mark = """
        MATCH (n {node_id: $node_id})
        SET n.status = 'superseded',
            n.superseded_by = $newer_id,
            n.t_invalidated_at = $now,
            n.is_active = false
        """
        with driver.session() as session:
            session.run(
                cypher_mark,
                {
                    "node_id": older_id,
                    "newer_id": newer_id,
                    "now": now.isoformat(),
                },
            ).consume()

        # 2. 创建 SUPERSEDED_BY 边
        cypher_edge = """
        MATCH (older {node_id: $older_id}), (newer {node_id: $newer_id})
        CREATE (older)-[:SUPERSEDED_BY {
            edge_id: $edge_id,
            created_at: $now,
            is_active: true
        }]->(newer)
        """
        with driver.session() as session:
            session.run(
                cypher_edge,
                {
                    "older_id": older_id,
                    "newer_id": newer_id,
                    "edge_id": str(uuid4()),
                    "now": now.isoformat(),
                },
            ).consume()

    def _create_complementary_edge(
        self,
        driver,
        a_id: str,
        b_id: str,
        confidence: float,
    ) -> None:
        """创建双向 COMPLEMENTARY 边（COMPLEMENT 解决）。"""
        now = datetime.utcnow()
        cypher = """
        MATCH (a {node_id: $a_id}), (b {node_id: $b_id})
        CREATE (a)-[:COMPLEMENTARY {
            edge_id: $edge_id_1,
            confidence: $confidence,
            created_at: $now,
            is_active: true
        }]->(b)
        CREATE (b)-[:COMPLEMENTARY {
            edge_id: $edge_id_2,
            confidence: $confidence,
            created_at: $now,
            is_active: true
        }]->(a)
        """
        with driver.session() as session:
            session.run(
                cypher,
                {
                    "a_id": a_id,
                    "b_id": b_id,
                    "edge_id_1": str(uuid4()),
                    "edge_id_2": str(uuid4()),
                    "confidence": confidence,
                    "now": now.isoformat(),
                },
            ).consume()

    # =========================================================
    # 辅助
    # =========================================================

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
