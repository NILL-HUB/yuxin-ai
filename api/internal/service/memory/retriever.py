"""混合检索器（MemoryRetriever）。

融合语义/关键词/图三通道，实现 System 1（Digest 缓存快速路径）与
System 2（TKG 粗召回 + 向量精召回 + 图扩展 + 混合评分 + 早停）的双路架构。

双路架构:
    - System 1: Digest 缓存命中时直接返回，不触发深度搜索
    - System 2: TKG BM25 粗召回 → pgvector 向量精召回 → SpreadActivation 图扩展
                → 混合评分 → 时间衰减 → 早停截断

降级策略:
    - Neo4j 不可用时 TKG 召回返回空列表
    - pgvector 不可用时向量召回返回空列表
    - EmbeddingsService 不可用时向量召回跳过
    - System 1 未命中时自动降级到 System 2

设计参考:
    docs/prd/memory-system/02-storage-and-retrieval.md §6.2
    docs/prd/memory-system/execution/03-track-b-storage-retrieval.md B3
"""

from __future__ import annotations

import logging
import math
from datetime import datetime, timezone
from typing import Optional

from internal.config.memory_settings import settings
from internal.model.memory_models import (
    RetrievalConfig,
    RetrievalOptions,
    RetrievalResult,
    RetrievalScore,
    SpreadConfig,
)
from internal.service.memory.spread_activation import SpreadActivation
from internal.service.memory.metrics import MetricsCollector

logger = logging.getLogger(__name__)


