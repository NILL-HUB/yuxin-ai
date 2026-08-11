"""记忆写入编排服务（MemoryWriteService）。

封装从 ``MemoryEvent`` 到最终写入 Neo4j + pgvector 的完整编排逻辑，
供 API 端点（A4 MemoryHandler）和对话后自动触发（A5）复用。

三层决策架构（记忆写入优化）:
    1. ExplicitStatementDetector：显式陈述检测（正则预筛 + LLM 确认）
    2. WriteTimeConflictResolver：写时冲突解决（复用四时间戳模型）
    3. SalienceScorer：六因子显著性评分（含 explicitness 因子）

决策路径:
    - confidence >= fast_path_threshold (0.85)：快路径，直接 FULL 写入（跳过 SalienceScorer）
    - boost_threshold (0.5) <= confidence < fast_path_threshold：拉高路径，
      explicitness=0.8 走 6 因子评分
    - confidence < boost_threshold：非显式，explicitness=0.0 走 6 因子评分

核心流程:
    MemoryEvent → 三层决策 → 按 WritePath 分流:
    - FULL:    embed 原文 + 抽取实体/关系 → LedgerWriter.write_full_path()
    - SUMMARY: 生成摘要 + embed 摘要 + 抽取实体/关系(≤5) → LedgerWriter.write_summary_path()
    - SKETCH:  仅抽取实体(轻量) → LedgerWriter.write_stats_path()

降级策略:
    全程异常捕获，任一环节失败时记 warning 日志并返回 None，不影响主流程。
    由 ``settings.memory_engine_enabled`` 总开关控制是否执行写入。
"""

import logging
from datetime import UTC, datetime
from typing import Any, Optional
from uuid import uuid4

from dataclasses import dataclass
from injector import inject

from internal.config.memory_settings import settings
from internal.model.memory_models import (
    EventSource,
    ExplicitCategory,
    ExplicitDetectionResult,
    MemoryEvent,
    WritePath,
)
from internal.service.embeddings_service import EmbeddingsService
from internal.service.memory.entity_extractor import MemoryEntityExtractor
from internal.service.memory.explicit_detector import ExplicitStatementDetector
from internal.service.memory.ledger_writer import LedgerWriter
from internal.service.memory.salience_scorer import SalienceScorer
from internal.service.memory.write_time_conflict_resolver import WriteTimeConflictResolver

logger = logging.getLogger(__name__)


