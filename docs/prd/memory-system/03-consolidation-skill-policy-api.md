# 巩固引擎、技能池、Policy 层与 API -- 代码实现

> 本文档为主架构文档的子模块，包含巩固引擎、技能涌现、策略路由、API 接口、路线图、监控及附录。

---

> **v5.1 设计更新（2026-07-09）**
>
> - **API 全面替换**：旧 API（/memory-candidates/*, /user/memory/*）被新 API 替代，不做向后兼容。
> - **删除策略修正**：从 DETACH DELETE 物理删除改为软删除（is_active=false）+ 彻底删除双选项。
> - **完全替代旧系统**：旧代码删除，不做向后兼容。

---
7. 巩固引擎
灵感来源：睡眠记忆巩固理论 — 睡眠期间海马体将日间经验转移到新皮层进行长期存储。

### 7.1 ConsolidationEngine 完整 Python 实现

```python
from __future__ import annotations
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Optional
from pydantic import BaseModel, Field
from neo4j import AsyncDriver
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text
from openai import AsyncOpenAI

logger = logging.getLogger(__name__)


# ── 数据模型 ──────────────────────────────────────────────
class ConsolidationPhase(str, Enum):
    """
    巩固阶段
    """

    EPISODIC_TO_SEMANTIC = "episodic_to_semantic"
    # 阶段 1: 情景→语义
    CONFLICT_DETECTION = "conflict_detection"
    # 阶段 2: 冲突检测
    WEIGHT_SCAN = "weight_scan"
    # 阶段 3: 权重扫描
    REDUNDANCY_MERGE = "redundancy_merge"
    # 阶段 4: 冗余合并
    STATS_SUMMARY = "stats_summary"

    # 阶段 5: 统计摘要
    class ConsolidationConfig(BaseModel):
        """
        巩固引擎配置
        """

        # 阶段 1: 情景→语义
        episode_age_days: int = Field(default=7, ge=1, description="Episode 转语义的最低年龄")
        semantic_min_examples: int = Field(
            default=3, ge=1, description="提取语义的最少相似 Episode 数"
        )
        semantic_similarity_threshold: float = Field(default=0.8, ge=0.0, le=1.0)
        # 阶段 2: 冲突检测
        conflict_check_batch_size: int = Field(default=50, ge=1)
        conflict_similarity_threshold: float = Field(default=0.85, ge=0.0, le=1.0)
        # 阶段 3: 权重扫描
        cold_threshold: float = Field(default=0.3, ge=0.0, le=1.0)
        # 阶段 4: 冗余合并
        merge_similarity_threshold: float = Field(default=0.9, ge=0.0, le=1.0)
        # LLM
        llm_model: str = Field(default="gpt-4o-mini")
        llm_temperature: float = Field(default=0.0)

        @dataclass
        class ConsolidationReport:
            """
            巩固执行报告
            """

            user_id: str
            started_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
            completed_at: Optional[datetime] = None
            phase_results: dict[str, dict] = field(default_factory=dict)
            errors: list[str] = field(default_factory=list)

            @property
            def total_items_processed(self) -> int:
                return sum(r.get("count", 0) for r in self.phase_results.values())

                @property
                def is_success(self) -> bool:
                    return len(self.errors) == 0

                    # ── 核心类 ──────────────────────────────────────────────────
                    class ConsolidationEngine:
                        """
                        记忆巩固引擎 — 后台定时任务，执行五个阶段的记忆整理。
                        五个阶段:
                        1. Episodic → Semantic: 将成熟的 Episode 提取为 Semantic 记忆
                        2. Conflict Detection: 检测矛盾/更新/互补关系
                        3. Weight Scan: 重新计算所有边权重，决定存储层级迁移
                        4. Redundancy Merge: 合并语义过近的重复记忆
                        5. Stats Summary: 生成记忆统计摘要
                        """

                        def __init__(
                            self,
                            neo4j: AsyncDriver,
                            db_session: AsyncSession,
                            llm_client: AsyncOpenAI,
                            config: Optional[ConsolidationConfig] = None,
                        ) -> None:
                            """
                            初始化巩固引擎。
                            Args:
                            neo4j: Neo4j 异步驱动。
                            db_session: SQLAlchemy 异步会话（用于 pgvector 向量检索）。
                            llm_client: OpenAI 异步客户端。
                            config: 巩固配置。
                            """
                            self._neo4j = neo4j
                            self._db_session = db_session
                            self._llm = llm_client
                            self._config = config or ConsolidationConfig()

                            async def run_consolidation(self, user_id: str) -> ConsolidationReport:
                                """
                                执行完整的五阶段巩固流程。
                                按顺序执行每个阶段，单个阶段失败不影响后续阶段。
                                最终返回完整的执行报告。
                                Args:
                                user_id: 用户 ID。
                                Returns:
                                巩固执行报告。
                                """
                                report = ConsolidationReport(user_id=user_id)
                                phases = [
                                    ("episodic_to_semantic", self._phase1_episodic_to_semantic),
                                    ("conflict_detection", self._phase2_conflict_detection),
                                    ("weight_scan", self._phase3_weight_scan),
                                    ("redundancy_merge", self._phase4_redundancy_merge),
                                    ("stats_summary", self._phase5_stats_summary),
                                ]
                                for phase_name, phase_func in phases:
                                    try:
                                        logger.info(
                                            "Consolidation phase '%s' starting for user %s",
                                            phase_name,
                                            user_id,
                                        )
                                        result = await phase_func(user_id)
                                        report.phase_results[phase_name] = result
                                        logger.info(
                                            "Consolidation phase '%s' completed: %s",
                                            phase_name,
                                            result,
                                        )
                                    except Exception as e:
                                        error_msg = f"Phase {phase_name} failed: {e}"
                                        report.errors.append(error_msg)
                                        logger.error(error_msg, exc_info=True)
                                        report.completed_at = datetime.now(timezone.utc)
                                        logger.info(
                                            "Consolidation completed for user %s: %d items, %d errors",
                                            user_id,
                                            report.total_items_processed,
                                            len(report.errors),
                                        )
                                        return report

                                async def _phase1_episodic_to_semantic(self, user_id: str) -> dict:
                                    """
                                    阶段 1: 情景→语义 — 从成熟 Episode 中提取通用语义记忆。
                                    策略:
                                    1. 查找超过 episode_age_days 天的热 Episode
                                    2. 用 pgvector 搜索语义相似的 Episode 簇
                                    3. 当簇内数量 >= semantic_min_examples 时，LLM 提取共性
                                    4. 创建 SemanticMemory 节点，建立 IS_ABSTRACTION_OF 边
                                    Args:
                                    user_id: 用户 ID。
                                    Returns:
                                    {"count": int, "semantics_created": int}
                                    """
                                    cfg = self._config
                                    # 1. 查找成熟 Episode
                                    cypher = """
                                    MATCH (e:Episode)-[:BELONGS_TO]->(u:User {id: $user_id})
                                    WHERE e.storage_tier = 'HOT'
                                    AND duration.between(date(e.created_at), date()).days >= $min_age
                                    RETURN e.id AS id, e.content AS content, e.embedding_key AS embed_key
                                    ORDER BY e.created_at ASC
                                    LIMIT 100
                                    """
                                    async with self._neo4j.session() as session:
                                        result = await session.run(
                                            cypher, user_id=user_id, min_age=cfg.episode_age_days
                                        )
                                        episodes = await result.data()
                                        if not episodes:
                                            return {"count": 0, "semantics_created": 0}
                                            # 2. 对每个 Episode 搜索相似 Episode
                                            semantics_created = 0
                                            processed: set[str] = set()
                                            for ep in episodes:
                                                if ep["id"] in processed:
                                                    continue
                                                    # 3. pgvector 向量搜索相似 Episode
                                                    # pgvector: 在 user_memory.embedding 列上执行余弦距离查询
                                                    stmt = text("""
                                                        SELECT memory_id, content,
                                                               1 - (embedding <=> CAST(:query_vec AS vector)) AS score
                                                        FROM user_memory
                                                        WHERE owner_account_id = :user_id
                                                          AND memory_type = 'episode'
                                                        ORDER BY embedding <=> CAST(:query_vec AS vector)
                                                        LIMIT 20
                                                    """)
                                                    sim_result = await self._db_session.execute(stmt, {
                                                        "query_vec": str([0.0] * 1536),
                                                        # 生产中使用真实向量
                                                        "user_id": user_id,
                                                    })
                                                    similar_hits = sim_result.fetchall()
                                                    cluster = [ep]
                                                    for row in similar_hits:
                                                        if (
                                                            float(row[2])
                                                            >= cfg.semantic_similarity_threshold
                                                        ):
                                                            cluster.append(
                                                                {
                                                                    "id": str(row[0]),
                                                                    "content": row[1] or "",
                                                                }
                                                            )
                                                            if (
                                                                len(cluster)
                                                                < cfg.semantic_min_examples
                                                            ):
                                                                continue
                                                                # 4. LLM 提取语义
                                                                prompt = f
                                                                """
                                                                从以下 {len(cluster)} 条相似经历中提取通用语义记忆（规律/知识）: {chr(10).join(f'{i+1}. {e["content"][:200]}' for i, e in enumerate(cluster))} 请用一句话概括这些经历的共同规律。
                                                                """
                                                                try:
                                                                    resp = await self._llm.chat.completions.create(
                                                                        model=cfg.llm_model,
                                                                        messages=[
                                                                            {
                                                                                "role": "user",
                                                                                "content": prompt,
                                                                            }
                                                                        ],
                                                                        temperature=cfg.llm_temperature,
                                                                        max_tokens=200,
                                                                    )
                                                                    semantic_text = (
                                                                        resp.choices[
                                                                            0
                                                                        ].message.content
                                                                        or ""
                                                                    )
                                                                    # 创建 SemanticMemory 节点
                                                                    semantic_id = f"semantic_{user_id}_{len(processed)}"
                                                                    merge_cypher = """ MERGE (s:SemanticMemory {id: $sid}) SET s.content = $content, s.user_id = $user_id, s.storage_tier = 'HOT', s.created_at = datetime(), s.source_count = $count WITH s UNWIND $episode_ids AS eid MATCH (e:Episode {id: eid}) MERGE (e)-[:IS_ABSTRACTION_OF]->(s) """
                                                                    ep_ids = [
                                                                        e["id"] for e in cluster
                                                                    ]
                                                                    async with self._neo4j.session() as session:
                                                                        await session.run(
                                                                            merge_cypher,
                                                                            sid=semantic_id,
                                                                            content=semantic_text,
                                                                            user_id=user_id,
                                                                            count=len(cluster),
                                                                            episode_ids=ep_ids,
                                                                        )
                                                                        semantics_created += 1
                                                                        for e in cluster:
                                                                            processed.add(e["id"])
                                                                except Exception as e:
                                                                    logger.warning(
                                                                        "Semantic extraction failed: %s",
                                                                        e,
                                                                    )
                                                                    return {
                                                                        "count": len(episodes),
                                                                        "semantics_created": semantics_created,
                                                                    }

                                    async def _phase2_conflict_detection(
                                        self, user_id: str
                                    ) -> dict:
                                        """
                                        阶段 2: 冲突检测 — 检测语义记忆间的矛盾/更新/互补。
                                        委托 ConflictDetector 执行。
                                        Args:
                                        user_id: 用户 ID。
                                        Returns:
                                        {"count": int, "contradictions": int, "updates": int, "complements": int}
                                        """
                                        detector = ConflictDetector(
                                            self._neo4j, self._llm, self._config
                                        )
                                        result = await detector.detect(user_id)
                                        return result

                                        async def _phase3_weight_scan(self, user_id: str) -> dict:
                                            """
                                            阶段 3: 权重扫描 — 重新计算边权重并更新存储层级。
                                            Args:
                                            user_id: 用户 ID。
                                            Returns:
                                            {"edges_scanned": int, "tier_migrations": dict}
                                            """
                                            from src.storage.hebbian_decay import (
                                                HebbianDecay,
                                                DecayConfig,
                                                MemoryEdge,
                                            )

                                            decay = HebbianDecay(DecayConfig())
                                            # 读取用户所有边
                                            cypher = """
                                            MATCH (a:MemoryNode)-[r]->(b:MemoryNode)
                                            WHERE a.user_id = $user_id OR b.user_id = $user_id
                                            RETURN id(r) AS edge_id, a.id AS source_id, b.id AS target_id, type(r) AS relation_type, r.weight AS weight, r.last_accessed_at AS last_accessed_at, r.access_count AS access_count, r.cooccurrence_count AS cooccurrence_count, r.competitor_count AS competitor_count
                                            """
                                            async with self._neo4j.session() as session:
                                                result = await session.run(cypher, user_id=user_id)
                                                records = await result.data()
                                                edges = []
                                                for r in records:
                                                    edges.append(
                                                        MemoryEdge(
                                                            edge_id=str(r["edge_id"]),
                                                            source_id=r["source_id"],
                                                            target_id=r["target_id"],
                                                            relation_type=r["relation_type"],
                                                            weight=r["weight"] or 1.0,
                                                            last_accessed_at=r["last_accessed_at"]
                                                            or datetime.now(timezone.utc),
                                                            access_count=r["access_count"] or 1,
                                                            cooccurrence_count=r[
                                                                "cooccurrence_count"
                                                            ]
                                                            or 0,
                                                        )
                                                    )
                                                    tier_counts = await decay.batch_update_weights(
                                                        edges, self._neo4j
                                                    )
                                                    # 迁移 L3 节点到冷存储
                                                    cold_edges = (
                                                        tier_counts.get(3, 0)
                                                        if isinstance(tier_counts, dict)
                                                        else 0
                                                    )
                                                    return {
                                                        "edges_scanned": len(edges),
                                                        "tier_migrations": {
                                                            "HOT": (
                                                                tier_counts.get(1, 0)
                                                                if isinstance(tier_counts, dict)
                                                                else 0
                                                            ),
                                                            "WARM": (
                                                                tier_counts.get(2, 0)
                                                                if isinstance(tier_counts, dict)
                                                                else 0
                                                            ),
                                                            "COLD": cold_edges,
                                                        },
                                                    }

                                            async def _phase4_redundancy_merge(
                                                self, user_id: str
                                            ) -> dict:
                                                """
                                                阶段 4: 冗余合并 — 合并语义过近的重复记忆。
                                                Args:
                                                user_id: 用户 ID。
                                                Returns:
                                                {"count": int, "merged": int}
                                                """
                                                cfg = self._config
                                                threshold = cfg.merge_similarity_threshold
                                                # pgvector 批量搜索高相似对
                                                cypher = """
                                                MATCH (n:MemoryNode)-[:BELONGS_TO]->(u:User {id: $user_id})
                                                WHERE n.storage_tier = 'HOT' OR n.storage_tier IS NULL
                                                RETURN n.id AS id, n.content AS content
                                                LIMIT 200
                                                """
                                                async with self._neo4j.session() as session:
                                                    result = await session.run(
                                                        cypher, user_id=user_id
                                                    )
                                                    nodes = await result.data()
                                                    merged = 0
                                                    visited: set[str] = set()
                                                    for node in nodes:
                                                        if node["id"] in visited:
                                                            continue
                                                            # 搜索与当前节点高相似的其他节点
                                                            # pgvector: 在 user_memory.embedding 列上执行余弦距离查询
                                                            sim_stmt = text("""
                                                                SELECT memory_id,
                                                                       1 - (embedding <=> CAST(:query_vec AS vector)) AS score
                                                                FROM user_memory
                                                                WHERE owner_account_id = :user_id
                                                                  AND 1 - (embedding <=> CAST(:query_vec AS vector)) >= :threshold
                                                                ORDER BY embedding <=> CAST(:query_vec AS vector)
                                                                LIMIT 5
                                                            """)
                                                            sim_rows = await self._db_session.execute(sim_stmt, {
                                                                "query_vec": str([0.0] * 1536),
                                                                # 生产中使用真实向量
                                                                "user_id": user_id,
                                                                "threshold": threshold,
                                                            })
                                                            similar = sim_rows.fetchall()
                                                            if len(similar) >= 2:
                                                                # 合并: 保留分数最高的，其余标记为 merged_to
                                                                primary_id = str(similar[0][0])
                                                                secondary_ids = [
                                                                    str(hit[0])
                                                                    for hit in similar[1:]
                                                                ]
                                                                merge_cypher = """ UNWIND $secondary_ids AS sid MATCH (s:MemoryNode {id: sid}) MATCH (p:MemoryNode {id: $primary_id}) SET s.status = 'merged', s.merged_to = $primary_id MERGE (s)-[:MERGED_INTO]->(p) """
                                                                async with self._neo4j.session() as session:
                                                                    await session.run(
                                                                        merge_cypher,
                                                                        primary_id=primary_id,
                                                                        secondary_ids=secondary_ids,
                                                                    )
                                                                    visited.update(secondary_ids)
                                                                    merged += len(secondary_ids)
                                                                    return {
                                                                        "count": len(nodes),
                                                                        "merged": merged,
                                                                    }

                                                async def _phase5_stats_summary(
                                                    self, user_id: str
                                                ) -> dict:
                                                    """
                                                    阶段 5: 统计摘要 — 生成记忆系统统计报告。
                                                    Args:
                                                    user_id: 用户 ID。
                                                    Returns:
                                                    {"total_nodes": int, "total_edges": int, "tier_distribution": dict}
                                                    """
                                                    cypher = """
                                                    MATCH (n)-[:BELONGS_TO]->(u:User {id: $user_id})
                                                    RETURN count(n) AS total_nodes, count{[-]->(n)} AS total_edges
                                                    """
                                                    async with self._neo4j.session() as session:
                                                        result = await session.run(
                                                            cypher, user_id=user_id
                                                        )
                                                        records = await result.data()
                                                        tier_cypher = """
                                                        MATCH (n)-[:BELONGS_TO]->(u:User {id: $user_id})
                                                        RETURN n.storage_tier AS tier, count(n) AS count
                                                        """
                                                        async with self._neo4j.session() as session:
                                                            result2 = await session.run(
                                                                tier_cypher, user_id=user_id
                                                            )
                                                            tier_records = await result2.data()
                                                            tier_dist = {
                                                                r["tier"] or "UNSET": r["count"]
                                                                for r in tier_records
                                                            }
                                                            return {
                                                                "total_nodes": (
                                                                    records[0]["total_nodes"]
                                                                    if records
                                                                    else 0
                                                                ),
                                                                "total_edges": (
                                                                    records[0]["total_edges"]
                                                                    if records
                                                                    else 0
                                                                ),
                                                                "tier_distribution": tier_dist,
                                                            }
```
**Celery 任务定义:**

```python
# tasks/consolidation_tasks.py
from celery import Celery
from celery.schedules import crontab

celery_app = Celery("memory_consolidation")
celery_app.conf.beat_schedule = {
    # 每天凌晨 3 点执行全量巩固
    "daily-consolidation": {
        "task": "tasks.consolidation_tasks.run_daily_consolidation",
        "schedule": crontab(hour=3, minute=0),
        "args": [],
    },
    # 每 6 小时执行权重扫描
    "weight-scan": {
        "task": "tasks.consolidation_tasks.run_weight_scan",
        "schedule": crontab(hour="*/6", minute=30),
        "args": [],
    },
}
celery_app.conf.task_routes = {
    "tasks.consolidation_tasks.*": {"queue": "consolidation"},
}