class MemoryRetriever:
    """混合检索器 System 1/2 双路。

    不使用 ``@inject``：无注入依赖，配置从 ``settings.retrieval`` 读取，
    Neo4j 驱动与 SQLAlchemy db 由构造函数传入或运行时获取。
    EmbeddingsService 通过 ``current_app.injector`` 获取。
    """

    def __init__(
        self,
        neo4j_driver=None,
        db=None,
        config: Optional[RetrievalConfig] = None,
        embeddings_service=None,
        digest_manager=None,
    ) -> None:
        """初始化混合检索器。

        Args:
            neo4j_driver: Neo4j 驱动
            db: SQLAlchemy 实例
            config: RetrievalConfig 实例，None 时使用 settings.retrieval
            embeddings_service: EmbeddingsService 实例（用于查询向量化）
            digest_manager: DigestManager 实例（System 1 快速路径用）
        """
        self._driver = neo4j_driver
        self._db = db
        self._config = config or settings.retrieval
        self._embeddings_service = embeddings_service
        self._digest_manager = digest_manager

    # =========================================================
    # 主入口
    # =========================================================

    def retrieve(
        self,
        query: str,
        user_id: str,
        options: Optional[RetrievalOptions] = None,
    ) -> list[RetrievalResult]:
        """主检索入口，先尝试 System 1 快速路径，未命中则走 System 2 深度搜索。

        Args:
            query: 查询文本
            user_id: 用户标识
            options: 检索选项，None 时使用默认值

        Returns:
            检索结果列表
        """
        import time as _time

        start = _time.perf_counter()

        if not query or not query.strip():
            MetricsCollector.record_retrieve(_time.perf_counter() - start, 0)
            return []

        if options is None:
            options = RetrievalOptions()

        # System 1 快速路径
        fast_result = self._system1_fast_path(query, user_id)
        if fast_result is not None:
            results = [
                RetrievalResult(
                    memory_id="digest",
                    content=fast_result,
                    score=1.0,
                    source="digest_cache",
                )
            ]
            MetricsCollector.record_retrieve(_time.perf_counter() - start, len(results))
            return results

        # System 2 深度搜索
        results = self._system2_deep_search(query, user_id, options)
        MetricsCollector.record_retrieve(_time.perf_counter() - start, len(results))
        return results

    # =========================================================
    # System 1: Digest 缓存快速路径
    # =========================================================

    def _system1_fast_path(self, query: str, user_id: str) -> Optional[str]:
        """检查 Digest 缓存是否足够，足够则直接返回。

        本任务简化实现：若 digest_manager 可用，则返回 Digest 文本作为
        快速路径结果。由 B8 集成后注入真实 DigestManager。

        Args:
            query: 查询文本
            user_id: 用户标识

        Returns:
            Digest 文本或 None
        """
        if self._digest_manager is None:
            return None

        try:
            digest_text = self._digest_manager.get_digest(user_id)
            if digest_text and len(digest_text) > 50:
                return digest_text
        except Exception:
            logger.warning(
                "_system1_fast_path: Digest 获取失败 user=%s", user_id, exc_info=True
            )

        return None

    # =========================================================
    # System 2: 深度搜索
    # =========================================================

    def _system2_deep_search(
        self,
        query: str,
        user_id: str,
        options: RetrievalOptions,
    ) -> list[RetrievalResult]:
        """TKG 粗召回 + 向量精召回 + 图扩展 + 混合评分 + 早停。

        步骤:
            ① TKG BM25 粗召回 → all_candidates dict
            ② 向量精召回 → 合并候选（同 id 取最大分，标记 hybrid）
            ③ 图扩展 → 新增节点加入候选
            ④ 混合评分 + 时间衰减 → 最终 score
            ⑤ 排序 + 早停截断
        """
        top_k = options.top_k
        recall_k = top_k * 2

        # ① TKG BM25 粗召回
        all_candidates: dict[str, RetrievalResult] = {}
        tkg_results = self._tkg_recall(query, user_id, recall_k)
        for result in tkg_results:
            all_candidates[result.memory_id] = result

        # ② 向量精召回
        query_embedding = self._embed_query(query)
        if query_embedding:
            vector_results = self._vector_recall(query_embedding, user_id, recall_k)
            for result in vector_results:
                mem_id = result.memory_id
                if mem_id in all_candidates:
                    # 合并：取最大分，标记 hybrid
                    existing = all_candidates[mem_id]
                    max_score = max(existing.score, result.score)
                    merged = RetrievalResult(
                        memory_id=mem_id,
                        content=result.content or existing.content,
                        score=max_score,
                        source="hybrid",
                        timestamp=result.timestamp,
                        metadata={**existing.metadata, **result.metadata},
                    )
                    merged.score_breakdown = RetrievalScore(
                        semantic=result.score,
                        keyword=existing.score,
                        total=max_score,
                    )
                    all_candidates[mem_id] = merged
                else:
                    all_candidates[mem_id] = result

        # ③ 图扩展
        if all_candidates:
            start_ids = list(all_candidates.keys())[:5]
            spread_results = self._graph_spread(start_ids, top_k=options.top_k)
            for node_id, activation in spread_results:
                if node_id not in all_candidates:
                    # 获取节点数据
                    node_data = self._get_node_data(node_id)
                    if node_data:
                        all_candidates[node_id] = RetrievalResult(
                            memory_id=node_id,
                            content=node_data.get("content", ""),
                            score=activation * 0.8,
                            source="graph_spread",
                            timestamp=node_data.get("timestamp", datetime.utcnow()),
                        )

        if not all_candidates:
            return []

        # ④ 混合评分 + 时间衰减
        query_text = query
        scored: list[RetrievalResult] = []
        for result in all_candidates.values():
            hybrid = self._hybrid_score(result, query_embedding, query_text)
            decay = self._time_decay(result.timestamp)
            final_score = hybrid * decay

            scored_result = RetrievalResult(
                memory_id=result.memory_id,
                content=result.content,
                score=final_score,
                source=result.source,
                timestamp=result.timestamp,
                metadata=result.metadata,
                evidence_chain=result.evidence_chain,
            )
            scored_result.score_breakdown = RetrievalScore(
                semantic=result.score_breakdown.semantic,
                keyword=result.score_breakdown.keyword,
                graph=result.score_breakdown.graph,
                time_decay=decay,
                total=final_score,
            )
            scored.append(scored_result)

        # ⑤ 排序 + 早停截断
        scored.sort(key=lambda x: x.score, reverse=True)
        scored = self._apply_early_stop(scored, top_k)

        return scored[:top_k]

    # =========================================================
    # 召回通道
    # =========================================================

    def _tkg_recall(
        self,
        query: str,
        user_id: str,
        top_k: int,
    ) -> list[RetrievalResult]:
        """Neo4j 全文索引 BM25 粗召回。

        使用 ``db.index.fulltext.queryNodes("memoryFullText", $query)`` 查询，
        仅返回 HOT/WARM 层节点。

        Args:
            query: 查询文本
            user_id: 用户标识
            top_k: 返回数量上限

        Returns:
            RetrievalResult 列表，source="bm25"
        """
        driver = self._driver or self._get_driver()
        if driver is None:
            logger.warning("_tkg_recall: Neo4j 不可用")
            return []

        try:
            cypher = """
            CALL db.index.fulltext.queryNodes("memoryFullText", $query)
            YIELD node, score
            WHERE node.user_id = $user_id
              AND (node.storage_tier IS NULL OR node.storage_tier IN ['hot', 'warm'])
              AND node.is_active <> false
              AND node.t_invalidated_at IS NULL
              AND (node.status IS NULL OR NOT (node.status IN ['superseded', 'deprecated']))
            WITH node, score
            ORDER BY score DESC
            LIMIT $top_k
            RETURN node.node_id AS node_id,
                   node.content AS content,
                   node.summary AS summary,
                   node.created_at AS created_at,
                   score
            """
            with driver.session() as session:
                result = session.run(
                    cypher,
                    {"query": query, "user_id": user_id, "top_k": top_k},
                )
                records = list(result)

            results: list[RetrievalResult] = []
            for record in records:
                node_id = str(record.get("node_id", ""))
                content = record.get("content") or record.get("summary") or ""
                bm25_score = float(record.get("score", 0.0))
                created_at = record.get("created_at") or datetime.utcnow()

                rr = RetrievalResult(
                    memory_id=node_id,
                    content=content,
                    score=bm25_score,
                    source="bm25",
                    timestamp=created_at if isinstance(created_at, datetime) else datetime.utcnow(),
                )
                rr.score_breakdown = RetrievalScore(keyword=bm25_score, total=bm25_score)
                results.append(rr)

            return results
        except Exception:
            logger.warning("_tkg_recall: 全文检索失败", exc_info=True)
            return []

    def _vector_recall(
        self,
        query_embedding: list[float],
        user_id: str,
        top_k: int,
    ) -> list[RetrievalResult]:
        """pgvector 向量检索精召回（按维度分表，HNSW 索引 + ``<=>`` 余弦距离）。

        从 user_memory_embedding_{dim} 表检索，JOIN user_memory 表获取元数据。

        Args:
            query_embedding: 查询向量
            user_id: 用户标识
            top_k: 返回数量上限

        Returns:
            RetrievalResult 列表，source="semantic"
        """
        if not query_embedding:
            return []

        db = self._db or self._get_db()
        if db is None:
            logger.warning("_vector_recall: 数据库不可用")
            return []

        try:
            from internal.service.embedding_table_router import EmbeddingTableRouter
            from sqlalchemy import text

            # 解析系统默认维度并确保维度表已创建
            router = EmbeddingTableRouter.get_instance()
            dimension = router.resolve_system_default_dimension()
            if not router.ensure_tables_for_dimension(dimension):
                logger.warning("_vector_recall: 维度 %d 表创建失败", dimension)
                return []
            table_name = router.get_user_memory_table_name(dimension)

            # 从维度分表检索 + JOIN user_memory 获取元数据
            sql = text(f"""
                SELECT um.id AS memory_id,
                       um.content,
                       um.embedding_node_id,
                       um.created_at,
                       1 - (v.embedding <=> :embedding) AS score
                FROM {table_name} v
                JOIN user_memory um ON v.memory_id = um.id
                WHERE v.owner_account_id = :user_id
                  AND um.status = 'active'
                ORDER BY v.embedding <=> :embedding
                LIMIT :top_k
            """)

            rows = db.session.execute(sql, {
                "user_id": user_id,
                "embedding": query_embedding,
                "top_k": top_k,
            }).all()

            results: list[RetrievalResult] = []
            for row in rows:
                mem_id = str(row.memory_id)
                if row.embedding_node_id:
                    mem_id = row.embedding_node_id

                content = row.content or ""
                semantic_score = float(row.score) if row.score is not None else 0.0

                rr = RetrievalResult(
                    memory_id=mem_id,
                    content=content,
                    score=semantic_score,
                    source="semantic",
                    timestamp=row.created_at or datetime.utcnow(),
                )
                rr.score_breakdown = RetrievalScore(semantic=semantic_score, total=semantic_score)
                results.append(rr)

            return results
        except Exception:
            logger.warning("_vector_recall: 向量检索失败", exc_info=True)
            return []

    def _graph_spread(
        self,
        start_ids: list[str],
        top_k: int = 20,
    ) -> list[tuple[str, float]]:
        """调用 SpreadActivation 进行图扩展。

        Args:
            start_ids: 起始节点 ID 列表
            top_k: 返回最大数量

        Returns:
            ``[(node_id, activation), ...]`` 列表
        """
        if not start_ids:
            return []

        try:
            spread = SpreadActivation(
                neo4j_driver=self._driver or self._get_driver(),
                config=SpreadConfig(),
            )
            return spread.activate(start_ids, top_k=top_k)
        except Exception:
            logger.warning("_graph_spread: 图扩展失败", exc_info=True)
            return []

    # =========================================================
    # 评分与早停
    # =========================================================

    def _hybrid_score(
        self,
        result: RetrievalResult,
        query_embed: Optional[list[float]],
        query_text: str,
    ) -> float:
        """混合评分：w_cosine * semantic + w_bm25 * keyword + w_graph * graph。

        根据 ``result.source`` 分配通道分数，缺失通道权重重分配到其余通道。

        Args:
            result: 检索结果
            query_embed: 查询向量（当前未直接使用，预留扩展）
            query_text: 查询文本（当前未直接使用，预留扩展）

        Returns:
            归一化到 [0, 1] 的混合分数
        """
        w_cosine = self._config.w_cosine
        w_bm25 = self._config.w_bm25
        w_graph = self._config.w_graph

        source = result.source or ""
        breakdown = result.score_breakdown

        # 根据来源分配通道分数
        if source == "hybrid":
            semantic = breakdown.semantic or result.score
            keyword = breakdown.keyword or result.score
            graph = breakdown.graph or 0.0
        elif source == "semantic":
            semantic = result.score
            keyword = 0.0
            graph = 0.0
        elif source == "bm25":
            semantic = 0.0
            keyword = result.score
            graph = 0.0
        elif source in ("graph_spread", "graph"):
            semantic = 0.0
            keyword = 0.0
            graph = result.score
        else:
            semantic = breakdown.semantic or 0.0
            keyword = breakdown.keyword or 0.0
            graph = breakdown.graph or 0.0

        # 缺失通道权重重分配
        has_semantic = semantic > 0
        has_keyword = keyword > 0
        has_graph = graph > 0

        active_weights = []
        active_scores = []
        if has_semantic:
            active_weights.append(w_cosine)
            active_scores.append(semantic)
        if has_keyword:
            active_weights.append(w_bm25)
            active_scores.append(keyword)
        if has_graph:
            active_weights.append(w_graph)
            active_scores.append(graph)

        if not active_weights:
            return 0.0

        total_weight = sum(active_weights)
        if total_weight <= 0:
            return 0.0

        # 归一化权重并计算加权平均
        weighted_sum = sum(w * s for w, s in zip(active_weights, active_scores))
        score = weighted_sum / total_weight

        return max(0.0, min(1.0, score))

    def _time_decay(self, timestamp: datetime, now: Optional[datetime] = None) -> float:
        """时间衰减：exp(-ln2 * Δt / half_life)，Δt 以小时计。

        保留最低 0.01 防完全消失。

        Args:
            timestamp: 记忆时间戳
            now: 当前时间，None 时使用 UTC 当前时刻

        Returns:
            衰减因子 [0.01, 1.0]
        """
        if now is None:
            now = datetime.now(timezone.utc)

        ts = timestamp
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        if now.tzinfo is None:
            now = now.replace(tzinfo=timezone.utc)

        delta_hours = (now - ts).total_seconds() / 3600.0
        delta_hours = max(delta_hours, 0.0)

        half_life = self._config.time_decay_half_life_hours
        if half_life <= 0:
            return 1.0

        decay = math.exp(-math.log(2) * delta_hours / half_life)
        return max(0.01, min(1.0, decay))

    def _apply_early_stop(
        self,
        scored: list[RetrievalResult],
        top_k: int,
    ) -> list[RetrievalResult]:
        """top_k + score_gap 判断，触发早停则截断。

        Args:
            scored: 已排序的检索结果（按 score 降序）
            top_k: 返回数量上限

        Returns:
            截断后的结果列表
        """
        if len(scored) <= top_k:
            return scored

        # 检查 cutoff 处与前一处的分数差
        cutoff = self._config.early_stop_top_k
        score_gap = self._config.early_stop_score_gap

        if cutoff >= len(scored):
            return scored

        score_at_cutoff = scored[cutoff].score
        score_before = scored[cutoff - 1].score

        if score_before - score_at_cutoff > score_gap:
            # 分差超过阈值，截断
            return scored[:cutoff]

        return scored

    # =========================================================
    # 辅助方法
    # =========================================================

    def _embed_query(self, query: str) -> Optional[list[float]]:
        """将查询文本转为向量。

        通过 EmbeddingsService.embeddings.embed_query() 获取向量。
        """
        embeddings_service = self._embeddings_service or self._get_embeddings_service()
        if embeddings_service is None:
            return None

        try:
            return embeddings_service.embeddings.embed_query(query)
        except Exception:
            logger.warning("_embed_query: 查询向量化失败", exc_info=True)
            return None

    def _get_node_data(self, node_id: str) -> Optional[dict]:
        """从 Neo4j 获取节点数据（content、timestamp 等）。"""
        driver = self._driver or self._get_driver()
        if driver is None:
            return None

        try:
            cypher = """
            MATCH (n {node_id: $node_id})
            RETURN n.content AS content,
                   n.summary AS summary,
                   n.created_at AS created_at,
                   n.user_id AS user_id
            """
            with driver.session() as session:
                result = session.run(cypher, {"node_id": node_id})
                record = result.single()

            if record is None:
                return None

            content = record.get("content") or record.get("summary") or ""
            created_at = record.get("created_at") or datetime.utcnow()
            if not isinstance(created_at, datetime):
                created_at = datetime.utcnow()

            return {
                "content": content,
                "timestamp": created_at,
            }
        except Exception:
            logger.warning("_get_node_data: 获取节点数据失败 node_id=%s", node_id, exc_info=True)
            return None

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

    def _get_db(self):
        """获取 SQLAlchemy 实例，不可用时返回 None。"""
        try:
            from flask import current_app

            db = current_app.extensions.get("database")
            if db is not None:
                return db
        except RuntimeError:
            pass
        try:
            from internal.extension.database_extension import db

            return db
        except Exception:
            logger.warning("_get_db: 获取数据库失败", exc_info=True)
            return None

    def _get_embeddings_service(self):
        """获取 EmbeddingsService 实例，不可用时返回 None。"""
        try:
            from flask import current_app

            injector = getattr(current_app, "injector", None)
            if injector is not None:
                from internal.service.embeddings_service import EmbeddingsService

                return injector.get(EmbeddingsService)
        except Exception:
            logger.warning("_get_embeddings_service: 获取失败", exc_info=True)
        return None
