"""六阶段巩固引擎（ConsolidationEngine）。

实现六阶段巩固流程，作为后台定时任务执行记忆整理。灵感来自睡眠记忆巩固
理论——睡眠期间海马体将日间经验转移到新皮层进行长期存储。

六阶段:
    - Phase 1 EXTRACT:  7 天以上 Episode → LLM 提取共性 → SemanticMemory + IS_ABSTRACTION_OF
    - Phase 2 RESOLVE:  委托 ConflictDetector.detect
    - Phase 3 TIER:     HebbianDecay.batch_update_weights + tier 降级
    - Phase 4 MERGE:    相似度 > 0.9 的节点合并（MERGED_INTO 边）
    - Phase 5 SKILL:    委托 SkillEmergence.scan_and_emerge 涌现技能
    - Phase 6 REPORT:   统计摘要

降级策略:
    - 单阶段失败不阻断后续阶段，错误记录到 report.errors
    - Neo4j 不可用时各阶段返回空结果
    - LLM 异常时跳过该条目

设计参考:
    docs/prd/memory-system/03-consolidation-skill-policy-api.md §7.1
    docs/prd/memory-system/execution/04-track-c-consolidation.md C1
    docs/prd/memory-system/execution/06-track-e-skill-pool.md E1
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Optional
from uuid import uuid4

from internal.config.memory_settings import settings
from internal.model.memory_models import (
    ConsolidationConfig,
    ConsolidationPhase,
    ConsolidationReport,
    MemoryEdge,
)
from internal.service.language_model_service import LanguageModelService
from internal.service.memory.metrics import MetricsCollector

logger = logging.getLogger(__name__)


class ConsolidationEngine:
    """五阶段巩固引擎。

    不使用 ``@inject``：无注入依赖，配置从 ``settings.consolidation`` 读取，
    Neo4j 驱动由构造函数传入或运行时获取。
    LLM 通过 ``LanguageModelService.get_cheap_chat_model()`` 静态调用。
    """

    def __init__(
        self,
        neo4j_driver=None,
        config: Optional[ConsolidationConfig] = None,
    ) -> None:
        """初始化巩固引擎。

        Args:
            neo4j_driver: Neo4j 驱动
            config: ConsolidationConfig 实例，None 时使用 settings.consolidation
        """
        self._driver = neo4j_driver
        self._config = config or settings.consolidation

    # =========================================================
    # 主入口
    # =========================================================

    def run_consolidation(self, user_id: str) -> ConsolidationReport:
        """执行完整的五阶段巩固流程。

        按顺序执行每个阶段，单个阶段失败不影响后续阶段。
        返回包含 phases 与 errors 的 ConsolidationReport。

        Args:
            user_id: 用户标识

        Returns:
            ConsolidationReport 巩固报告
        """
        import time as _time

        _start = _time.perf_counter()
        report = self._run_consolidation_impl(user_id)
        MetricsCollector.record_consolidation_phase(
            _time.perf_counter() - _start,
            error=len(report.errors) > 0,
        )
        return report

    def _run_consolidation_impl(self, user_id: str) -> ConsolidationReport:
        """run_consolidation 的原始实现。"""
        report = ConsolidationReport(
            run_id=uuid4(),
            started_at=datetime.utcnow(),
        )

        # 六阶段定义
        phases = [
            (ConsolidationPhase.EXTRACT.value, self._phase1_episodic_to_semantic),
            (ConsolidationPhase.RESOLVE.value, self._phase2_conflict_detection),
            (ConsolidationPhase.TIER.value, self._phase3_weight_scan),
            (ConsolidationPhase.MERGE.value, self._phase4_redundancy_merge),
            (ConsolidationPhase.SKILL.value, self._phase5_skill_emergence),
            (ConsolidationPhase.REPORT.value, self._phase6_stats_summary),
        ]

        for phase_name, phase_func in phases:
            try:
                phase_result = phase_func(user_id)
                report.phases[phase_name] = phase_result

                # 累加汇总字段
                if phase_name == ConsolidationPhase.RESOLVE.value:
                    report.conflicts_resolved = phase_result.get("count", 0)
                elif phase_name == ConsolidationPhase.MERGE.value:
                    report.merged_count = phase_result.get("merged", 0)
                elif phase_name == ConsolidationPhase.SKILL.value:
                    # 修复：skills_emerged 从 SKILL 阶段获取真实技能涌现数
                    report.skills_emerged = phase_result.get("skills_emerged", 0)

            except Exception as exc:
                error_msg = f"阶段 {phase_name} 失败: {exc}"
                report.errors.append(error_msg)
                report.phases[phase_name] = {"error": str(exc)}
                logger.warning(
                    "run_consolidation: %s", error_msg, exc_info=True
                )

        report.finished_at = datetime.utcnow()
        return report

    # =========================================================
    # Phase 1: 情景 → 语义
    # =========================================================

    def _phase1_episodic_to_semantic(self, user_id: str) -> dict:
        """阶段 1：7 天以上 Episode → LLM 提取共性 → SemanticMemory 节点。

        步骤:
            1. 查找 HOT 层且年龄 >= episode_age_days 的 Episode
            2. 对每个 Episode 用 pgvector 搜索相似 Episode 簇
            3. 簇内数量 >= semantic_min_examples 时，调 LLM 提取共性语义
            4. 创建 SemanticMemory 节点 + IS_ABSTRACTION_OF 边

        Returns:
            ``{"count": int, "semantics_created": int}``
        """
        driver = self._driver or self._get_driver()
        if driver is None:
            return {"count": 0, "semantics_created": 0}

        episode_age_days = self._config.episode_age_days
        min_examples = self._config.semantic_min_examples
        similarity_threshold = self._config.semantic_similarity_threshold

        # 查找老的 HOT Episode
        try:
            old_episodes = self._query_old_episodes(driver, user_id, episode_age_days)
        except Exception:
            logger.warning("_phase1: 查询老 Episode 失败", exc_info=True)
            return {"count": 0, "semantics_created": 0}

        if not old_episodes:
            return {"count": 0, "semantics_created": 0}

        processed: set[str] = set()
        semantics_created = 0
        count = 0

        for episode in old_episodes:
            ep_id = episode.get("node_id", "")
            if ep_id in processed:
                continue

            # 查找相似 Episode 簇
            cluster = self._find_similar_cluster(
                driver, user_id, episode, similarity_threshold
            )

            if len(cluster) < min_examples:
                continue

            # 标记已处理
            for member in cluster:
                processed.add(member.get("node_id", ""))

            count += 1

            # LLM 提取共性语义
            semantic_desc = self._extract_semantic(cluster)
            if not semantic_desc:
                continue

            # 创建 SemanticMemory 节点 + IS_ABSTRACTION_OF 边
            try:
                self._create_semantic_memory(
                    driver, user_id, semantic_desc, cluster
                )
                semantics_created += 1
            except Exception:
                logger.warning("_phase1: 创建 SemanticMemory 失败", exc_info=True)

        return {"count": count, "semantics_created": semantics_created}

    # =========================================================
    # Phase 2: 冲突检测
    # =========================================================

    def _phase2_conflict_detection(self, user_id: str) -> dict:
        """阶段 2：委托 ConflictDetector.detect(user_id)。

        Returns:
            ``{"count", "contradictions", "updates", "complements"}``
        """
        try:
            from internal.service.memory.conflict_detector import ConflictDetector

            detector = ConflictDetector(
                neo4j_driver=self._driver or self._get_driver(),
                config=self._config,
            )
            return detector.detect(user_id)
        except Exception:
            logger.warning("_phase2: 冲突检测失败", exc_info=True)
            return {"count": 0, "contradictions": 0, "updates": 0, "complements": 0}

    # =========================================================
    # Phase 3: 权重扫描
    # =========================================================

    def _phase3_weight_scan(self, user_id: str) -> dict:
        """阶段 3：HebbianDecay.batch_update_weights + tier 降级。

        Returns:
            ``{"edges_scanned": int, "tier_migrations": {"hot": n, "warm": m, "cold": k}}``
        """
        driver = self._driver or self._get_driver()
        if driver is None:
            return {"edges_scanned": 0, "tier_migrations": {"hot": 0, "warm": 0, "cold": 0}}

        # 读取用户所有边
        try:
            edges = self._query_user_edges(driver, user_id)
        except Exception:
            logger.warning("_phase3: 查询边失败", exc_info=True)
            return {"edges_scanned": 0, "tier_migrations": {"hot": 0, "warm": 0, "cold": 0}}

        if not edges:
            return {"edges_scanned": 0, "tier_migrations": {"hot": 0, "warm": 0, "cold": 0}}

        # 调用 HebbianDecay.batch_update_weights
        try:
            from internal.service.memory.hebbian_decay import HebbianDecay

            decay = HebbianDecay()
            tier_counts = decay.batch_update_weights(edges, driver)
        except Exception:
            logger.warning("_phase3: 权重更新失败", exc_info=True)
            return {"edges_scanned": len(edges), "tier_migrations": {"hot": 0, "warm": 0, "cold": 0}}

        # 转换 tier_counts 为 dict
        tier_migrations = {
            "hot": tier_counts.get("hot", 0) if isinstance(tier_counts, dict) else 0,
            "warm": tier_counts.get("warm", 0) if isinstance(tier_counts, dict) else 0,
            "cold": tier_counts.get("cold", 0) if isinstance(tier_counts, dict) else 0,
        }

        # 处理 StorageTier 枚举键
        if tier_counts and not isinstance(tier_counts, dict):
            tier_migrations = {"hot": 0, "warm": 0, "cold": 0}
            for tier, count in (tier_counts.items() if hasattr(tier_counts, 'items') else []):
                key = tier.value if hasattr(tier, 'value') else str(tier)
                if key in tier_migrations:
                    tier_migrations[key] = count

        return {
            "edges_scanned": len(edges),
            "tier_migrations": tier_migrations,
        }

    # =========================================================
    # Phase 4: 冗余合并
    # =========================================================

    def _phase4_redundancy_merge(self, user_id: str) -> dict:
        """阶段 4：相似度 > 0.9 的节点合并（创建 MERGED_INTO 边）。

        Returns:
            ``{"count": int, "merged": int}``
        """
        driver = self._driver or self._get_driver()
        if driver is None:
            return {"count": 0, "merged": 0}

        merge_threshold = self._config.merge_similarity_threshold

        # 查询 HOT 层 MemoryNode
        try:
            nodes = self._query_hot_nodes(driver, user_id)
        except Exception:
            logger.warning("_phase4: 查询 HOT 节点失败", exc_info=True)
            return {"count": 0, "merged": 0}

        if not nodes:
            return {"count": 0, "merged": 0}

        count = 0
        merged = 0
        processed: set[str] = set()

        for node in nodes:
            node_id = node.get("node_id", "")
            if node_id in processed:
                continue

            # 用 pgvector 查找相似节点
            similar_nodes = self._find_similar_nodes_pgvector(
                user_id, node_id, merge_threshold
            )

            if not similar_nodes:
                continue

            count += 1

            # 保留权重最高的为主节点，其余合并
            primary_id = node_id
            primary_weight = node.get("weight", 0.0)

            for similar_id, similarity in similar_nodes:
                if similar_id in processed:
                    continue

                try:
                    self._merge_nodes(driver, similar_id, primary_id)
                    processed.add(similar_id)
                    merged += 1
                except Exception:
                    logger.warning(
                        "_phase4: 合并节点失败 %s → %s",
                        similar_id,
                        primary_id,
                        exc_info=True,
                    )

        return {"count": count, "merged": merged}

    # =========================================================
    # Phase 5: 技能涌现
    # =========================================================

    def _phase5_skill_emergence(self, user_id: str) -> dict:
        """阶段 5：委托 SkillEmergence.scan_and_emerge 涌现技能。

        扫描 30 天内高频行为模式（≥ min_pattern_frequency 次），LLM 提取
        参数化技能模板，执行 CANDIDATE→EMERGING→ACTIVE→STALE→DEPRECATED
        状态转移。种子提示机制：有 positive 种子的技能阈值降为 1。

        Returns:
            ``{"skills_emerged": int, "skills_updated": int}``
        """
        try:
            from internal.service.memory.skill_emergence import SkillEmergence

            emergence = SkillEmergence(
                neo4j_driver=self._driver or self._get_driver(),
                redis_client=self._get_redis(),
            )
            skills = emergence.scan_and_emerge(user_id)
            # 区分新增和更新：status=CANDIDATE 视为新增，其余视为更新
            new_count = sum(
                1 for s in skills if s.status.value == "candidate"
            )
            updated_count = len(skills) - new_count
            return {
                "skills_emerged": new_count,
                "skills_updated": updated_count,
            }
        except Exception:
            logger.warning("_phase5: 技能涌现失败", exc_info=True)
            return {"skills_emerged": 0, "skills_updated": 0}

    # =========================================================
    # Phase 6: 统计摘要
    # =========================================================

    def _phase6_stats_summary(self, user_id: str) -> dict:
        """阶段 6：更新统计计数器。

        Returns:
            ``{"total_nodes", "total_edges", "tier_distribution"}``
        """
        driver = self._driver or self._get_driver()
        if driver is None:
            return {"total_nodes": 0, "total_edges": 0, "tier_distribution": {}}

        try:
            cypher = """
            MATCH (n)
            WHERE n.user_id = $user_id AND n.is_active <> false
            RETURN count(n) AS total_nodes,
                   collect(n.storage_tier) AS tiers
            """
            with driver.session() as session:
                result = session.run(cypher, {"user_id": user_id})
                record = result.single()

            total_nodes = 0
            tier_distribution: dict[str, int] = {}
            if record:
                total_nodes = record.get("total_nodes", 0)
                tiers = record.get("tiers", [])
                for tier in tiers:
                    key = tier if tier else "unknown"
                    tier_distribution[key] = tier_distribution.get(key, 0) + 1

            # 统计边数
            cypher_edges = """
            MATCH (s)-[r]->(t)
            WHERE s.user_id = $user_id AND r.is_active <> false
            RETURN count(r) AS total_edges
            """
            with driver.session() as session:
                result = session.run(cypher_edges, {"user_id": user_id})
                edge_record = result.single()

            total_edges = edge_record.get("total_edges", 0) if edge_record else 0

            return {
                "total_nodes": total_nodes,
                "total_edges": total_edges,
                "tier_distribution": tier_distribution,
            }
        except Exception:
            logger.warning("_phase5: 统计失败", exc_info=True)
            return {"total_nodes": 0, "total_edges": 0, "tier_distribution": {}}

    # =========================================================
    # Phase 1 内部方法
    # =========================================================

    def _query_old_episodes(self, driver, user_id: str, age_days: int) -> list[dict]:
        """查询 HOT 层且年龄 >= age_days 的 Episode 节点。"""
        cutoff = datetime.utcnow() - timedelta(days=age_days)
        cypher = """
        MATCH (e:Episode {user_id: $user_id})
        WHERE (e.storage_tier IS NULL OR e.storage_tier = 'hot')
          AND e.is_active <> false
          AND e.created_at <= $cutoff
          AND e.content IS NOT NULL
          AND e.processed IS NULL
        RETURN e.node_id AS node_id,
               e.content AS content,
               e.summary AS summary,
               e.created_at AS created_at,
               e.weight AS weight
        LIMIT 100
        """
        with driver.session() as session:
            result = session.run(
                cypher,
                {"user_id": user_id, "cutoff": cutoff.isoformat()},
            )
            return [dict(record) for record in result]

    def _find_similar_cluster(
        self,
        driver,
        user_id: str,
        episode: dict,
        similarity_threshold: float,
    ) -> list[dict]:
        """查找与给定 Episode 相似的其他 Episode（Neo4j 向量相似度或内容匹配）。

        简化实现：使用 Neo4j 的点积相似度（若有向量索引）或内容关键词匹配。
        """
        ep_id = episode.get("node_id", "")
        content = episode.get("content") or episode.get("summary") or ""

        if not content:
            return [episode]

        try:
            # 使用 Neo4j 向量相似度查询（如果节点有 embedding 属性）
            cypher = """
            MATCH (e:Episode {user_id: $user_id})
            WHERE e.node_id <> $ep_id
              AND (e.storage_tier IS NULL OR e.storage_tier = 'hot')
              AND e.is_active <> false
              AND e.content IS NOT NULL
            WITH e, gds.similarity.jaccard(
                e.content, $content
            ) AS similarity
            WHERE similarity >= $threshold
            RETURN e.node_id AS node_id,
                   e.content AS content,
                   e.summary AS summary,
                   e.created_at AS created_at,
                   e.weight AS weight,
                   similarity
            ORDER BY similarity DESC
            LIMIT 10
            """
            with driver.session() as session:
                result = session.run(
                    cypher,
                    {
                        "ep_id": ep_id,
                        "user_id": user_id,
                        "content": content[:500],
                        "threshold": similarity_threshold * 0.5,  # 降低阈值因 Jaccard 较严格
                    },
                )
                cluster = [dict(record) for record in result]
        except Exception:
            # GDS 不可用，降级为简单内容匹配
            cluster = self._fallback_content_match(driver, user_id, ep_id, content)

        # 将自身加入簇
        cluster.insert(0, episode)
        return cluster

    def _fallback_content_match(
        self,
        driver,
        user_id: str,
        ep_id: str,
        content: str,
    ) -> list[dict]:
        """GDS 不可用时，用简单 CONTAINS 匹配。"""
        # 取内容前 50 字符作为关键词
        keyword = content[:50].strip()
        if not keyword:
            return []

        cypher = """
        MATCH (e:Episode {user_id: $user_id})
        WHERE e.node_id <> $ep_id
          AND e.is_active <> false
          AND e.content CONTAINS $keyword
        RETURN e.node_id AS node_id,
               e.content AS content,
               e.summary AS summary,
               e.created_at AS created_at,
               e.weight AS weight
        LIMIT 5
        """
        with driver.session() as session:
            result = session.run(
                cypher,
                {"ep_id": ep_id, "user_id": user_id, "keyword": keyword},
            )
            return [dict(record) for record in result]

    def _extract_semantic(self, cluster: list[dict]) -> Optional[str]:
        """LLM 提取簇内 Episode 的共性语义。

        使用 LLMActivityProbe 探针包装，死机时返回 None（不写垃圾）。
        """
        from internal.service.memory.llm_activity_probe import (
            LLMActivityProbe,
            LLMActivityTimeoutError,
        )

        episodes_text = "\n".join(
            f"- {ep.get('content', '')[:200] or ep.get('summary', '')[:200]}"
            for ep in cluster
            if ep.get("content") or ep.get("summary")
        )

        if not episodes_text.strip():
            return None

        from internal.service.system_prompt_library_service import SystemPromptLibraryService

        prompt = SystemPromptLibraryService().get_prompt_or_default(
            "memory_semantic_extraction_prompt"
        ).format(episodes=episodes_text)

        try:
            llm = LanguageModelService.get_feature_model("memory_consolidation")
            result = LLMActivityProbe.invoke_with_probe(
                llm, prompt, feature_key="memory_consolidation"
            )
            content = getattr(result, "content", None)
            if content is None:
                content = str(result)
            content = content.strip()
            if len(content) > 10:
                return content
            return None
        except LLMActivityTimeoutError as exc:
            logger.warning(
                "_extract_semantic: LLM 探针检测到死机，终止写入（不写垃圾）: %s",
                exc,
            )
            return None
        except Exception:
            logger.warning("_extract_semantic: LLM 提取失败", exc_info=True)
            return None

    def _create_semantic_memory(
        self,
        driver,
        user_id: str,
        semantic_desc: str,
        cluster: list[dict],
    ) -> None:
        """创建 SemanticMemory 节点 + IS_ABSTRACTION_OF 边。"""
        now = datetime.utcnow().isoformat()
        semantic_id = str(uuid4())

        # 创建 SemanticMemory 节点
        cypher_create = """
        CREATE (s:SemanticMemory:MemoryNode {
            node_id: $semantic_id,
            id: $semantic_id,
            user_id: $user_id,
            content: $content,
            summary: $content,
            storage_tier: 'hot',
            memory_type: 'semantic',
            is_active: true,
            created_at: $now,
            updated_at: $now,
            source: 'consolidation'
        })
        """
        with driver.session() as session:
            session.run(
                cypher_create,
                {
                    "semantic_id": semantic_id,
                    "user_id": user_id,
                    "content": semantic_desc[:1000],
                    "now": now,
                },
            ).consume()

        # 创建 IS_ABSTRACTION_OF 边并标记 Episode 已处理
        for episode in cluster:
            ep_id = episode.get("node_id", "")
            if not ep_id:
                continue

            cypher_edge = """
            MATCH (s:SemanticMemory {node_id: $semantic_id}), (e:Episode {node_id: $ep_id})
            CREATE (s)-[:IS_ABSTRACTION_OF {
                edge_id: $edge_id,
                created_at: $now,
                is_active: true
            }]->(e)
            SET e.processed = true, e.processed_at = $now
            """
            with driver.session() as session:
                session.run(
                    cypher_edge,
                    {
                        "semantic_id": semantic_id,
                        "ep_id": ep_id,
                        "edge_id": str(uuid4()),
                        "now": now,
                    },
                ).consume()

    # =========================================================
    # Phase 3 内部方法
    # =========================================================

    def _query_user_edges(self, driver, user_id: str) -> list[MemoryEdge]:
        """查询用户所有活跃边，构造 MemoryEdge 列表。"""
        cypher = """
        MATCH (s)-[r]->(t)
        WHERE s.user_id = $user_id AND r.is_active <> false
        RETURN r.edge_id AS edge_id,
               s.node_id AS source_id,
               t.node_id AS target_id,
               type(r) AS relation_type,
               r.weight AS weight,
               r.created_at AS created_at,
               r.last_accessed_at AS last_accessed_at,
               r.access_count AS access_count,
               r.cooccurrence_count AS cooccurrence_count
        """
        with driver.session() as session:
            result = session.run(cypher, {"user_id": user_id})
            edges = []
            for record in result:
                try:
                    edge = MemoryEdge(
                        edge_id=record.get("edge_id") or uuid4(),
                        source_id=record.get("source_id"),
                        target_id=record.get("target_id"),
                        relation_type=record.get("relation_type", "RELATED"),
                        weight=float(record.get("weight", 1.0)),
                        created_at=record.get("created_at") or datetime.utcnow(),
                        last_accessed_at=record.get("last_accessed_at") or datetime.utcnow(),
                        access_count=int(record.get("access_count", 0)),
                        cooccurrence_count=int(record.get("cooccurrence_count", 0)),
                    )
                    edges.append(edge)
                except Exception:
                    logger.warning(
                        "_query_user_edges: 构造 MemoryEdge 失败", exc_info=True
                    )
            return edges

    # =========================================================
    # Phase 4 内部方法
    # =========================================================

    def _query_hot_nodes(self, driver, user_id: str) -> list[dict]:
        """查询用户 HOT 层 MemoryNode。"""
        cypher = """
        MATCH (n)
        WHERE n.user_id = $user_id
          AND (n.storage_tier IS NULL OR n.storage_tier = 'hot')
          AND n.is_active <> false
          AND n.content IS NOT NULL
        RETURN n.node_id AS node_id,
               n.content AS content,
               n.weight AS weight,
               n.created_at AS created_at
        LIMIT 200
        """
        with driver.session() as session:
            result = session.run(cypher, {"user_id": user_id})
            return [dict(record) for record in result]

    def _find_similar_nodes_pgvector(
        self,
        user_id: str,
        node_id: str,
        threshold: float,
    ) -> list[tuple[str, float]]:
        """用 pgvector 查找相似度 >= threshold 的其他节点。

        Returns:
            ``[(node_id, similarity), ...]``
        """
        db = self._get_db()
        if db is None:
            return []

        try:
            from internal.model.knowledge import UserMemory

            # 查找源节点的 embedding
            source = (
                db.session.query(UserMemory.embedding, UserMemory.embedding_node_id)
                .filter(UserMemory.owner_account_id == user_id)
                .filter(UserMemory.embedding_node_id == node_id)
                .filter(UserMemory.embedding.isnot(None))
                .first()
            )

            if source is None or source.embedding is None:
                return []

            query_vec = source.embedding

            # 查找相似节点
            rows = (
                db.session.query(
                    UserMemory.embedding_node_id,
                    UserMemory.embedding,
                )
                .filter(UserMemory.owner_account_id == user_id)
                .filter(UserMemory.embedding.isnot(None))
                .filter(UserMemory.embedding_node_id != node_id)
                .order_by(UserMemory.embedding.cosine_distance(query_vec))
                .limit(10)
                .all()
            )

            import numpy as np

            source_vec = np.array(query_vec, dtype=np.float32)
            source_norm = np.linalg.norm(source_vec)
            if source_norm < 1e-10:
                return []

            results = []
            for row in rows:
                if row.embedding is None or not row.embedding_node_id:
                    continue
                vec = np.array(row.embedding, dtype=np.float32)
                vec_norm = np.linalg.norm(vec)
                if vec_norm < 1e-10:
                    continue
                similarity = float(np.dot(source_vec, vec) / (source_norm * vec_norm))
                if similarity >= threshold:
                    results.append((row.embedding_node_id, similarity))

            return results
        except Exception:
            logger.warning("_find_similar_nodes_pgvector: 失败", exc_info=True)
            return []

    def _merge_nodes(self, driver, source_id: str, target_id: str) -> None:
        """合并节点：source 标记为 merged + 创建 MERGED_INTO 边。"""
        now = datetime.utcnow().isoformat()

        # 标记 source 为 merged
        cypher_mark = """
        MATCH (n {node_id: $source_id})
        SET n.status = 'merged',
            n.merged_to = $target_id,
            n.is_active = false,
            n.merged_at = $now
        """
        with driver.session() as session:
            session.run(
                cypher_mark,
                {"source_id": source_id, "target_id": target_id, "now": now},
            ).consume()

        # 创建 MERGED_INTO 边
        cypher_edge = """
        MATCH (s {node_id: $source_id}), (t {node_id: $target_id})
        CREATE (s)-[:MERGED_INTO {
            edge_id: $edge_id,
            created_at: $now,
            is_active: true
        }]->(t)
        """
        with driver.session() as session:
            session.run(
                cypher_edge,
                {
                    "source_id": source_id,
                    "target_id": target_id,
                    "edge_id": str(uuid4()),
                    "now": now,
                },
            ).consume()

    # =========================================================
    # 辅助方法
    # =========================================================

    def _get_driver(self):
        """获取 Neo4j 驱动，不可用时返回 None。"""
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

    def _get_db(self):
        """获取 SQLAlchemy 实例，不可用时返回 None。"""
        try:
            from internal.context import current_app

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

    def _get_redis(self):
        """获取 Redis 客户端，不可用时返回 None。"""
        try:
            from internal.context import current_app

            return current_app.extensions.get("redis")
        except RuntimeError:
            return None
        except Exception:
            logger.warning("_get_redis: 获取 Redis 失败", exc_info=True)
            return None