@celery_app.task(bind=True, max_retries=2, default_retry_delay=300)
async def run_daily_consolidation(self, user_ids: list[str] | None = None) -> dict:
    """
    Celery 任务: 对指定用户或所有活跃用户执行全量巩固。
    Args:
    user_ids: 用户 ID 列表。None 表示扫描所有活跃用户。
    Returns:
    执行摘要。
    """
    from src.consolidation.engine import ConsolidationEngine

    # ... 初始化 engine ...
    # if user_ids is None:
    # user_ids = await _get_active_users()
    results = {}
    for uid in user_ids:
        try:
            report = await engine.run_consolidation(uid)
            results[uid] = {"success": report.is_success, "items": report.total_items_processed}
        except Exception as e:
            results[uid] = {"success": False, "error": str(e)}
            return results

            @celery_app.task(bind=True, max_retries=3, default_retry_delay=60)
            async def run_weight_scan(self, user_id: str) -> dict:
                """
                Celery 任务: 单用户权重扫描。
                """
                from src.consolidation.engine import ConsolidationEngine

                # ... 初始化 engine ...
                report = await engine.run_consolidation(user_id)
                # 仅取阶段 3 结果
                return report.phase_results.get("weight_scan", {})
```
### 7.2 ConflictDetector 完整 Python 实现

```python
from __future__ import annotations
import logging
from enum import Enum
from typing import Optional
from pydantic import BaseModel, Field
from neo4j import AsyncDriver
from openai import AsyncOpenAI

logger = logging.getLogger(__name__)


# ── 模型 ──────────────────────────────────────────────────
class ConflictType(str, Enum):
    """
    冲突类型"""

    CONTRADICTION = "contradiction"
    # 矛盾：两个记忆内容直接矛盾
    UPDATE = "update"
    # 更新：新记忆是旧记忆的更新版本
    COMPLEMENT = "complement"
    # 互补：两个记忆互相补充


class ConflictResult(BaseModel):
    """
    单对冲突检测结果"""

    memory_a_id: str
    memory_b_id: str
    conflict_type: ConflictType
    confidence: float = Field(ge=0.0, le=1.0)
    resolution: str = ""
    similarity: float = 0.0
    # ── Prompt 模板 ────────────────────────────────────────────
    CONFLICT_DETECTION_PROMPT = """ 你是一个记忆一致性检测器。请判断以下两条记忆之间的关系。
    ##
    记忆 A {memory_a}
    ##
    记忆 B {memory_b} 请从以下三个选项中选择最合适的关系，并给出置信度(0-1)和简要解释： 1. CONTRADICTION（矛盾）: 两条记忆存在事实性矛盾 2. UPDATE（更新）: 记忆B是记忆A的更新版本 3. COMPLEMENT（互补）: 两条记忆互为补充，不矛盾 输出格式(JSON): {{"type": "CONTRADICTION|UPDATE|COMPLEMENT", "confidence": 0.0-1.0, "explanation": "..."}} """
    # ── 核心类 ──────────────────────────────────────────────────


class ConflictDetector:
    """
    记忆冲突检测器 — 使用 LLM 判定记忆对之间的关系。 三分支判定: - CONTRADICTION: 标记旧记忆为 deprecated，保留新记忆 - UPDATE: 合并新记忆内容到旧记忆，更新时间戳
    - COMPLEMENT: 保留两者，添加 COMPLEMENTARY 边
    """

    def __init__(
        self,
        neo4j: AsyncDriver,
        llm_client: AsyncOpenAI,
        config: "ConsolidationConfig",
    ) -> None:
        """
        初始化冲突检测器。 Args: neo4j: Neo4j 异步驱动。 llm_client: OpenAI 异步客户端。
        config: 巩固配置。
        """
        self._neo4j = neo4j
        self._llm = llm_client
        self._config = config

    async def detect(self, user_id: str) -> dict:
        """
        检测用户的所有潜在冲突记忆对。 策略: 1. 从 Neo4j 获取用户的热 SemanticMemory 节点 2. 对每对语义相近的节点，调用 LLM 判定关系
        3. 根据判定结果执行相应操作
        Args:
        user_id: 用户 ID。
        Returns:
        {"count": int, "contradictions": int, "updates": int, "complements": int}
        """
        # 获取候选对
        cypher = """ MATCH (a:SemanticMemory)-[:BELONGS_TO]->(u:User {id: $user_id}) MATCH (b:SemanticMemory)-[:BELONGS_TO]->(u) WHERE a.id < b.id AND (a.storage_tier = 'HOT' OR a.storage_tier IS NULL)
        AND (b.storage_tier = 'HOT' OR b.storage_tier IS NULL)
        RETURN a.id AS a_id, a.content AS a_content, b.id AS b_id, b.content AS b_content, a.created_at AS a_ts, b.created_at AS b_ts
        LIMIT $batch_size
        """
        stats = {"count": 0, "contradictions": 0, "updates": 0, "complements": 0}
        async with self._neo4j.session() as session:
            result = await session.run(
                cypher, user_id=user_id, batch_size=self._config.conflict_check_batch_size
            )
            pairs = await result.data()
            for pair in pairs:
                stats["count"] += 1
                conflict = await self._detect_pair(
                    pair["a_id"],
                    pair["a_content"],
                    pair["b_id"],
                    pair["b_content"],
                    pair["a_ts"],
                    pair["b_ts"],
                )
                if conflict is None:
                    continue
                await self._resolve_conflict(conflict)
                if conflict.conflict_type == ConflictType.CONTRADICTION:
                    stats["contradictions"] += 1
                elif conflict.conflict_type == ConflictType.UPDATE:
                    stats["updates"] += 1
            else:
                stats["complements"] += 1
                return stats

    async def _detect_pair(
        self,
        a_id: str,
        a_content: str,
        b_id: str,
        b_content: str,
        a_ts,
        b_ts,
    ) -> Optional[ConflictResult]:
        """
        对单对记忆进行冲突判定。 Args: a_id, a_content: 记忆 A 的 ID 和内容。 b_id, b_content: 记忆 B 的 ID 和内容。
        a_ts, b_ts: 时间戳。
        Returns:
        冲突结果，或 None（低置信度时不处理）。
        """
        prompt = CONFLICT_DETECTION_PROMPT.format(
            memory_a=a_content[:500], memory_b=b_content[:500]
        )
        try:
            resp = await self._llm.chat.completions.create(
                model=self._config.llm_model,
                messages=[{"role": "user", "content": prompt}],
                temperature=0.0,
                max_tokens=200,
                response_format={"type": "json_object"},
            )
            import json

            parsed = json.loads(resp.choices[0].message.content or "{}")
            conflict_type = ConflictType(parsed.get("type", "COMPLEMENT"))
            confidence = float(parsed.get("confidence", 0.0))
            if confidence < 0.7:
                return None
            return ConflictResult(
                memory_a_id=a_id,
                memory_b_id=b_id,
                conflict_type=conflict_type,
                confidence=confidence,
                resolution=parsed.get("explanation", ""),
            )
        except Exception as e:
            logger.warning("Conflict detection LLM call failed: %s", e)
            return None

    async def _resolve_conflict(self, conflict: ConflictResult) -> None:
        """
        根据冲突类型执行解决操作。 CONTRADICTION: 标记旧记忆为 deprecated UPDATE: 合并内容到较新的记忆 COMPLEMENT: 添加 COMPLEMENTARY 边
        Args:
        conflict: 冲突检测结果。
        """
        if conflict.conflict_type == ConflictType.CONTRADICTION:
            # 标记较旧的记忆为 deprecated
            cypher = """ MATCH (a:SemanticMemory {id: $a_id}) MATCH (b:SemanticMemory {id: $b_id}) WITH a, b, CASE WHEN a.created_at < b.created_at THEN a ELSE b END AS older SET
            older.status = 'deprecated',
            older.deprecated_reason = $reason,
            older.deprecated_at = datetime() """
            async with self._neo4j.session() as session:
                await session.run(
                    cypher,
                    a_id=conflict.memory_a_id,
                    b_id=conflict.memory_b_id,
                    reason=f"Contradiction with {conflict.memory_b_id}",
                )
        elif conflict.conflict_type == ConflictType.UPDATE:
            # 标记旧记忆被更新
            cypher = """ MATCH (a:SemanticMemory {id: $a_id}) MATCH (b:SemanticMemory {id: $b_id}) WITH a, b, CASE WHEN a.created_at < b.created_at THEN a ELSE b END AS older, CASE WHEN a.created_at < b.created_at THEN b ELSE a END AS newer SET
            older.status = 'superseded',
            older.superseded_by = newer.id MERGE (older)-[:SUPERSEDED_BY]->(newer) """
            async with self._neo4j.session() as session:
                await session.run(cypher, a_id=conflict.memory_a_id, b_id=conflict.memory_b_id)
        elif conflict.conflict_type == ConflictType.COMPLEMENT:
            # 添加互补边
            cypher = """ MATCH (a:SemanticMemory {id: $a_id}) MATCH (b:SemanticMemory {id: $b_id}) MERGE (a)-[:COMPLEMENTARY {confidence: $conf}]->(b) MERGE (b)-[:COMPLEMENTARY {confidence: $conf}]->(a) """
            async with self._neo4j.session() as session:
                await session.run(
                    cypher,
                    a_id=conflict.memory_a_id,
                    b_id=conflict.memory_b_id,
                    conf=conflict.confidence,
                )