@inject
@dataclass
class MemoryWriteService:
    """记忆写入编排服务。

    依赖注入:
        salience_scorer: 显著性评分器
        ledger_writer:   权威账本写入器
        embeddings_service: 文本向量化服务
        entity_extractor:   LLM 实体/关系抽取 + 摘要生成
        explicit_detector:  显式陈述检测器（三层决策第一层）
        conflict_resolver:  写时冲突解决器（三层决策第二层）
    """

    salience_scorer: SalienceScorer
    ledger_writer: LedgerWriter
    embeddings_service: EmbeddingsService
    entity_extractor: MemoryEntityExtractor
    explicit_detector: ExplicitStatementDetector
    conflict_resolver: WriteTimeConflictResolver

    # =========================================================
    # 对话后自动触发入口（A5 调用）
    # =========================================================

    def write_from_conversation(
        self,
        account,
        query: str,
        ai_response: str,
        conversation_id: str,
    ) -> Optional[dict[str, Any]]:
        """从对话内容构建 MemoryEvent 并写入。

        Args:
            account: 用户账号对象（需有 ``id`` 属性）
            query: 用户提问
            ai_response: AI 回答
            conversation_id: 会话 ID

        Returns:
            写入结果摘要 dict；降级或失败时返回 None。
        """
        if not settings.memory_engine_enabled:
            logger.warning("记忆引擎已禁用（memory_engine_enabled=False），跳过写入")
            return None

        if not query or not ai_response:
            return None

        content = f"User: {query}\nAssistant: {ai_response}"
        event = MemoryEvent(
            event_id=uuid4(),
            timestamp=datetime.now(UTC),
            source=EventSource.USER_MESSAGE,
            content=content,
            context_messages=[],
            metadata={
                "query": query,
                "conversation_id": conversation_id,
            },
            session_id=str(conversation_id),
            user_id=str(account.id),
        )

        return self.write_from_event(event)

    # =========================================================
    # 核心写入编排（A4 / A5 共用）
    # =========================================================

    def write_from_event(self, event: MemoryEvent) -> Optional[dict[str, Any]]:
        """对事件执行三层决策并按写入路径写入 Neo4j + pgvector。

        三层决策架构:
            1. ExplicitStatementDetector.detect() → ExplicitDetectionResult
            2. WriteTimeConflictResolver.resolve() → 写时冲突解决
            3. SalienceScorer.score(explicitness) → 六因子评分（快路径跳过）

        Args:
            event: 已构建的记忆事件。

        Returns:
            写入结果 dict，含 ``status`` / ``memory_id`` / ``created_at`` / ``score``；
            降级或失败时返回 None。
        """
        if not settings.memory_engine_enabled:
            logger.warning("记忆引擎已禁用，跳过写入")
            return None

        try:
            # ===== 三层决策第一层：显式陈述检测 =====
            detection = self.explicit_detector.detect(event)
            logger.info(
                "显式检测完成: user=%s is_explicit=%s category=%s confidence=%.2f",
                event.user_id,
                detection.is_explicit,
                detection.category.value if detection.category else None,
                detection.confidence,
            )

            # ===== 三层决策第二层：写时冲突解决 =====
            conflict_result = self.conflict_resolver.resolve(event, detection)
            if conflict_result.conflict_detected:
                logger.info(
                    "写时冲突解决: type=%s resolved=%d superseded=%s",
                    conflict_result.conflict_type,
                    conflict_result.resolved_count,
                    conflict_result.superseded_ids,
                )

            # ===== 种子提示注册（显式 capability 类陈述 → SkillEmergence 种子） =====
            if (
                detection.is_explicit
                and detection.category == ExplicitCategory.CAPABILITY
                and detection.subject
            ):
                self._register_capability_seed_hint(event, detection)

            # ===== 三层决策第三层：显著性评分（含 explicitness） =====
            cfg = settings.explicit_detection
            explicitness = 0.0
            fast_path = False

            if detection.is_explicit:
                if detection.confidence >= cfg.fast_path_threshold:
                    # 快路径：跳过 SalienceScorer，直接 FULL 写入
                    fast_path = True
                    write_path = WritePath.FULL
                    salience_total = None
                    logger.info(
                        "快路径触发: confidence=%.2f >= %.2f，直接 FULL 写入",
                        detection.confidence,
                        cfg.fast_path_threshold,
                    )
                elif detection.confidence >= cfg.boost_threshold:
                    # 拉高路径：explicitness=0.8，走 6 因子评分
                    explicitness = 0.8

            if not fast_path:
                salience_result = self.salience_scorer.score(
                    event, explicitness=explicitness
                )
                write_path = salience_result.write_path
                salience_total = salience_result.total_score
                logger.info(
                    "记忆评分完成: user=%s score=%.4f path=%s explicitness=%.2f",
                    event.user_id,
                    salience_result.total_score,
                    write_path.value,
                    explicitness,
                )

            # ===== 按路径分流写入 =====
            if write_path == WritePath.FULL:
                result = self._write_full(event, detection)
            elif write_path == WritePath.SUMMARY:
                result = self._write_summary(event)
            elif write_path == WritePath.SKETCH:
                result = self._write_sketch(event)
            else:
                # WritePath.REJECT 或未知路径：不写入
                logger.info("写入路径 %s，跳过写入", write_path.value)
                return {
                    "status": "rejected",
                    "memory_id": None,
                    "created_at": datetime.now(UTC).isoformat(),
                    "score": salience_total,
                }

            if result is None:
                return None

            result.setdefault("status", write_path.value)
            result.setdefault("created_at", datetime.now(UTC).isoformat())
            result["score"] = salience_total if salience_total is not None else 1.0
            # 附加显式检测与冲突解决元数据
            result["explicit_detection"] = {
                "is_explicit": detection.is_explicit,
                "category": detection.category.value if detection.category else None,
                "polarity": detection.polarity.value,
                "confidence": detection.confidence,
                "fallback_used": detection.fallback_used,
            }
            result["conflict_resolution"] = {
                "conflict_detected": conflict_result.conflict_detected,
                "conflict_type": conflict_result.conflict_type,
                "resolved_count": conflict_result.resolved_count,
                "superseded_ids": conflict_result.superseded_ids,
            }
            return result

        except Exception:
            logger.warning(
                "记忆写入失败，不影响主流程: user=%s",
                event.user_id,
                exc_info=True,
            )
            return None

    # =========================================================
    # 三条写入路径
    # =========================================================

    def _write_full(
        self,
        event: MemoryEvent,
        explicit_detection: Optional[ExplicitDetectionResult] = None,
    ) -> Optional[dict[str, Any]]:
        """FULL 路径：embed 原文 + 全量实体/关系抽取 + 写入。

        Args:
            event: 记忆事件
            explicit_detection: 显式陈述检测结果（可选），传递给 LedgerWriter
                用于实体种子注入与 explicit_* 属性写入
        """
        # 1. 生成原文向量
        embedding = self._embed_text(event.content)
        if not embedding:
            logger.warning("FULL 路径：向量生成失败，降级为空向量")
            embedding = []

        # 2. 抽取实体与关系
        entities, relations = self.entity_extractor.extract_entities_and_relations(
            event.content
        )

        # 3. 写入（携带显式检测结果用于实体种子注入）
        result = self.ledger_writer.write_full_path(
            event=event,
            entities=entities,
            relations=relations,
            embedding=embedding,
            explicit_detection=explicit_detection,
        )
        return result

    def _write_summary(self, event: MemoryEvent) -> Optional[dict[str, Any]]:
        """SUMMARY 路径：生成摘要 + embed 摘要 + 截断实体/关系(≤5) + 写入。"""
        # 1. 生成摘要
        summary = self.entity_extractor.generate_summary(event.content)
        if not summary:
            summary = event.content[:200]

        # 2. 生成摘要向量
        embedding = self._embed_text(summary)
        if not embedding:
            logger.warning("SUMMARY 路径：向量生成失败，降级为空向量")
            embedding = []

        # 3. 抽取实体与关系（截断为 5）
        entities, relations = self.entity_extractor.extract_entities_and_relations(
            event.content,
            max_entities=5,
        )

        # 4. 写入
        result = self.ledger_writer.write_summary_path(
            event=event,
            summary=summary,
            entities=entities,
            relations=relations,
            embedding=embedding,
        )
        return result

    def _write_sketch(self, event: MemoryEvent) -> Optional[dict[str, Any]]:
        """SKETCH 路径：仅抽取实体 + 更新统计计数。"""
        # 仅抽取实体（不抽关系，轻量）
        entities, _ = self.entity_extractor.extract_entities_and_relations(
            event.content,
            max_entities=10,
        )

        result = self.ledger_writer.write_stats_path(
            event=event,
            entities=entities,
        )
        return result

    # =========================================================
    # 辅助方法
    # =========================================================

    def _embed_text(self, text: str) -> list[float]:
        """调用 EmbeddingsService 生成文本向量。

        失败时返回空列表（LedgerWriter 会跳过向量写入）。
        """
        if not text:
            return []
        try:
            return self.embeddings_service.embeddings.embed_query(text)
        except Exception:
            logger.warning("向量生成失败，返回空列表", exc_info=True)
            return []

    def _register_capability_seed_hint(
        self,
        event: MemoryEvent,
        detection: ExplicitDetectionResult,
    ) -> None:
        """显式 capability 类陈述 → SkillEmergence 种子提示（不创建 Skill 节点）。

        通过 current_app 获取 Neo4j 驱动与 Redis 客户端，懒构造 SkillEmergence
        实例并调用 register_seed_hint()。任一环节失败仅记 warning，不影响主流程。

        设计参考: docs/prd/memory-write-optimization-design.md §5.7
        """
        try:
            from internal.context import current_app

            from internal.service.memory.skill_emergence import SkillEmergence

            neo4j_driver = current_app.extensions.get("neo4j")
            redis_client = current_app.extensions.get("redis")
            if redis_client is None:
                logger.warning("种子提示注册跳过: Redis 不可用")
                return

            emergence = SkillEmergence(
                neo4j_driver=neo4j_driver,
                redis_client=redis_client,
            )
            polarity = detection.polarity.value if detection.polarity else "positive"
            emergence.register_seed_hint(
                user_id=event.user_id,
                skill_name=detection.subject or "",
                polarity=polarity,
                source="explicit_statement",
            )
        except Exception:
            logger.warning(
                "种子提示注册失败，不影响主流程: user=%s subject=%s",
                event.user_id,
                detection.subject,
                exc_info=True,
            )
