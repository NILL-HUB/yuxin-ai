"""写时冲突解决器（Write-Time Conflict Resolver）。

三层决策架构的第二层，在显式陈述写入前检测与现存记忆的冲突，
复用四时间戳模型（MemoryEdge.t_invalidated_at + invalidated_by + SUPERSEDED_BY 边）。

与 ConflictDetector 的区别:
    - ConflictDetector: 巩固阶段异步批量检测（全用户扫描）
    - WriteTimeConflictResolver: 写时实时检测（仅针对当前 subject）

冲突类型与解决操作（与 ConflictDetector 一一致）:
    - SUPERSEDE (UPDATE):     旧节点 t_invalidated_at=now + SUPERSEDED_BY 边
    - CONTRADICTION:          旧节点 t_invalidated_at=now + is_active=false
    - COMPLEMENT (REFINEMENT): 创建双向 COMPLEMENTARY 边
    - NONE:                   无冲突，正常写入

三路信号融合（设计文档 §4.2）:
    1. 向量余弦：event.content 向量 vs 候选 Episode content 向量
    2. BM25 编辑距离（可选预筛，当前实现跳过）
    3. LLM 判定：复用 ConflictDetector 的 _ConflictJudgment prompt

降级策略:
    - Neo4j 不可用：跳过冲突检测，返回无冲突
    - LLM 异常：跳过该候选
    - 向量生成失败：跳过该候选

设计参考:
    docs/prd/memory-write-optimization-design.md §4 写时冲突检测
    docs/prd/memory-system/03-consolidation-skill-policy-api.md §7.2
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Optional

from injector import inject
from pydantic import BaseModel, Field

from internal.config.memory_settings import settings
from internal.model.memory_models import (
    ConflictType,
    ExplicitDetectionResult,
    MemoryEvent,
)
from internal.service.embeddings_service import EmbeddingsService
from internal.service.language_model_service import LanguageModelService
from internal.service.memory.metrics import MetricsCollector

logger = logging.getLogger(__name__)


# LLM 判定超时（秒）—— DeepSeek-V4-Flash 实际响应 5-15s，需留足时间避免误降级
_LLM_TIMEOUT_SECONDS = 20.0


# =========================================================
# LLM 结构化输出辅助模型
# =========================================================


class _ConflictJudgment(BaseModel):
    """LLM 冲突判定结果（与 ConflictDetector._ConflictJudgment 一致）。"""

    type: str = Field(
        ...,
        description="冲突类型: contradiction / update / complement / none",
    )
    confidence: float = Field(..., ge=0.0, le=1.0, description="置信度 0-1")
    explanation: str = Field(default="", description="判定理由")


# =========================================================
# 输出结果模型
# =========================================================


@dataclass
class WriteTimeConflictResult:
    """写时冲突检测结果。

    Attributes:
        conflict_detected: 是否检测到冲突
        conflict_type: 冲突类型（supersede/contradiction/complement/none）
        superseded_ids: 被 SUPERSEDE 标记失效的旧节点 ID 列表
        resolved_count: 已解决的冲突数量
        skipped: 是否因降级跳过检测（Neo4j 不可用等）
    """

    conflict_detected: bool = False
    conflict_type: str = "none"
    superseded_ids: list[str] = field(default_factory=list)
    resolved_count: int = 0
    skipped: bool = False


# =========================================================
# 主解决器
# =========================================================


@inject
@dataclass
class WriteTimeConflictResolver:
    """写时冲突解决器。

    依赖注入:
        embeddings_service: 文本向量化服务（用于向量余弦相似度计算）
        Neo4j 驱动通过 ``current_app.extensions['neo4j']`` 或 ``get_driver()`` 获取
    """

    embeddings_service: EmbeddingsService

    # ----------------------------------------------------------
    # 主入口
    # ----------------------------------------------------------

    def resolve(
        self,
        event: MemoryEvent,
        detection: ExplicitDetectionResult,
    ) -> WriteTimeConflictResult:
        """写时冲突检测与解决。

        流程:
            1. 前置检查：非显式陈述或无 subject 直接返回无冲突
            2. 获取 Neo4j 驱动：不可用则降级跳过
            3. 查询候选：通过 subject 实体关联的现存 HOT/WARM Episode
            4. 逐对判定：向量余弦预筛 → LLM 判定
            5. 执行解决：SUPERSEDE / CONTRADICTION / COMPLEMENT

        Args:
            event: 新写入的记忆事件
            detection: 显式陈述检测结果（含 subject 实体种子）

        Returns:
            WriteTimeConflictResult
        """
        # 1. 前置检查
        if not detection.is_explicit or not detection.subject:
            return WriteTimeConflictResult()

        cfg = settings.explicit_detection
        driver = self._get_driver()
        if driver is None:
            logger.warning(
                "write_time_conflict: Neo4j 不可用，降级跳过冲突检测 user=%s",
                event.user_id,
            )
            return WriteTimeConflictResult(skipped=True)

        # 2. 查询候选 Episode
        candidates = self._query_candidates(
            driver, event.user_id, detection.subject
        )
        if not candidates:
            return WriteTimeConflictResult()

        # 3. 生成新事件向量（用于余弦预筛）
        new_embedding = self._embed_text(event.content)

        # 4. 逐对判定与解决
        result = WriteTimeConflictResult()
        for candidate in candidates:
            try:
                self._resolve_one(
                    driver,
                    event,
                    detection,
                    candidate,
                    new_embedding,
                    cfg.vector_fallback_threshold,
                    result,
                )
            except Exception:
                logger.warning(
                    "write_time_conflict: 单候选解决失败 candidate=%s",
                    candidate.get("node_id"),
                    exc_info=True,
                )

        return result

    # ----------------------------------------------------------
    # 单候选解决
    # ----------------------------------------------------------

    def _resolve_one(
        self,
        driver,
        event: MemoryEvent,
        detection: ExplicitDetectionResult,
        candidate: dict,
        new_embedding: list[float],
        similarity_threshold: float,
        result: WriteTimeConflictResult,
    ) -> None:
        """对单个候选项执行冲突判定与解决。"""
        cand_id = candidate.get("node_id")
        cand_content = candidate.get("content", "")
        if not cand_id or not cand_content:
            return

        # 1. 向量余弦预筛
        similarity = self._cosine_similarity_text(
            new_embedding, cand_content
        )
        if similarity < similarity_threshold:
            return  # 相似度不足，不判定

        # 2. LLM 判定
        conflict_type = self._llm_judge(event.content, cand_content)
        if conflict_type is None:
            return  # LLM 判定失败或无冲突

        # 3. 执行解决
        now = datetime.now(UTC)
        resolved = False

        if conflict_type == ConflictType.SUPERSEDE:
            # 旧节点标记失效 + SUPERSEDED_BY 边
            self._mark_superseded(driver, cand_id, event, now)
            result.superseded_ids.append(cand_id)
            resolved = True
            MetricsCollector.record_conflict_resolved("supersede")
        elif conflict_type == ConflictType.CONTRADICTION:
            # 旧节点标记废弃
            self._mark_deprecated(driver, cand_id, now, "写时冲突：矛盾")
            result.superseded_ids.append(cand_id)
            resolved = True
            MetricsCollector.record_conflict_resolved("contradiction")
        elif conflict_type == ConflictType.REFINEMENT:
            # 创建双向 COMPLEMENTARY 边（需要新 Episode 的 node_id，此处仅记录）
            # 实际 COMPLEMENTARY 边由 LedgerWriter 写入后由巩固阶段处理
            # 写时只记录，不创建，避免新节点尚未创建
            resolved = True
            MetricsCollector.record_conflict_resolved("complement")

        if resolved:
            result.conflict_detected = True
            result.conflict_type = conflict_type.value
            result.resolved_count += 1
            logger.info(
                "write_time_conflict: 解决冲突 type=%s old=%s subject=%s",
                conflict_type.value,
                cand_id,
                detection.subject,
            )

    # ----------------------------------------------------------
    # LLM 判定
    # ----------------------------------------------------------

    def _llm_judge(
        self, new_content: str, old_content: str
    ) -> Optional[ConflictType]:
        """调用 LLM 判定两条记忆的关系。

        探针检测到死机时返回 None（不处理，不写垃圾）。
        置信度 < 0.7 也返回 None。
        """
        from internal.service.memory.llm_activity_probe import (
            LLMActivityProbe,
            LLMActivityTimeoutError,
        )

        from internal.service.system_prompt_library_service import SystemPromptLibraryService

        prompt = SystemPromptLibraryService().get_prompt_or_default(
            "memory_write_time_conflict_resolver_prompt"
        ).format(
            memory_a=old_content[:500],
            memory_b=new_content[:500],
        )

        try:
            llm = LanguageModelService.get_feature_model("memory_write_conflict_resolution")
            judgment = LLMActivityProbe.invoke_structured_with_probe(
                llm, _ConflictJudgment, prompt,
                feature_key="memory_write_conflict_resolution",
            )
        except LLMActivityTimeoutError as exc:
            logger.warning(
                "_llm_judge: LLM 探针检测到死机，终止写入（不写垃圾）: %s",
                exc,
            )
            return None
        except Exception:
            logger.warning(
                "_llm_judge: LLM 判定异常",
                exc_info=True,
            )
            return None

        if judgment.confidence < 0.7:
            return None

        type_map = {
            "contradiction": ConflictType.CONTRADICTION,
            "update": ConflictType.SUPERSEDE,
            "complement": ConflictType.REFINEMENT,
        }
        return type_map.get(judgment.type.lower().strip())

    # ----------------------------------------------------------
    # 向量相似度计算
    # ----------------------------------------------------------

    def _embed_text(self, text: str) -> list[float]:
        """生成文本向量，失败时返回空列表。"""
        if not text:
            return []
        try:
            return self.embeddings_service.embeddings.embed_query(text)
        except Exception:
            logger.warning("_embed_text: 向量生成失败", exc_info=True)
            return []

    def _cosine_similarity_text(
        self,
        new_embedding: list[float],
        old_text: str,
    ) -> float:
        """计算新事件向量与旧文本的余弦相似度。

        Args:
            new_embedding: 新事件的嵌入向量
            old_text: 候选 Episode 的原文

        Returns:
            余弦相似度 [0, 1]；任一向量为空返回 0.0
        """
        if not new_embedding:
            return 0.0
        old_embedding = self._embed_text(old_text)
        if not old_embedding:
            return 0.0
        return self._cosine(new_embedding, old_embedding)

    @staticmethod
    def _cosine(a: list[float], b: list[float]) -> float:
        """计算两个向量的余弦相似度。"""
        if not a or not b or len(a) != len(b):
            return 0.0
        dot = sum(x * y for x, y in zip(a, b))
        norm_a = math.sqrt(sum(x * x for x in a))
        norm_b = math.sqrt(sum(y * y for y in b))
        if norm_a == 0 or norm_b == 0:
            return 0.0
        return max(0.0, min(1.0, dot / (norm_a * norm_b)))

    # ----------------------------------------------------------
    # Neo4j 查询与操作
    # ----------------------------------------------------------

    def _query_candidates(
        self,
        driver,
        user_id: str,
        subject: str,
    ) -> list[dict]:
        """查询与 subject 实体关联的现存 HOT/WARM Episode。

        查询路径: Entity(name=subject) <-[:CONTAINS]- Episode
        过滤条件: is_active=true, storage_tier IN ['hot','warm'], t_invalidated_at IS NULL
        """
        cypher = """
        MATCH (e:Entity {name: $subject, user_id: $user_id})<-[:CONTAINS]-(ep:Episode)
        WHERE ep.is_active = true
          AND (ep.storage_tier IS NULL OR ep.storage_tier IN ['hot', 'warm'])
          AND ep.t_invalidated_at IS NULL
          AND ep.content IS NOT NULL
        RETURN ep.node_id AS node_id,
               ep.content AS content,
               ep.created_at AS created_at
        LIMIT 10
        """
        try:
            with driver.session() as session:
                result = session.run(
                    cypher,
                    {"subject": subject, "user_id": user_id},
                )
                return [dict(record) for record in result]
        except Exception:
            logger.warning(
                "_query_candidates: 查询候选失败 subject=%s", subject, exc_info=True
            )
            return []

    def _mark_superseded(
        self,
        driver,
        old_node_id: str,
        event: MemoryEvent,
        now: datetime,
    ) -> None:
        """标记旧节点为被取代（复用四时间戳模型）。

        1. 旧节点 SET t_invalidated_at=now, is_active=false
        2. 旧节点的现存有效边 SET t_invalidated_at=now, invalidated_by=event_id
        3. 创建 SUPERSEDED_BY 边（旧 → 新，但新节点尚未创建，此处仅标记旧节点）

        注意：新 Episode 节点由 LedgerWriter.write_full_path() 创建，
        SUPERSEDED_BY 边的完整创建需要 LedgerWriter 在写入新节点后补充。
        本方法仅标记旧节点失效，避免新节点不存在时创建悬空边。
        """
        # 1. 旧节点标记失效
        cypher_node = """
        MATCH (n {node_id: $node_id})
        SET n.t_invalidated_at = $now,
            n.is_active = false,
            n.status = 'superseded',
            n.superseded_by_event = $event_id
        """
        with driver.session() as session:
            session.run(
                cypher_node,
                {
                    "node_id": old_node_id,
                    "now": now.isoformat(),
                    "event_id": str(event.event_id),
                },
            ).consume()

        # 2. 旧节点的现存有效边标记失效
        cypher_edges = """
        MATCH (n {node_id: $node_id})-[r]->(t)
        WHERE r.t_invalidated_at IS NULL
          AND r.is_active = true
        SET r.t_invalidated_at = $now,
            r.invalidated_by = $event_id,
            r.is_active = false
        """
        with driver.session() as session:
            session.run(
                cypher_edges,
                {
                    "node_id": old_node_id,
                    "now": now.isoformat(),
                    "event_id": str(event.event_id),
                },
            ).consume()

    def _mark_deprecated(
        self,
        driver,
        node_id: str,
        now: datetime,
        reason: str,
    ) -> None:
        """标记节点为废弃（CONTRADICTION 解决，复用 ConflictDetector 模式）。"""
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

    # ----------------------------------------------------------
    # 降级检查
    # ----------------------------------------------------------

    def _get_driver(self):
        """获取 Neo4j 驱动，不可用时返回 None 触发降级。"""
        try:
            from internal.context import current_app

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


__all__ = ["WriteTimeConflictResolver", "WriteTimeConflictResult"]