```
### 7.3 RepresentationRepulsion 完整 Python 实现

```python
from __future__ import annotations
import logging
from typing import Optional
import numpy as np
from neo4j import AsyncDriver
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text

logger = logging.getLogger(__name__)


class RepresentationRepulsion:
    """
    表征排斥 — 对语义过近但实际不同的记忆拉开嵌入距离。
    灵感来源：神经科学中的反向重播（reverse replay）—
    在学习新记忆时，系统会"反向重播"相关记忆以区分新旧表征，
    避免灾难性遗忘。
    当两条记忆的向量余弦相似度超过 threshold 时，
    在嵌入空间中沿连线方向将两者推开 gamma 距离。
    """

    def __init__(
        self,
        neo4j: AsyncDriver,
        db_session: AsyncSession,
    ) -> None:
        """
        初始化表征排斥器。
        Args:
            neo4j: Neo4j 异步驱动。
            db_session: SQLAlchemy 异步会话（用于 pgvector 向量读写）。
        """
        self._neo4j = neo4j
        self._db_session = db_session

    async def repulse(
        self,
        user_id: str,
        threshold: float = 0.95,
        gamma: float = 0.1,
    ) -> dict:
        """
        执行表征排斥操作。
        步骤:
        1. 从 pgvector 搜索与用户记忆中高相似度的对
        2. 从 Neo4j 确认这些对确实不是同一概念（无 COMPLEMENTARY/IS_ABSTRACTION_OF 边）
        3. 在嵌入空间中推开两者
        Args:
        user_id: 用户 ID。
        threshold: 相似度阈值，超过此值触发排斥。
        gamma: 排斥力度（在嵌入空间中的移动距离）。
        Returns:
        {"scanned": int, "repulsed_pairs": int}
        """
        # 1. 从 pgvector 搜索高相似对
        # pgvector: 读取用户记忆的向量用于两两相似度计算
        stmt = text("""
            SELECT memory_id, embedding
            FROM user_memory
            WHERE owner_account_id = :user_id
              AND embedding IS NOT NULL
            LIMIT 200
        """)
        result = await self._db_session.execute(stmt, {"user_id": user_id})
        rows = result.fetchall()
        if not rows:
            return {"scanned": 0, "repulsed_pairs": 0}
        repulsed_pairs = 0
        point_map = {str(r[0]): r for r in rows}
        point_ids = list(point_map.keys())
        # 2. 检查 Neo4j 中是否已有关联边
        batch_cypher = """
            UNWIND $pairs AS pair
            MATCH (a:MemoryNode {id: pair[0]})
            MATCH (b:MemoryNode {id: pair[1]})
            OPTIONAL MATCH (a)-[r]-(b)
            WHERE r IS NULL
            RETURN pair[0] AS id_a, pair[1] AS id_b
            """
        # 3. 对每对高相似但无关联的节点执行排斥
        updates: list[dict] = []
        for i in range(len(point_ids)):
            for j in range(i + 1, len(point_ids)):
                pid_a, pid_b = point_ids[i], point_ids[j]
        pa, pb = point_map[pid_a], point_map[pid_b]
        # 计算余弦相似度（pgvector: embedding 为第 2 列）
        vec_a = np.array(pa[1], dtype=np.float32)
        vec_b = np.array(pb[1], dtype=np.float32)
        cos_sim = float(
            np.dot(vec_a, vec_b) / (np.linalg.norm(vec_a) * np.linalg.norm(vec_b) + 1e-10)
        )
        if cos_sim < threshold:
            continue
            # 排斥: 沿连线方向各推 gamma/2
        direction = vec_a - vec_b
        norm_dir = direction / (np.linalg.norm(direction) + 1e-10)
        new_a = vec_a + norm_dir * (gamma / 2)
        new_b = vec_b - norm_dir * (gamma / 2)
        # 归一化
        new_a = new_a / (np.linalg.norm(new_a) + 1e-10)
        new_b = new_b / (np.linalg.norm(new_b) + 1e-10)
        updates.append(
            {
                "id": pid_a,
                "vector": new_a.tolist(),
            }
        )
        updates.append(
            {
                "id": pid_b,
                "vector": new_b.tolist(),
            }
        )
        repulsed_pairs += 1
        # 批量更新 pgvector
        if updates:
            for u in updates:
                update_stmt = text("""
                    UPDATE user_memory
                    SET embedding = CAST(:vec AS vector)
                    WHERE memory_id = :mid
                """)
                await self._db_session.execute(update_stmt, {
                    "vec": str(u["vector"]),
                    "mid": u["id"],
                })
            await self._db_session.commit()
        return {"scanned": len(rows), "repulsed_pairs": repulsed_pairs}
```

---

##
8. 技能池
灵感来源： procedural memory（程序性记忆）— 通过重复练习形成的自动化技能模式。

### 8.1 SkillEmergence 完整 Python 实现

```python
from __future__ import annotations
import logging
import math
from datetime import datetime, timezone
from enum import Enum
from typing import Optional
from pydantic import BaseModel, Field
import redis.asyncio as aioredis
from neo4j import AsyncDriver
from openai import AsyncOpenAI

logger = logging.getLogger(__name__)


# ── 模型 ──────────────────────────────────────────────────
class SkillStatus(str, Enum):
    """
    技能生命周期状态"""

    CANDIDATE = "candidate"
    # 候选: 刚检测到模式
    EMERGING = "emerging"
    # 涌现中: 已提取模板
    ACTIVE = "active"
    # 活跃: 成熟度达标，可复用
    STALE = "stale"
    # 过时: 长期未使用
    DEPRECATED = "deprecated"

    # 废弃: 被新技能替代
    class Skill(BaseModel):
        """
        技能模型"""

        skill_id: str
        name: str = Field(description="技能名称")
        description: str = ""
        template: str = Field(default="", description="参数化行为模板")
        parameters: list[dict] = Field(default_factory=list, description="模板参数定义")
        user_id: str = ""
        status: SkillStatus = SkillStatus.CANDIDATE
        maturity: float = Field(default=0.0, ge=0.0, le=1.0, description="成熟度")
        use_count: int = Field(default=0, ge=0, description="使用次数")
        frequency: int = Field(default=0, ge=0, description="检测到的行为频率")
        first_seen_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
        last_used_at: Optional[datetime] = None
        last_updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
        source_memories: list[str] = Field(default_factory=list, description="来源记忆 ID")

        class SkillConfig(BaseModel):
            """
            技能涌现配置"""

            # 频率阈值
            min_pattern_frequency: int = Field(default=3, ge=1, description="最低模式频率")
            pattern_window_days: int = Field(default=30, ge=1, description="模式检测窗口")
            # 成熟度
            maturity_active_threshold: float = Field(default=0.7, ge=0.0, le=1.0)
            maturity_stale_threshold: float = Field(default=0.2, ge=0.0, le=1.0)
            stale_days: int = Field(default=90, ge=1, description="技能过时的天数阈值")
            # LLM
            extraction_model: str = Field(default="gpt-4o-mini")
            extraction_temperature: float = Field(default=0.2)
            # ── LLM Prompt 模板 ────────────────────────────────────────
            SKILL_EXTRACTION_PROMPT = """ 你是一个行为模式分析器。请从以下重复行为序列中提取可复用的参数化技能模板。
            ##
            重复行为序列 {sequences} 要求： 1. 提取行为的核心模式和不变结构 2. 识别可参数化的变量（如时间、地点、对象等） 3. 输出 JSON 格式 输出格式: {{ "name": "技能名称（简洁中文）", "description": "技能描述", "template": "包含 {{参数}} 的行为模板", "parameters": [
            {{"name": "参数名", "type": "string/number/date", "description": "参数说明"}} ] }} """


SKILL_UPDATE_PROMPT = """
你是一个技能更新器。根据新证据更新已有技能。
##
当前技能 名称: {skill_name} 描述: {skill_description} 模板: {skill_template} 使用次数: {use_count}
##
新证据（最近行为） {new_evidence} 请决定： 1. 是否需要更新技能描述或模板 2. 是否需要新增/删除/修改参数 输出格式(JSON): {{ "action": "keep|update|deprecate", "name": "更新后的名称（如果 action=update）", "description": "更新后的描述", "template": "更新后的模板", "parameters": [参数列表], "reason": "更新原因" }} """
# ── 技能生命周期状态机 ────────────────────────────────────
# 状态转移规则:
# CANDIDATE → EMERGING: LLM 成功提取模板
# EMERGING → ACTIVE: maturity >= active_threshold
# ACTIVE → STALE:
# last_used_at 距今 > stale_days
# STALE → ACTIVE:
# 再次使用
# any → DEPRECATED:
# 被新技能替代
SKILL_TRANSITIONS: dict[SkillStatus, list[SkillStatus]] = {
    SkillStatus.CANDIDATE: [SkillStatus.EMERGING, SkillStatus.DEPRECATED],
    SkillStatus.EMERGING: [SkillStatus.ACTIVE, SkillStatus.CANDIDATE, SkillStatus.DEPRECATED],
    SkillStatus.ACTIVE: [SkillStatus.STALE, SkillStatus.DEPRECATED],
    SkillStatus.STALE: [SkillStatus.ACTIVE, SkillStatus.DEPRECATED],
    SkillStatus.DEPRECATED: [],
}


class SkillEmergence:
    """
    技能涌现器 — 从高频行为模式中自动提取可复用技能。 工作流程: 1. 扫描 TKG 中的高频行为边 2. 聚类形成候选模式
    3. LLM 提取参数化模板
    4. 计算成熟度，决定状态转移
    5. 增量更新已有技能
    """

    def __init__(
        self,
        neo4j: AsyncDriver,
        redis: aioredis.Redis,
        llm_client: AsyncOpenAI,
        config: Optional[SkillConfig] = None,
    ) -> None:
        """
        初始化技能涌现器。 Args: neo4j: Neo4j 异步驱动。 redis: Redis 异步客户端（缓存技能池）。
        llm_client: OpenAI 异步客户端。
        config: 技能配置。
        """


self._neo4j = neo4j
self._redis = redis
self._llm = llm_client
self._config = config or SkillConfig()


async def scan_and_emerge(self, user_id: str) -> list[Skill]:
    """
    扫描 TKG 高频行为边，判定候选，提取/更新技能。 Args: user_id: 用户 ID。 Returns:
    新涌现或更新的技能列表。
    """
    # 1. 扫描高频行为模式
    patterns = await self._scan_high_frequency_patterns(user_id)
    results: list[Skill] = []
    for pattern in patterns:
        pattern_key = pattern["pattern"]
        frequency = pattern["count"]
        memory_ids = pattern["keys"]
        # 2. 检查是否已有技能
        existing = await self._find_existing_skill(user_id, pattern_key)
        if existing is not None:
            # 3. 增量更新
            updated = await self._update_skill(
                existing,
                {
                    "frequency": frequency,
                    "new_memories": memory_ids,
                },
            )
            results.append(updated)
        elif frequency >= self._config.min_pattern_frequency:
            # 4. 新技能提取
            pattern_memories = await self._fetch_memories(memory_ids)
            if pattern_memories:
                new_skill = await self._extract_template(pattern_memories)
                if new_skill:
                    new_skill.user_id = user_id
                    new_skill.frequency = frequency
                    new_skill.source_memories = memory_ids
                    await self._persist_skill(new_skill)
                    results.append(new_skill)
                    return results

    async def _scan_high_frequency_patterns(self, user_id: str) -> list[dict]:
        """
        扫描 TKG 中的高频行为模式。 使用 Neo4j Cypher 统计在时间窗口内的重复边序列。 Args: user_id: 用户 ID。
        Returns:
        候选模式列表。
        """
        cypher = """
        MATCH (e:Episode)-[:BELONGS_TO]->(u:User {id: $user_id})
        WHERE e.created_at >= datetime() - duration({days: $window})
        WITH e.content AS content, e.id AS eid
        WITH content, collect(eid) AS eids
        WHERE size(eids) >= $min_freq
        RETURN substring(content, 0, 200) AS pattern, size(eids) AS count, eids AS keys
        ORDER BY count DESC
        LIMIT 20
        """
        async with self._neo4j.session() as session:
            result = await session.run(
                cypher,
                user_id=user_id,
                window=self._config.pattern_window_days,
                min_freq=self._config.min_pattern_frequency,
            )
            records = await result.data()
            return records

        async def _find_existing_skill(
            self,
            user_id: str,
            pattern_key: str,
        ) -> Optional[Skill]:
            """
            查找已有技能。"""
            cypher = """ MATCH (s:Skill)-[:BELONGS_TO]->(u:User {id: $user_id}) WHERE s.status IN ['candidate', 'emerging', 'active'] AND s.name CONTAINS $key
            RETURN s
            LIMIT 1
            """
            async with self._neo4j.session() as session:
                result = await session.run(cypher, user_id=user_id, key=pattern_key[:50])
                records = await result.data()
                if records:
                    return Skill(**records[0]["s"])
                    return None

            async def _fetch_memories(self, memory_ids: list[str]) -> list[dict]:
                """
                从 Neo4j 批量获取记忆内容。"""
                cypher = """ UNWIND $ids AS mid MATCH (n:MemoryNode {id: mid})
                RETURN n.id AS id, n.content AS content, n.created_at AS ts
                """
                async with self._neo4j.session() as session:
                    result = await session.run(cypher, ids=memory_ids)
                    return await result.data()

                async def _extract_template(self, pattern_memories: list[dict]) -> Optional[Skill]:
                    """
                    LLM 从重复行为序列中提取参数化模板。 Args: pattern_memories: 重复行为序列的记忆列表。 Returns:
                    提取的技能，或 None。
                    """
                    sequences_text = "\n".join(
                        f"{i+1}. [{m['ts']}] {m['content']}"
                        for i, m in enumerate(pattern_memories[:10])
                    )
                    prompt = SKILL_EXTRACTION_PROMPT.format(sequences=sequences_text)
                    try:
                        resp = await self._llm.chat.completions.create(
                            model=self._config.extraction_model,
                            messages=[{"role": "user", "content": prompt}],
                            temperature=self._config.extraction_temperature,
                            max_tokens=500,
                            response_format={"type": "json_object"},
                        )
                        import json

                        parsed = json.loads(resp.choices[0].message.content or "{}")
                        skill = Skill(
                            skill_id=f"skill_{hash(parsed.get('name', ''))}",
                            name=parsed.get("name", "unnamed_skill"),
                            description=parsed.get("description", ""),
                            template=parsed.get("template", ""),
                            parameters=parsed.get("parameters", []),
                            status=SkillStatus.CANDIDATE,
                        )
                        return skill
                    except Exception as e:
                        logger.warning("Skill extraction failed: %s", e)
                        return None

                    async def _update_skill(
                        self,
                        existing: Skill,
                        new_evidence: dict,
                    ) -> Skill:
                        """
                        增量更新已有技能。 根据新证据（频率增加、新记忆）更新技能成熟度， 必要时通过 LLM 更新模板。 Args:
                        existing: 已有技能。
                        new_evidence: 新证据字典。
                        Returns:
                        更新后的技能。
                        """
                        # 更新频率和使用计数
                        existing.frequency = max(
                            existing.frequency, new_evidence.get("frequency", existing.frequency)
                        )
                        existing.use_count += 1
                        existing.last_used_at = datetime.now(timezone.utc)
                        existing.last_updated_at = datetime.now(timezone.utc)
                        # 重新计算成熟度
                        existing.maturity = self._compute_maturity(existing)
                        # 如果有足够新证据，通过 LLM 判定是否需要更新模板
                        if (
                            new_evidence.get("new_memories")
                            and len(new_evidence["new_memories"]) > 2
                        ):
                            memories = await self._fetch_memories(new_evidence["new_memories"])
                            if memories:
                                try:
                                    evidence_text = "\n".join(
                                        f"- {m['content'][:200]}" for m in memories[:5]
                                    )
                                    prompt = SKILL_UPDATE_PROMPT.format(
                                        skill_name=existing.name,
                                        skill_description=existing.description,
                                        skill_template=existing.template,
                                        use_count=existing.use_count,
                                        new_evidence=evidence_text,
                                    )
                                    resp = await self._llm.chat.completions.create(
                                        model=self._config.extraction_model,
                                        messages=[{"role": "user", "content": prompt}],
                                        temperature=0.0,
                                        max_tokens=400,
                                        response_format={"type": "json_object"},
                                    )
                                    import json

                                    parsed = json.loads(resp.choices[0].message.content or "{}")
                                    action = parsed.get("action", "keep")
                                    if action == "deprecate":
                                        existing.status = SkillStatus.DEPRECATED
                                    elif action == "update":
                                        existing.name = parsed.get("name", existing.name)
                                        existing.description = parsed.get(
                                            "description", existing.description
                                        )
                                        existing.template = parsed.get(
                                            "template", existing.template
                                        )
                                        existing.parameters = parsed.get(
                                            "parameters", existing.parameters
                                        )
                                except Exception as e:
                                    logger.warning("Skill update LLM call failed: %s", e)
                                    # 状态转移
                                    existing.status = self._transition_status(existing)
                                    await self._persist_skill(existing)
                                    return existing

                        def _compute_maturity(self, skill: Skill) -> float:
                            """
                            计算技能成熟度。 成熟度 = sigmoid(frequency_factor + usage_factor + recency_factor) - frequency_factor: log(1 + frequency) / log(10) - usage_factor: log(1 + use_count) / log(20)
                            - recency_factor: 距上次使用的天数衰减
                            Args:
                            skill: 技能对象。
                            Returns:
                            成熟度 [0, 1]。
                            """


freq_factor = math.log1p(skill.frequency) / math.log(10)
usage_factor = math.log1p(skill.use_count) / math.log(20)
recency_factor = 1.0
if skill.last_used_at:
    days_since = max(
        0.0, (datetime.now(timezone.utc) - skill.last_used_at).total_seconds() / 86400.0
    )
    recency_factor = 0.9**days_since
    raw = freq_factor * 0.4 + usage_factor * 0.4 + recency_factor * 0.2
    return 1.0 / (1.0 + math.exp(-5.0 * (raw - 0.5)))


def _transition_status(self, skill: Skill) -> SkillStatus:
    """
    根据成熟度和使用状态执行状态转移。 Args: skill: 技能对象。 Returns:
    转移后的状态。
    """


cfg = self._config
current = skill.status
if current == SkillStatus.CANDIDATE and skill.template:
    return SkillStatus.EMERGING
    if current == SkillStatus.EMERGING and skill.maturity >= cfg.maturity_active_threshold:
        return SkillStatus.ACTIVE
        if current == SkillStatus.ACTIVE and skill.last_used_at:
            days_since = (datetime.now(timezone.utc) - skill.last_used_at).total_seconds() / 86400.0
            if days_since > cfg.stale_days:
                return SkillStatus.STALE
                if current == SkillStatus.STALE and skill.use_count > 0:
                    recent_use = (
                        skill.last_used_at
                        and (datetime.now(timezone.utc) - skill.last_used_at).total_seconds()
                        < 86400.0
                    )
                    if recent_use:
                        return SkillStatus.ACTIVE
                        return current


async def _persist_skill(self, skill: Skill) -> None:
    """
    将技能持久化到 Neo4j。"""


cypher = """ MERGE (s:Skill {id: $id}) SET
s.name = $name,
s.description = $description,
s.template = $template,
s.parameters = $parameters,
s.user_id = $user_id,
s.status = $status,
s.maturity = $maturity,
s.use_count = $use_count,
s.frequency = $frequency,
s.first_seen_at = datetime($first_seen),
s.last_used_at = CASE WHEN $last_used IS NULL THEN NULL ELSE datetime($last_used) END,
s.last_updated_at = datetime($last_updated)
"""
async with self._neo4j.session() as session:
    await session.run(
        cypher,
        id=skill.skill_id,
        name=skill.name,
        description=skill.description,
        template=skill.template,
        parameters=skill.parameters,
        user_id=skill.user_id,
        status=skill.status.value,
        maturity=skill.maturity,
        use_count=skill.use_count,
        frequency=skill.frequency,
        first_seen=skill.first_seen_at.isoformat(),
        last_used=skill.last_used_at.isoformat() if skill.last_used_at else None,
        last_updated=skill.last_updated_at.isoformat(),
    )
    # 更新 Redis 缓存
    await self._redis.delete(f"skill:pool:{skill.user_id}")
```

---

### 8.5 Skill 即时触发机制（v5.2 新增）

> **灵感来源**：Hermes Agent — "Autonomous skill creation after complex tasks"
> **实施优先级**：P0
> **依赖**：断裂点 ⚠️-1 已修复（`SkillEmergence.scan_and_emerge` 已接通巩固引擎）

#### 设计思路

当前 Skill 涌现是**每日凌晨巩固时批处理扫描**（Celery `daily-consolidation`，每日 3:00），延迟太大。吸纳 Hermes 的**任务结束后即时评估**机制，形成"即时涌现 + 批量巩固"双路径。

#### 触发流程

```
对话/任务结束
    │
    ▼
PostExecutionHook（新增，挂在 AssistantAgentService._write_memory_from_conversation 之后）
    │
    ├─ 检查触发条件（满足任一）:
    │   ├── 本次任务 tool_call ≥ 5 次（复杂任务）
    │   ├── 出错后自动恢复（自我纠错）
    │   ├── 用户纠正 Agent 输出（correction signal）
    │   └── 非显而易见的工作流（novel workflow detection）
    │
    ▼ [命中触发条件]
异步后台任务（Celery beat_one_off）
    │
    ├─ 1. 收集执行轨迹（trajectory）
    │      从本次会话的 Episode 节点提取工具调用序列
    │
    ├─ 2. 调用 SkillEmergence._extract_template()    ← 复用现有代码
    │      LLM 分析轨迹，提取参数化技能模板
    │
    ├─ 3. 查找已有 Skill（_find_existing_skill）      ← 复用现有代码
    │      ├── 命中 → _update_skill（增量更新，调用 bump_use）
    │      └── 未命中 → _persist_skill（创建 CANDIDATE 状态 Skill）
    │
    └─ 4. 完全静默，用户无感
```

#### 与现有架构的融合点

| 现有组件 | 融合方式 |
|---|---|
| `AssistantAgentService._write_memory_from_conversation()` | 在现有后台线程中追加调用 `PostExecutionHook` |
| `SkillEmergence._extract_template()` | **复用现有代码**，无需修改 |
| `SkillEmergence._find_existing_skill()` | **复用现有代码** |
| `SkillEmergence._update_skill()` / `_persist_skill()` | **复用现有代码** |
| `ConsolidationEngine` Phase 5（SKILL） | **保持不变**，每日巩固仍做批量扫描（作为即时涌现的补充） |

#### 配置项（SkillConfig 新增）

```python
instant_emergence_enabled: bool = True
instant_emergence_min_tool_calls: int = 5
instant_emergence_model: str = "gpt-4o-mini"  # 复用 extraction_model
instant_emergence_async: bool = True  # 异步执行，不阻塞响应
```

---

### 8.6 Skill 分层加载策略（Progressive Disclosure，v5.2 新增）

> **灵感来源**：分层加载设计思想（⚠️ 此设计思想参考自社区文章对 Hermes 的描述，但未能在 Hermes 源码中直接找到 `progressive_disclosure` 或 `tier_loader` 命名的实现文件，标注为设计思想参考）
> **实施优先级**：P1

#### 设计思路

当前 `DigestManager._fetch_skills()` 查所有 ACTIVE 状态 `:Skill` 节点，**全量返回** name+description+template+use_count，拼接后注入 Digest。当 Skill 数量增长到 100+ 时，上下文成本失控。采用三层渐进式披露解决。

#### 三层加载

```
┌─────────────────────────────────────────────────────┐
│ Tier 0：目录卡片（始终注入 system prompt）            │
│ 仅加载：skill_name + description（一行摘要）          │
│ 总量上限：~3000 tokens                               │
│ 存储：Redis hash key "skill:tier0:{user_id}"         │
└──────────────────────┬──────────────────────────────┘
                       │ Agent 判断某 Skill 方向匹配
                       ▼
┌─────────────────────────────────────────────────────┐
│ Tier 1：完整内容（按需加载）                          │
│ 加载：template + parameters + 完整描述               │
│ 触发：Agent 主动请求 / ToolSelector 匹配命中          │
│ 存储：Neo4j :Skill 节点全量属性                       │
└──────────────────────┬──────────────────────────────┘
                       │ 需要更多细节
                       ▼
┌─────────────────────────────────────────────────────┐
│ Tier 2：补充说明（深度参考）                          │
│ 加载：source_memories（原始行为序列）+ 使用示例       │
│ 触发：Agent 显式请求 detail（新增 tool: get_skill_detail）│
│ 存储：Neo4j :Skill.source_memories + Episode 节点    │
└─────────────────────────────────────────────────────┘
```

#### Token 预算控制

```python
# DigestManager 配置新增
skill_tier0_max_tokens: int = 3000      # Tier 0 总量上限
skill_tier0_max_items: int = 50         # Tier 0 最多 50 个技能卡片
skill_tier1_max_concurrent: int = 3     # Tier 1 同时展开不超过 3 个
skill_tier2_enabled: bool = True        # Tier 2 开关
```

#### 与现有架构的融合点

| 现有组件 | 改造方式 |
|---|---|
| `DigestManager._fetch_skills()` | 改为只返回 Tier 0 数据（name + description） |
| `ToolSelectorService.select_tools()` | 匹配命中后自动触发 Tier 1 加载 |
| `SkillToolFactory.build_tools()` | 构建 tool 时注入 Tier 1 内容 |
| 新增 `get_skill_detail` tool | Agent 可主动请求 Tier 2 深度信息 |

---

### 8.7 Skill 生命周期治理（Curator + bump_use，v5.2 部分实施）

> **灵感来源**：Hermes Agent — "Skills self-improve during use"
> **实施优先级**：P1
> **实施状态**：Curator 周期剪枝已实施（断裂点 ⚠️-3 修复），bump_use 实时统计待实施

#### 8.7.1 实时使用统计（bump_use，待实施）

```
Agent 调用 Skill（SkillExecutor 执行）
    │
    ▼
SkillExecutor 执行后（新增 hook）
    │
    ├─ Redis HINCRBY skill:stats:{user_id} {skill_id}:use_count 1
    ├─ Redis HSET  skill:stats:{user_id} {skill_id}:last_used_at now
    └─ 异步标记 Neo4j :Skill 节点（延迟批量写入，避免高频写图）
```

#### 8.7.2 Curator 周期任务（已实施）

```
Celery Beat: 每周日凌晨 04:00 执行（crontab(hour=4, minute=0, day_of_week=0)）
    │
    ▼
SkillEmergence.curate_skills(user_id)  ← 已实现
    │
    ├─ 1. 读取所有 :Skill 节点（status IN [active, stale]）
    │
    ├─ 2. 合并 Redis 实时统计到 Neo4j
    │      use_count = Neo4j.use_count + Redis.use_count
    │      last_used_at = max(Neo4j, Redis)
    │
    ├─ 3. 重算成熟度（_compute_maturity）    ← 复用现有代码
    │      maturity = freq*0.4 + usage*0.4 + recency*0.2
    │
    ├─ 4. 状态转移判定
    │      ├── maturity < 0.2 且 90 天未用 → ACTIVE → STALE
    │      ├── STALE 且 30 天未用 → DEPRECATED
    │      └── STALE 但近期又被使用 → STALE → ACTIVE（复活）
    │
    └─ 5. 报告：scanned / transitioned / deprecated
```

#### 8.7.3 配置项（SkillConfig 新增）

```python
curator_enabled: bool = True
curator_interval_days: int = 7
curator_merge_similarity_threshold: float = 0.85
curator_stale_to_deprecated_days: int = 30
bump_use_redis_enabled: bool = True
bump_use_neo4j_flush_interval: int = 3600  # 每小时批量回写 Neo4j
```

---

##
9. Policy 层

### 9.1 PolicyRouter 完整 Python 实现

```python
from __future__ import annotations
import logging
from datetime import datetime, timezone
from enum import Enum
from typing import Optional
from pydantic import BaseModel, Field
from neo4j import AsyncDriver
from openai import AsyncOpenAI

logger = logging.getLogger(__name__)

# ── 模型 ──────────────────────────────────────────────────


class QueryIntent(str, Enum):
    """查询意图"""

    FACTUAL = "factual"  # 事实查询 ("他叫什么名字?")
    TEMPORAL = "temporal"  # 时间查询 ("上周三发生了什么?")
    RELATIONAL = "relational"  # 关系查询 ("A和B是什么关系?")
    ACTION = "action"  # 行动指令 ("帮我安排明天日程")
    REFLECTION = "reflection"  # 自省 ("我最近在忙什么?")
    GREETING = "greeting"  # 问候
    META = "meta"  # 元查询 ("你记得什么?")


class IntentClassification(BaseModel):
    """意图分类结果"""

    intent: QueryIntent
    confidence: float = Field(ge=0.0, le=1.0)
    entities: list[str] = Field(default_factory=list)
    time_reference: Optional[str] = None


class ViewProfile(BaseModel):
    """视图配置"""

    view_name: str
    description: str
    node_labels: list[str]
    edge_types: list[str]
    score_boost: float = Field(default=1.0)


# ── 预定义视图 ────────────────────────────────────────────

PREDEFINED_VIEWS: dict[str, ViewProfile] = {
    "profile": ViewProfile(
        view_name="profile",
        description="用户画像视图",
        node_labels=["User", "Trait", "Preference"],
        edge_types=["HAS_TRAIT", "HAS_PREFERENCE"],
    ),
    "episodes": ViewProfile(
        view_name="episodes",
        description="事件记忆视图",
        node_labels=["Episode"],
        edge_types=["NEXT", "CAUSED_BY"],
        score_boost=1.2,
    ),
    "skills": ViewProfile(
        view_name="skills",
        description="技能视图",
        node_labels=["Skill"],
        edge_types=["REQUIRES", "BELONGS_TO"],
    ),
    "relations": ViewProfile(
        view_name="relations",
        description="关系网络视图",
        node_labels=["Person", "Organization"],
        edge_types=["KNOWS", "WORKS_WITH", "RELATED_TO"],
    ),
    "knowledge": ViewProfile(
        view_name="knowledge",
        description="知识视图",
        node_labels=["SemanticMemory", "Fact"],
        edge_types=["SUPPORTS", "CONTRADICTS"],
    ),
}


# ── 核心类 ──────────────────────────────────────────────────


class PolicyRouter:
    """
    策略路由器 — 决定读写路径、视图选择、Early Stop。
    职责:
      1. classify_query: 将用户查询分类为意图
      2. select_views: 根据意图选择查询视图
      3. should_use_system2: 判断是否需要深度搜索
      4. select_retrieval_strategy: 依赖健康检查执行降级路由

    降级逻辑（依赖故障检测）:
      - Neo4j 不可用时，路由到 "vector_only" 策略（仅 pgvector）
      - pgvector 不可用时，路由到 "graph_only" 策略（仅 TKG）
      - 两者都不可用时，路由到 "digest_only" 策略（仅 Redis 缓存）
      - 全部不可用时，路由到 "disabled" 策略（跳过记忆注入）
    """

    def __init__(
        self,
        neo4j: AsyncDriver,
        llm_client: Optional[AsyncOpenAI] = None,
    ) -> None:
        """
        初始化策略路由器。
        Args:
            neo4j: Neo4j 异步驱动。
            llm_client: LLM 客户端（用于意图分类，可选；不传则使用规则分类）。
        """
        self._neo4j = neo4j
        self._llm = llm_client

    async def classify_query(self, query: str) -> IntentClassification:
        """
        查询意图分类。
        优先使用 LLM 分类，不可用时回退到规则分类。
        Args:
            query: 用户查询文本。
        Returns:
            意图分类结果。
        """
        if self._llm:
            try:
                return await self._llm_classify(query)
            except Exception as e:
                logger.warning("LLM classification failed, fallback to rules: %s", e)
                return self._rule_classify(query)
        return self._rule_classify(query)

    async def select_views(
        self,
        intent: IntentClassification,
        user_id: str,
    ) -> list[str]:
        """
        查询自适应视图选择 — 根据意图选择最相关的视图子集。
        映射规则:
          - FACTUAL → knowledge
          - TEMPORAL → episodes
          - RELATIONAL → relations
          - ACTION → profile, skills
          - REFLECTION → profile, episodes, knowledge
          - GREETING → profile
          - META → all views
        Args:
            intent: 意图分类结果。
            user_id: 用户 ID。
        Returns:
            视图名称列表。
        """
        intent_view_map: dict[QueryIntent, list[str]] = {
            QueryIntent.FACTUAL: ["knowledge"],
            QueryIntent.TEMPORAL: ["episodes"],
            QueryIntent.RELATIONAL: ["relations"],
            QueryIntent.ACTION: ["profile", "skills"],
            QueryIntent.REFLECTION: ["profile", "episodes", "knowledge"],
            QueryIntent.GREETING: ["profile"],
            QueryIntent.META: list(PREDEFINED_VIEWS.keys()),
        }
        view_names = intent_view_map.get(intent.intent, ["profile"])
        # 确保视图存在
        return [v for v in view_names if v in PREDEFINED_VIEWS]

    def should_use_system2(self, intent: IntentClassification) -> bool:
        """
        System 1/2 路由判定。
        以下场景需要 System 2（深度搜索）:
          - FACTUAL 且置信度 < 0.9（可能需要多跳推理）
          - TEMPORAL（需要时间范围查询）
          - RELATIONAL（需要图遍历）
          - REFLECTION（需要全局概览）
          - META（需要完整记忆）
        其他场景使用 System 1（Digest 快速路径）。
        Args:
            intent: 意图分类结果。
        Returns:
            True 表示使用 System 2。
        """
        always_system2 = {
            QueryIntent.TEMPORAL,
            QueryIntent.RELATIONAL,
            QueryIntent.REFLECTION,
            QueryIntent.META,
        }
        if intent.intent in always_system2:
            return True
        if intent.intent == QueryIntent.FACTUAL and intent.confidence < 0.9:
            return True
        return False

    # ── 内部方法 ─────────────────────────────────────────

    async def _llm_classify(self, query: str) -> IntentClassification:
        """LLM 意图分类。"""
        intent_lines = "\n".join(f"- {t.value}: {t.value}" for t in QueryIntent)
        prompt = f"""对以下查询进行意图分类。
查询: {query}
可选意图:
{intent_lines}
输出 JSON: {{"intent": "意图名", "confidence": 0.0-1.0, "entities": ["实体1"], "time_reference": "时间引用或null"}}
"""
        resp = await self._llm.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.0,
            max_tokens=150,
            response_format={"type": "json_object"},
        )
        import json

        parsed = json.loads(resp.choices[0].message.content or "{}")
        return IntentClassification(
            intent=QueryIntent(parsed.get("intent", "factual")),
            confidence=float(parsed.get("confidence", 0.5)),
            entities=parsed.get("entities", []),
            time_reference=parsed.get("time_reference"),
        )

    @staticmethod
    def _rule_classify(query: str) -> IntentClassification:
        """规则回退意图分类 — 基于关键词匹配。"""
        query_lower = query.lower()
        # 时间关键词
        time_keywords = ["昨天", "上周", "前天", "最近", "什么时候", "几号", "哪天"]
        if any(kw in query_lower for kw in time_keywords):
            return IntentClassification(intent=QueryIntent.TEMPORAL, confidence=0.7)
        # 关系关键词
        rel_keywords = ["关系", "认识", "朋友", "同事", "谁是"]
        if any(kw in query_lower for kw in rel_keywords):
            return IntentClassification(intent=QueryIntent.RELATIONAL, confidence=0.7)
        # 行动关键词
        action_keywords = ["帮我", "安排", "设置", "提醒", "创建"]
        if any(kw in query_lower for kw in action_keywords):
            return IntentClassification(intent=QueryIntent.ACTION, confidence=0.8)
        # 自省关键词
        refl_keywords = ["我最近", "总结", "回顾", "我的", "忙什么"]
        if any(kw in query_lower for kw in refl_keywords):
            return IntentClassification(intent=QueryIntent.REFLECTION, confidence=0.7)
        # 问候
        greeting_keywords = ["你好", "嗨", "hello", "hi"]
        if any(kw in query_lower for kw in greeting_keywords):
            return IntentClassification(intent=QueryIntent.GREETING, confidence=0.9)
        # 元查询
        meta_keywords = ["你记得", "你认识", "你知道什么", "记忆"]
        if any(kw in query_lower for kw in meta_keywords):
            return IntentClassification(intent=QueryIntent.META, confidence=0.7)
        return IntentClassification(intent=QueryIntent.FACTUAL, confidence=0.5)
```
### 9.2 记忆治理

```python
from __future__ import annotations
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional
from pydantic import BaseModel, Field
from neo4j import AsyncDriver

logger = logging.getLogger(__name__)


# ── 模型 ──────────────────────────────────────────────────
class AuditEntry(BaseModel):
    """
    审计日志条目"""

    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    action: str
    user_id: str
    memory_id: Optional[str] = None
    details: dict = Field(default_factory=dict)
    actor: str = Field(default="system")


class PIIField(BaseModel):
    """
    PII 字段定义"""

    field_name: str
    pii_type: str
    # email, phone, ssn, name, address
    masking_rule: str = "hash"
    # hash, redact, truncate


class MemoryGovernor:
    """
    记忆治理器 — GDPR 合规、PII 过滤、审计日志。 职责: 1. GDPR 删除: 按 user_id 级联删除所有记忆数据 2. PII 过滤: 在写入前检测和脱敏个人信息
    3. 审计日志: 记录所有关键操作
    """

    def __init__(
        self,
        neo4j: AsyncDriver,
        audit_log_func: Optional[callable] = None,
    ) -> None:
        """
        初始化治理器。 Args: neo4j: Neo4j 异步驱动。 audit_log_func: 审计日志回调函数，用于写入审计日志。
        """
        self._neo4j = neo4j
        self._audit = audit_log_func or (lambda entry: logger.info("AUDIT: %s", entry))

    async def gdpr_delete(self, user_id: str) -> dict:
        """
        GDPR 删除 — 级联删除用户的所有记忆数据。 删除范围: 1. Neo4j: 用户节点及所有关联记忆节点和边 2. PostgreSQL: 用户的 user_memory 行（含向量）
        3. Redis: 用户的缓存数据
        Args:
        user_id: 用户 ID。
        Returns:
        删除统计。
        """
        stats: dict = {"neo4j_nodes": 0, "neo4j_edges": 0}
        # 1. Neo4j 级联删除
        cypher = """ MATCH (u:User {id: $user_id}) OPTIONAL MATCH (u)-[r]-(n) DETACH DELETE u, n RETURN count(*) AS deleted
        """
        async with self._neo4j.session() as session:
            result = await session.run(cypher, user_id=user_id)
            records = await result.data()
            stats["neo4j_nodes"] = records[0]["deleted"] if records else 0
            # 2. pgvector 删除（需在调用方处理）
            # pgvector: DELETE FROM user_memory WHERE owner_account_id = :user_id
            # 3. Redis 删除（需在调用方处理）
            # 审计日志
            await self._log_audit(action="GDPR_DELETE", user_id=user_id, details=stats)
            logger.info("GDPR delete completed for user %s: %s", user_id, stats)
            return stats

    async def filter_pii(self, content: str) -> str:
        """
        PII 过滤 — 检测并脱敏内容中的个人信息。 使用简易正则匹配检测常见 PII 模式。 生产中应替换为专用 PII 检测服务。 Args:
        content: 原始内容。
        Returns:
        脱敏后的内容。
        """
        import re

        # 邮箱
        content = re.sub(
            r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b", "[EMAIL_REDACTED]", content
        )
        # 手机号（中国大陆）
        content = re.sub(r"\b1[3-9]\d{9}\b", "[PHONE_REDACTED]", content)
        # 身份证号
        content = re.sub(r"\b\d{17}[\dXx]\b", "[ID_REDACTED]", content)
        # 银行卡号
        content = re.sub(r"\b\d{16,19}\b", "[CARD_REDACTED]", content)
        return content

    async def soft_delete_memory(self, memory_id: str, user_id: str) -> bool:
        """
        软删除单条记忆 — 节点保留可恢复。
        操作: 设置 is_active=false + pgvector 清空 embedding + Redis 清缓存。
        Args: memory_id: 记忆 ID。 user_id: 用户 ID（权限校验）。
        Returns:
        是否成功删除。
        """
        # 权限校验
        check_cypher = """ MATCH (n:MemoryNode {id: $mid}) OPTIONAL MATCH (n)-[:BELONGS_TO]->(u:User {id: $uid}) RETURN u.id AS owner """
        async with self._neo4j.session() as session:
            result = await session.run(check_cypher, mid=memory_id, uid=user_id)
            records = await result.data()
            if not records or records[0]["owner"] != user_id:
                logger.warning("Unauthorized soft-delete attempt: memory=%s user=%s", memory_id, user_id)
                return False
            # 设置 is_active=false（节点保留）
            soft_delete_cypher = """ MATCH (n:MemoryNode {id: $mid}) SET n.is_active = false, n.deleted_at = datetime() """
            async with self._neo4j.session() as session:
                await session.run(soft_delete_cypher, mid=memory_id)
                # pgvector 清空 embedding + Redis 清缓存（需在调用方处理）
                # pgvector: UPDATE user_memory SET embedding = NULL WHERE memory_id = :mid
                await self._log_audit(action="SOFT_DELETE_MEMORY", user_id=user_id, memory_id=memory_id)
                return True

    async def hard_delete_memory(self, memory_id: str, user_id: str) -> bool:
        """
        彻底删除单条记忆 — 不可恢复。
        操作: DETACH DELETE + pgvector 删除 user_memory 行。
        Args: memory_id: 记忆 ID。 user_id: 用户 ID（权限校验）。
        Returns:
        是否成功删除。
        """
        # 权限校验
        check_cypher = """ MATCH (n:MemoryNode {id: $mid}) OPTIONAL MATCH (n)-[:BELONGS_TO]->(u:User {id: $uid}) RETURN u.id AS owner """
        async with self._neo4j.session() as session:
            result = await session.run(check_cypher, mid=memory_id, uid=user_id)
            records = await result.data()
            if not records or records[0]["owner"] != user_id:
                logger.warning("Unauthorized hard-delete attempt: memory=%s user=%s", memory_id, user_id)
                return False
            # 物理删除节点及关联边
            delete_cypher = """ MATCH (n:MemoryNode {id: $mid}) DETACH DELETE n """
            async with self._neo4j.session() as session:
                await session.run(delete_cypher, mid=memory_id)
                # pgvector 删除 user_memory 行（需在调用方处理）
                # pgvector: DELETE FROM user_memory WHERE memory_id = :mid
                await self._log_audit(action="HARD_DELETE_MEMORY", user_id=user_id, memory_id=memory_id)
                return True

    async def edit_memory(self, memory_id: str, user_id: str, new_content: str) -> Optional[str]:
        """
        编辑记忆内容 — 创建新节点 + 旧节点 t_invalidated_at=now。
        Args: memory_id: 旧记忆 ID。 user_id: 用户 ID（权限校验）。 new_content: 新内容。
        Returns:
        新记忆节点 ID，失败返回 None。
        """
        # 权限校验
        check_cypher = """ MATCH (n:MemoryNode {id: $mid}) OPTIONAL MATCH (n)-[:BELONGS_TO]->(u:User {id: $uid}) RETURN u.id AS owner """
        async with self._neo4j.session() as session:
            result = await session.run(check_cypher, mid=memory_id, uid=user_id)
            records = await result.data()
            if not records or records[0]["owner"] != user_id:
                logger.warning("Unauthorized edit attempt: memory=%s user=%s", memory_id, user_id)
                return None
            import uuid
            new_id = f"mem_{uuid.uuid4().hex[:12]}"
            # 旧节点失效 + 创建新节点
            edit_cypher = """ MATCH (old:MemoryNode {id: $mid}) SET old.t_invalidated_at = datetime() CREATE (new:MemoryNode {id: $new_id, content: $content, is_active: true, created_at: datetime()})-[:BELONGS_TO]->(:User {id: $uid}) MERGE (old)-[:SUPERSEDED_BY]->(new) RETURN new.id AS new_id """
            result = await session.run(edit_cypher, mid=memory_id, new_id=new_id, content=new_content, uid=user_id)
            await self._log_audit(action="EDIT_MEMORY", user_id=user_id, memory_id=memory_id, details={"new_id": new_id})
            return new_id

    async def _log_audit(self, action: str, user_id: str, **kwargs) -> None:
        """
        记录审计日志。"""
        entry = AuditEntry(action=action, user_id=user_id, **kwargs)
        try:
            if callable(self._audit):
                self._audit(entry.model_dump())
        except Exception as e:
            logger.error("Audit log failed: %s", e)
```

---

##
10. API 接口定义

### API 端点

新系统 API 完全替代旧系统 API，不做向后兼容：

| 方法 | 路径 | 说明 | 替代的旧 API |
|---|---|---|---|
| POST | /memory/write | 写入记忆事件（SalienceScorer 评分后自动调用） | 无（旧系统无此端点，写入由 confirm 触发） |
| POST | /memory/retrieve | 检索记忆（System 1/2 双路） | /user/memory (GET list) + recall_relevant_memories |
| GET | /memory/digest/{user_id} | 获取 Memory Digest | 无（旧系统无 Digest） |
| POST | /memory/consolidate/{user_id} | 触发巩固引擎 | 无（旧系统无巩固） |
| GET | /memory/graph/{user_id} | 获取记忆图谱数据（用于可视化） | 无（旧系统无图谱） |
| GET | /memory/graph/{user_id}/cluster/{type} | 获取某聚类的子图 | 无 |
| GET | /memory/{memory_id} | 获取单条记忆详情 | /user/memory/{id} (GET) |
| PUT | /memory/{memory_id} | 编辑记忆内容（创建新节点+旧节点失效） | /user/memory/{id} (POST update) |
| DELETE | /memory/{memory_id} | 软删除记忆 | /user/memory/{id} (DELETE) |
| DELETE | /memory/{memory_id}/hard | 彻底删除记忆 | 无（旧系统只有硬删除） |
| POST | /memory/{memory_id}/decay | 手动降低权重 | 无 |
| GET | /memory/skills/{user_id} | 获取涌现技能列表 | 无 |
| GET | /memory/health | 健康检查 | 无 |

**已删除的旧 API**（不做向后兼容）：
- `GET /memory-candidates` — 候选列表（不再需要候选确认流程）
- `POST /memory-candidates/{id}/confirm` — 确认候选（不再需要）
- `POST /memory-candidates/{id}/ignore` — 忽略候选（不再需要）
- `GET /user/memory/settings` — 用户设置（不再需要候选确认设置）
- `POST /user/memory/settings` — 更新设置（不再需要）

### 10.1 FastAPI 路由定义

```python
from __future__ import annotations
import logging
from datetime import datetime, timezone
from typing import Optional
from fastapi import APIRouter, HTTPException, Depends, Query
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/memory", tags=["memory"])


# ── Request/Response 模型 ──────────────────────────────────
class MemoryWriteRequest(BaseModel):
    """
    记忆写入请求
    """

    user_id: str = Field(..., min_length=1, description="用户 ID")
    content: str = Field(..., min_length=1, max_length=10000, description="记忆内容")
    memory_type: str = Field(default="episode", description="记忆类型: episode/semantic/fact")
    metadata: dict = Field(default_factory=dict, description="附加元数据")
    tags: list[str] = Field(default_factory=list, description="标签列表")

    class MemoryWriteResponse(BaseModel):
        """
        记忆写入响应
        """

        memory_id: str
        status: str = "created"
        created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

        class MemoryRetrieveRequest(BaseModel):
            """
            记忆检索请求
            """

            query: str = Field(..., min_length=1, max_length=2000, description="查询文本")
            user_id: str = Field(..., min_length=1, description="用户 ID")
            top_k: int = Field(default=20, ge=1, le=200)
            time_range_days: Optional[int] = Field(default=None, description="时间范围限制（天）")
            budget_tokens: int = Field(default=2000, ge=100, le=8000)
            views: list[str] = Field(default_factory=list, description="限定视图列表")

            class MemoryRetrieveResponse(BaseModel):
                """
                记忆检索响应
                """

                results: list[dict]
                summary: str = ""
                intent: str = ""
                retrieval_path: str = ""
                latency_ms: float = 0.0

                class ConsolidationResponse(BaseModel):
                    """
                    巩固响应
                    """

                    user_id: str
                    success: bool
                    total_items: int = 0
                    phase_results: dict = Field(default_factory=dict)
                    errors: list[str] = Field(default_factory=list)

                    class SkillListResponse(BaseModel):
                        """
                        技能列表响应
                        """

                        user_id: str
                        skills: list[dict]
                        total: int = 0

                        class HealthResponse(BaseModel):
                            """
                            健康检查响应
                            """

                            status: str = "healthy"
                            version: str = "1.0.0"
                            neo4j: bool = True
                            pgvector: bool = True
                            redis: bool = True
                            uptime_seconds: float = 0.0

                            class ErrorResponse(BaseModel):
                                """
                                错误响应
                                """

                                error_code: str
                                message: str
                                details: Optional[dict] = None
                                # ── 错误码定义 ──────────────────────────────────────────
                                ERROR_CODES: dict[int, str] = {
                                    400: "BAD_REQUEST",
                                    401: "UNAUTHORIZED",
                                    403: "FORBIDDEN",
                                    404: "NOT_FOUND",
                                    409: "CONFLICT",
                                    422: "VALIDATION_ERROR",
                                    429: "RATE_LIMITED",
                                    500: "INTERNAL_ERROR",
                                    503: "SERVICE_UNAVAILABLE",
                                }

                                # ── 路由定义 ──────────────────────────────────────────────
                                @router.post(
                                    "/write",
                                    response_model=MemoryWriteResponse,
                                    responses={
                                        400: {"model": ErrorResponse},
                                        500: {"model": ErrorResponse},
                                    },
                                    summary="写入记忆",
                                )
                                async def write_memory(
                                    request: MemoryWriteRequest,
                                ) -> MemoryWriteResponse:
                                    """
                                    将一条新记忆写入系统。
                                    流程: PII 过滤 → 解析 → 嵌入 → Neo4j 写入 → pgvector 写入 → 触发 Digest 更新
                                    """
                                    import uuid
                                    import time

                                    start = time.monotonic()
                                    # PII 过滤
                                    # content = await governor.filter_pii(request.content)
                                    memory_id = f"mem_{uuid.uuid4().hex[:12]}"
                                    # ... 实际写入逻辑 ...
                                    elapsed_ms = (time.monotonic() - start) * 1000
                                    logger.info(
                                        "Memory written: id=%s user=%s type=%s latency=%.1fms",
                                        memory_id,
                                        request.user_id,
                                        request.memory_type,
                                        elapsed_ms,
                                    )
                                    return MemoryWriteResponse(memory_id=memory_id)

                                    @router.post(
                                        "/retrieve",
                                        response_model=MemoryRetrieveResponse,
                                        responses={
                                            400: {"model": ErrorResponse},
                                            500: {"model": ErrorResponse},
                                        },
                                        summary="检索记忆",
                                    )
                                    async def retrieve_memory(
                                        request: MemoryRetrieveRequest,
                                    ) -> MemoryRetrieveResponse:
                                        """
                                        混合检索记忆 — 融合语义/关键词/图三通道。
                                        自动路由 System 1（快速）或 System 2（深度）路径。
                                        """
                                        import time

                                        start = time.monotonic()
                                        # 1. 意图分类
                                        # intent = await policy_router.classify_query(request.query)
                                        # 2. System 1/2 路由
                                        # if policy_router.should_use_system2(intent):
                                        # results = await retriever.retrieve(...)
                                        # else:
                                        # digest = await digest_manager.get_digest(request.user_id)
                                        elapsed_ms = (time.monotonic() - start) * 1000
                                        return MemoryRetrieveResponse(
                                            results=[],
                                            summary="",
                                            intent="factual",
                                            retrieval_path="system2",
                                            latency_ms=elapsed_ms,
                                        )

                                        @router.get(
                                            "/digest/{user_id}",
                                            response_model=dict,
                                            responses={404: {"model": ErrorResponse}},
                                            summary="获取记忆 Digest",
                                        )
                                        async def get_digest(
                                            user_id: str,
                                            refresh: bool = Query(
                                                default=False, description="强制刷新缓存"
                                            ),
                                        ) -> dict:
                                            """
                                            获取用户的 Memory Digest 摘要。
                                            """
                                            # if refresh:
                                            # text = await digest_manager.update_digest(user_id)
                                            # else:
                                            # text = await digest_manager.get_digest(user_id)
                                            return {
                                                "user_id": user_id,
                                                "digest": "",
                                                "cached": True,
                                            }

                                            @router.post(
                                                "/consolidate/{user_id}",
                                                response_model=ConsolidationResponse,
                                                responses={500: {"model": ErrorResponse}},
                                                summary="触发记忆巩固",
                                            )
                                            async def consolidate_memory(
                                                user_id: str,
                                            ) -> ConsolidationResponse:
                                                """
                                                手动触发用户的记忆巩固流程（五阶段）。
                                                """
                                                # report = await consolidation_engine.run_consolidation(user_id)
                                                return ConsolidationResponse(
                                                    user_id=user_id, success=True, total_items=0
                                                )

                                                @router.delete(
                                                    "/{memory_id}",
                                                    responses={
                                                        403: {"model": ErrorResponse},
                                                        404: {"model": ErrorResponse},
                                                    },
                                                    summary="删除记忆",
                                                )
                                                async def delete_memory(
                                                    memory_id: str,
                                                    user_id: str = Query(
                                                        ..., description="用户 ID（权限校验）"
                                                    ),
                                                ) -> dict:
                                                    """
                                                    删除单条记忆（需权限校验）。
                                                    """
                                                    # success = await governor.delete_memory(memory_id, user_id)
                                                    return {"memory_id": memory_id, "deleted": True}

                                                    @router.get(
                                                        "/skills/{user_id}",
                                                        response_model=SkillListResponse,
                                                        summary="获取技能池",
                                                    )
                                                    async def list_skills(
                                                        user_id: str,
                                                    ) -> SkillListResponse:
                                                        """
                                                        获取用户的技能池列表。
                                                        """
                                                        return SkillListResponse(
                                                            user_id=user_id, skills=[], total=0
                                                        )

                                                        @router.get(
                                                            "/health",
                                                            response_model=HealthResponse,
                                                            summary="健康检查",
                                                        )
                                                        async def health_check() -> HealthResponse:
                                                            """
                                                            系统健康检查 — 检测 Neo4j/pgvector/Redis 连通性。
                                                            """
                                                            import time

                                                            # neo4j_ok = await _check_neo4j()
                                                            # pgvector_ok = await _check_pgvector()
                                                            # redis_ok = await _check_redis()
                                                            return HealthResponse(
                                                                status="healthy",
                                                                neo4j=True,
                                                                pgvector=True,
                                                                redis=True,
                                                                uptime_seconds=0.0,
                                                            )
                                                            # ── 应用注册 ──────────────────────────────────────────────
                                                            #
                                                            from fastapi import FastAPI

                                                            # app = FastAPI(title="Memory System API", version="1.0.0")
                                                            # app.include_router(router)
```

---

##
11. 实现路线图

### 11.1 P0-P5 分阶段交付表
| 阶段 | 名称 | 周期 | 核心交付物 | 验收标准 | |------|------|------|-----------|----------| | P0 | MVP 基础框架 | 2 周 | MemoryWriter / MemoryRetriever（仅 pgvector） / FastAPI 骨架 | 能写入记忆并通过向量检索返回，E2E 延迟 < 200ms |
| P1 | 图存储集成 | 2 周 | Neo4j schema / TKG 写入 / BM25 粗召回 / HebbianDecay | 记忆能写入 Neo4j，BM25 召回准确率 > 60% |
| P2 | 双路检索 | 2 周 | SpreadActivation / FunnelCompressor / DigestManager / PolicyRouter | System 1 P99 < 10ms；System 2 P99 < 500ms |
| P3 | 巩固引擎 | 3 周 | ConsolidationEngine / ConflictDetector / ColdStorageManager | 五阶段流程可跑通，夜间巩固不丢失数据 |
| P4 | 技能与治理 | 2 周 | SkillEmergence / MemoryGovernor / GDPR | 技能从 5+ 次重复行为中自动提取，GDPR 删除在 30s 内完成 |
| P5 | 生产化 | 3 周 | Prometheus metrics / Grafana / 压测 / 灰度 | P99 写入 < 100ms，P99 检索 < 800ms，QPS > 100 |

**里程碑依赖:**

```
P0 ──→ P1 ──→ P2 ──→ P3 ──→ P4
                │
        │
                └───────────┼──→ P5
                            │
```

---

##
12. 监控与度量

### 12.1 Prometheus Metrics 定义
| 指标名 | 类型 | 标签 | 说明 | |--------|------|------|------| | `memory_write_total` | Counter | user_id, memory_type, status | 写入请求总数 |
| `memory_write_latency_seconds` | Histogram | user_id, memory_type | 写入延迟分布 |
| `memory_retrieve_total` | Counter | user_id, path, intent, status | 检索请求总数（path=system1/system2） |
| `memory_retrieve_latency_seconds` | Histogram | user_id, path, intent | 检索延迟分布 |
| `memory_retrieve_results_count` | Histogram | user_id, source | 每次检索返回结果数 |
| `memory_consolidation_duration_seconds` | Histogram | user_id, phase | 巩固各阶段耗时 |
| `memory_consolidation_items_processed` | Counter | user_id, phase | 巩固处理的条目数 |
| `memory_consolidation_errors_total` | Counter | user_id, phase | 巩固错误数 |
| `memory_storage_tier_nodes` | Gauge | user_id, tier | 各层级存储节点数 |
| `memory_skill_count` | Gauge | user_id, status | 各状态技能数量 |
| `memory_digest_cache_hit_ratio` | Gauge | user_id | Digest 缓存命中率 |
| `memory_conflict_detected_total` | Counter | user_id, type | 冲突检测数（type=contradiction/update/complement） |
| `memory_spread_activation_depth` | Histogram | user_id | 图扩展实际跳数分布 |
| `memory_llm_tokens_total` | Counter | model, operation | LLM token 消耗 |
| `memory_pii_filtered_total` | Counter | pii_type | PII 过滤次数 |

### 12.2 Grafana Dashboard 建议

**面板布局（4 行 x 3 列）:**
| 行 | 面板 1 | 面板 2 | 面板 3 | |----|--------|--------|--------| | R1 | 写入 QPS (rate) | 写入 P50/P95/P99 (latency) | 写入错误率 |
| R2 | 检索 QPS by path | 检索 P50/P95/P99 by path | System 1 缓存命中率 |
| R3 | 存储层级分布 (pie) | 巩固耗时 (bar) | 冲突检测数 (stacked) |
| R4 | 技能数量 by status | LLM token 消耗 | PII 过滤计数 |

### 12.3 四层度量栈 Python 采集代码

```python
from __future__ import annotations
import time
import logging
from dataclasses import dataclass
from typing import Optional
from prometheus_client import (
    Counter,
    Histogram,
    Gauge,
    CollectorRegistry,
    generate_latest,
    CONTENT_TYPE_LATEST,
)
from fastapi import Response
from fastapi.routing import APIRouter

logger = logging.getLogger(__name__)
# ── Registry ──────────────────────────────────────────────
_registry = CollectorRegistry()
# ── Layer 1: RED Metrics (请求级) ───────────────────────
WRITE_TOTAL = Counter(
    "memory_write_total",
    "Total memory write requests",
    labels=["user_id", "memory_type", "status"],
    registry=_registry,
)
WRITE_LATENCY = Histogram(
    "memory_write_latency_seconds",
    "Memory write latency",
    ["user_id", "memory_type"],
    buckets=[0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0],
    registry=_registry,
)
RETRIEVE_TOTAL = Counter(
    "memory_retrieve_total",
    "Total memory retrieve requests",
    labels=["user_id", "path", "intent", "status"],
    registry=_registry,
)
RETRIEVE_LATENCY = Histogram(
    "memory_retrieve_latency_seconds",
    "Memory retrieve latency",
    ["user_id", "path", "intent"],
    buckets=[0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.0],
    registry=_registry,
)
RETRIEVE_RESULTS = Histogram(
    "memory_retrieve_results_count",
    "Number of results per retrieval",
    ["user_id", "source"],
    buckets=[1, 5, 10, 20, 50, 100],
    registry=_registry,
)
# ── Layer 2: USE Metrics (资源级) ───────────────────────
STORAGE_TIER_GAUGE = Gauge(
    "memory_storage_tier_nodes",
    "Number of memory nodes per storage tier",
    labels=["user_id", "tier"],
    registry=_registry,
)
SKILL_COUNT_GAUGE = Gauge(
    "memory_skill_count",
    "Number of skills per status",
    labels=["user_id", "status"],
    registry=_registry,
)
DIGEST_CACHE_HIT = Gauge(
    "memory_digest_cache_hit_ratio", "Digest cache hit ratio", ["user_id"], registry=_registry
)
# ── Layer 3: 系统/依赖 Metrics ──────────────────────────
CONSOLIDATION_DURATION = Histogram(
    "memory_consolidation_duration_seconds",
    "Consolidation phase duration",
    ["user_id", "phase"],
    buckets=[1, 5, 10, 30, 60, 120, 300],
    registry=_registry,
)
CONSOLIDATION_ERRORS = Counter(
    "memory_consolidation_errors_total",
    "Consolidation errors",
    labels=["user_id", "phase"],
    registry=_registry,
)
LLM_TOKENS = Counter(
    "memory_llm_tokens_total",
    "LLM token consumption",
    labels=["model", "operation"],
    registry=_registry,
)
# ── Layer 4: 业务 Metrics ───────────────────────────────
CONFLICT_DETECTED = Counter(
    "memory_conflict_detected_total",
    "Conflicts detected during consolidation",
    labels=["user_id", "type"],
    registry=_registry,
)
PII_FILTERED = Counter(
    "memory_pii_filtered_total", "PII fields filtered", labels=["pii_type"], registry=_registry
)
SPREAD_DEPTH = Histogram(
    "memory_spread_activation_depth",
    "Graph spread activation depth",
    ["user_id"],
    buckets=[1, 2, 3, 4, 5, 6],
    registry=_registry,
)
# ── Metrics API Endpoint ─────────────────────────────────
metrics_router = APIRouter(prefix="/metrics", tags=["metrics"])


@metrics_router.get("/", summary="Prometheus 指标")
async def prometheus_metrics() -> Response:
    """
    暴露 Prometheus 格式的 metrics 端点。"""
    return Response(content=generate_latest(_registry), media_type=CONTENT_TYPE_LATEST)

    # ── 采集辅助类 ──────────────────────────────────────────
    class MetricsCollector:
        """
        度量采集器 — 封装各层指标的便捷记录方法。"""

        @staticmethod
        def record_write(
            user_id: str,
            memory_type: str,
            status: str,
            latency_seconds: float,
        ) -> None:
            """
            记录写入度量。"""
            WRITE_TOTAL.labels(user_id=user_id, memory_type=memory_type, status=status).inc()
            WRITE_LATENCY.labels(user_id=user_id, memory_type=memory_type).observe(latency_seconds)

            @staticmethod
            def record_retrieve(
                user_id: str,
                path: str,
                intent: str,
                status: str,
                latency_seconds: float,
                result_count: int,
            ) -> None:
                """
                记录检索度量。"""
                RETRIEVE_TOTAL.labels(
                    user_id=user_id,
                    path=path,
                    intent=intent,
                    status=status,
                ).inc()
                RETRIEVE_LATENCY.labels(
                    user_id=user_id,
                    path=path,
                    intent=intent,
                ).observe(latency_seconds)
                RETRIEVE_RESULTS.labels(
                    user_id=user_id,
                    source="hybrid",
                ).observe(result_count)

                @staticmethod
                def update_storage_tier(user_id: str, tier: str, count: int) -> None:
                    """
                    更新存储层级指标。"""
                    STORAGE_TIER_GAUGE.labels(user_id=user_id, tier=tier).set(count)

                    @staticmethod
                    def record_digest_cache(user_id: str, hit: bool) -> None:
                        """
                        记录 Digest 缓存命中。"""
                        # 使用简单的滑动窗口近似
                        key = f"digest_cache_{user_id}"
                        # 在生产中使用 prometheus-client 的 Counter + rate() 实现
                        DIGEST_CACHE_HIT.labels(user_id=user_id).set(1.0 if hit else 0.0)

                        @staticmethod
                        def record_consolidation_phase(
                            user_id: str,
                            phase: str,
                            duration_seconds: float,
                            error: bool = False,
                        ) -> None:
                            """
                            记录巩固阶段度量。"""
                            CONSOLIDATION_DURATION.labels(user_id=user_id, phase=phase).observe(
                                duration_seconds
                            )
                            if error:
                                CONSOLIDATION_ERRORS.labels(user_id=user_id, phase=phase).inc()

                                @staticmethod
                                def record_llm_tokens(
                                    model: str, operation: str, tokens: int
                                ) -> None:
                                    """
                                    记录 LLM token 消耗。"""
                                    LLM_TOKENS.labels(model=model, operation=operation).inc(tokens)

                                    @staticmethod
                                    def record_conflict(user_id: str, conflict_type: str) -> None:
                                        """
                                        记录冲突检测。"""
                                        CONFLICT_DETECTED.labels(
                                            user_id=user_id, type=conflict_type
                                        ).inc()

                                        @staticmethod
                                        def record_pii(pii_type: str) -> None:
                                            """
                                            记录 PII 过滤。"""
                                            PII_FILTERED.labels(pii_type=pii_type).inc()

                                            @staticmethod
                                            def record_spread_depth(
                                                user_id: str, depth: int
                                            ) -> None:
                                                """
                                                记录图扩展深度。"""
                                                SPREAD_DEPTH.labels(user_id=user_id).observe(
                                                    float(depth)
                                                )
                                                # ── 上下文管理器（用于计时）────────────────────────────
                                                from contextlib import asynccontextmanager

                                                @asynccontextmanager
                                                async def observe_latency(
                                                    metric: Histogram,
                                                    labels: dict,
                                                    on_complete: Optional[callable] = None,
                                                ):
                                                    """
                                                    异步计时上下文管理器 — 自动记录延迟到 Prometheus。"""
                                                    start = time.monotonic()
                                                    try:
                                                        yield
                                                    finally:
                                                        elapsed = time.monotonic() - start
                                                        metric.labels(**labels).observe(elapsed)
                                                        if on_complete:
                                                            on_complete(elapsed)
```

---

## 附录

### A. 配置项速查表
| 配置项 | 类型 | 默认值 | 所属组件 | 说明 | |--------|------|--------|----------|------| | `lambda_decay` | float | 0.05 | HebbianDecay | 时间衰减系数 |
| `alpha_cooccurrence` | float | 0.2 | HebbianDecay | 共现增强系数 |
| `beta_interference` | float | 0.15 | HebbianDecay | 干扰惩罚系数 |
| `cooccurrence_window_hours` | int | 168 | HebbianDecay | 共现统计窗口（7天） |
| `hot_threshold` | float | 0.7 | HebbianDecay | 热记忆权重阈值 |
| `warm_threshold` | float | 0.3 | HebbianDecay | 温记忆权重阈值 |
| `w_cosine` | float | 0.4 | MemoryRetriever | 向量相似度权重 |
| `w_bm25` | float | 0.3 | MemoryRetriever | BM25 权重 |
| `w_graph` | float | 0.3 | MemoryRetriever | 图扩展权重 |
| `time_decay_half_life_hours` | float | 168.0 | MemoryRetriever | 时间衰减半衰期（7天） |
| `early_stop_top_k` | int | 10 | MemoryRetriever | Early Stop 最大数 |
| `early_stop_score_gap` | float | 0.15 | MemoryRetriever | Early Stop 分差阈值 |
| `pgvector_table` | str | "user_memory" | MemoryRetriever | pgvector 向量表名 |
| `embedding_dim` | int | 1536 | MemoryRetriever | 嵌入维度 |
| `max_hops` | int | 3 | SpreadActivation | 最大跳数 |
| `activation_decay` | float | 0.5 | SpreadActivation | 每跳衰减系数 |
| `min_activation` | float | 0.01 | SpreadActivation | 最低激活阈值 |
| `dedup_similarity_threshold` | float | 0.85 | FunnelCompressor | 去重相似度阈值 |
| `evidence_max_items` | int | 30 | FunnelCompressor | 最大证据条目数 |
| `early_stop_confidence` | float | 0.9 | FunnelCompressor | Early Stop 置信度 |
| `llm_model` | str | "gpt-4o-mini" | FunnelCompressor | LLM 模型 |
| `budget_tokens` | int | 2000 | FunnelCompressor | 输出 token 预算 |
| `cache_ttl_seconds` | int | 300 | DigestManager | Digest 缓存 TTL |
| `max_tokens` | int | 2000 | DigestManager | Digest 最大 token 数 |
| `episode_age_days` | int | 7 | ConsolidationEngine | Episode 转语义最低年龄 |
| `semantic_min_examples` | int | 3 | ConsolidationEngine | 提取语义的最少 Episode |
| `conflict_check_batch_size` | int | 50 | ConflictDetector | 冲突检测批量大小 |
| `conflict_similarity_threshold` | float | 0.85 | ConflictDetector | 冲突检测相似度阈值 |
| `min_pattern_frequency` | int | 3 | SkillEmergence | 最低模式频率 |
| `pattern_window_days` | int | 30 | SkillEmergence | 模式检测窗口 |
| `maturity_active_threshold` | float | 0.7 | SkillEmergence | 技能活跃成熟度阈值 |
| `stale_days` | int | 90 | SkillEmergence | 技能过时天数 |
| `repulsion_threshold` | float | 0.95 | RepresentationRepulsion | 排斥相似度阈值 |
| `repulsion_gamma` | float | 0.1 | RepresentationRepulsion | 排斥力度 |

### B. Cypher 查询速查表
| 查询名 | 用途 | 关键 WHERE 条件 | |--------|------|-----------------| | BM25 粗召回 | 全文搜索 | `db.index.fulltext.queryNodes("memoryFullText", $query)` |
| 向量召回辅助 | 按 ID 获取节点 | `MATCH (n:MemoryNode {id: $id})` |
| 用户记忆列表 | 获取用户所有记忆 | `MATCH (n)-[:BELONGS_TO]->(u:User {id: $uid})` |
| 高频模式扫描 | 技能涌现候选 | `e.created_at >= datetime() - duration({days: $w})` + `size(collect) >= $freq` |
| 存储层级更新 | 权重扫描后批量更新 | `UNWIND $updates AS u` + `SET r.weight, r.storage_tier` |
| 冲突候选对 | SemanticMemory 对 | `a.id < b.id` + 热层级过滤 |
| 合并去重 | 冗余合并 | `SET s.status = 'merged'` + `MERGE (s)-[:MERGED_INTO]->(p)` |
| 技能查询 | 获取用户技能池 | `MATCH (s:Skill)-[:BELONGS_TO]->(u:User {id: $uid})` |
| Digest 数据 | 画像/技能/事件/任务 | 分别查询 User, Skill, Episode, Task 节点 |
| GDPR 级联删除 | 完全清除用户数据 | `DETACH DELETE u, n` |
| 单条删除 + 权限校验 | 安全删除 | 先查 owner，再 `DETACH DELETE` |
| Episode→Semantic 聚类 | 巩固阶段1 | `duration.between(date(e.created_at), date()).days >= $min_age` |
| 层级分布统计 | 监控 | `RETURN n.storage_tier AS tier, count(n)` |

### C. LLM Prompt 模板速查表
| Prompt 名称 | 用途 | 输入 | 输出格式 | |-------------|------|------|----------| | `SKILL_EXTRACTION_PROMPT` | 从重复行为提取技能模板 | 行为序列文本 | JSON: name, description, template, parameters |
| `SKILL_UPDATE_PROMPT` | 增量更新已有技能 | 当前技能 + 新证据 | JSON: action(keep/update/deprecate), name, description, template |
| `CONFLICT_DETECTION_PROMPT` | 记忆冲突判定 | 记忆 A + 记忆 B | JSON: type(CONTRADICTION/UPDATE/COMPLEMENT), confidence, explanation |
| `compression_prompt_template` | 漏斗 LLM 压缩 | 证据列表 + token 预算 | 结构化摘要文本 |
| 意图分类 prompt | PolicyRouter LLM 分类 | 查询文本 | JSON: intent, confidence, entities, time_reference |
| 语义提取 prompt | 巩固阶段1提取共性 | 相似 Episode 簇 | 一句话语义概括 |
| Digest 渲染 | 画像+技能+事件+任务 | 结构化数据 | 模板渲染文本 |

### D. 参考文献 
1. Atkinson, R. C., & Shiffrin, R. M. (1968). Human memory: A proposed system and its control processes. *Psychology of Learning and Motivation*, 2, 89-195.
2. Hebb, D. O. (1949). *The Organization of Behavior*. Wiley.
3. Kahneman, D. (2011). *Thinking, Fast and Slow*. Farrar, Straus and Giroux.
4. Collins, A. M., & Loftus, E. F. (1975). A spreading-activation theory of semantic processing. *Psychological Review*, 82(6), 407-428.
5. McClelland, J. L., McNaughton, B. L., & O'Reilly, R. C. (1995). Why there are complementary learning systems in the hippocampus and neocortex. *Psychological Review*, 102(3), 419-457.
6. Ebbinghaus, H. (1885/1964). *Memory: A Contribution to Experimental Psychology*. Dover.
7. Mazur, J. E. (2006). *Learning and Behavior* (6th ed.). Pearson.

---

## 旧系统替代说明

### 组件替代矩阵

| 旧组件 | 新组件 | 替代关系 | 说明 |
|---|---|---|---|
| MemoryCandidateExtractor | SalienceScorer | 完全替代 | LLM 二元判断 → 五因子量化评分 |
| MemoryConfidenceTracker | SalienceScorer（评分阈值）+ ConsolidationEngine（冲突整理） | 完全替代 | 计数累计 → 评分阈值；无冲突检测 → 五阶段巩固 |
| UserMemoryConfirmationService | 已删除（不需要） | 完全删除 | 自动写入 + 事后图管理替代逐条确认 |
| MemoryCandidate 表 (PG) | 已删除 | 完全删除 | 不再需要候选累计表 |
| UserMemoryService.recall_relevant_memories | MemoryRetriever | 完全替代 | pgvector 单路 → TKG+pgvector 混合 |
| token_buffer_memory.get_relevant_facts | MemoryDigest | 部分替代 | 只替代 relevant_facts，recent_messages 和 distant_summary 保留 |
| MemoryVectorService (旧 pgvector) | PostgreSQL pgvector 向量存储 | 完全替代 | 记忆向量迁移到 user_memory.embedding 列 |
| MemoryConfirmationCard.vue | 图可视化界面 | 完全替代 | 逐条确认卡片 → 全局图管理 |
| memory_candidate_handler.py | 已删除 | 完全删除 | 候选确认 API 不再需要 |
| user_memory_handler.py | 新 API handler | 完全替代 | CRUD API 重新设计 |

### 不被替代的旧组件

以下旧组件**保留不动**，不属于记忆系统替换范围：
- `token_buffer_memory` 的 `recent_messages` 和 `distant_summary` 逻辑（对话管理职责）
- `UserMemory` PG 表（作为关系数据持久层，新系统也读写）
- `knowledge_base_service.py` 及相关 RAG 管线（知识库系统，非记忆系统）
- `scoped_knowledge_service.py` 中的知识库管理方法（非记忆相关方法）

---

> 文档结束。以上为记忆系统工程架构文档的后半部分（第 5-12 章 + 附录），涵盖存储层、读取路径、巩固引擎、技能池、Policy 层、API 接口、路线图、监控及附录的全部内容。
