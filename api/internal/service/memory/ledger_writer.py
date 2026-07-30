"""权威账本写入器（LedgerWriter）。

根据显著性评分决定的写入路径（FULL / SUMMARY / SKETCH），将记忆事件以不同
粒度写入 Neo4j 时序知识图谱（TKG）与 PostgreSQL pgvector 向量库。

写入路径:
    - FULL:    完整路径。Episode 节点（原文，hot 层）+ 全量实体/关系 + 向量
    - SUMMARY: 摘要路径。Episode 节点（摘要，hot 层）+ 前 5 实体/关系 + 向量（warm 标记）
    - SKETCH:  草稿路径。仅更新实体访问计数与共现计数，不写 Episode 与向量

降级策略:
    - Neo4j 不可用：跳过图写入，仅返回降级标记，向量写入仍可继续
    - pgvector 不可用：跳过向量写入，图写入不受影响

设计参考:
    docs/prd/memory-system/01-data-models-and-write-path.md
    docs/prd/memory-system/02-storage-and-retrieval.md
"""

from __future__ import annotations

import logging
import re
from datetime import datetime
from uuid import UUID, uuid4
from typing import Optional

from dataclasses import dataclass
from injector import inject

from flask import current_app

from pkg.sqlalchemy import SQLAlchemy
from internal.model.knowledge import UserMemory
from internal.model.memory_models import ExplicitDetectionResult, MemoryEvent
from internal.service.memory.metrics import MetricsCollector, observe_latency


logger = logging.getLogger(__name__)


# 关系类型白名单：只允许字母数字下划线，防 Cypher 注入
_RELATION_TYPE_RE = re.compile(r"^[A-Za-z0-9_]+$")


@inject
@dataclass
class LedgerWriter:
    """权威账本写入总控。

    依赖注入:
        db: SQLAlchemy 实例（同步 session），用于 user_memory 表（pgvector）写入
        Neo4j 驱动通过 ``current_app.extensions['neo4j']`` 或 ``get_driver()`` 获取，
        不在构造函数注入，便于在驱动不可用时优雅降级。
    """

    db: SQLAlchemy

    # =========================================================
    # 三条写入路径
    # =========================================================

    def write_full_path(
        self,
        event: MemoryEvent,
        entities: list[dict],
        relations: list[dict],
        embedding: list[float],
        explicit_detection: Optional[ExplicitDetectionResult] = None,
    ) -> dict:
        """完整写入路径：全量存储原文、实体、关系与向量。

        Args:
            event: 原始记忆事件
            entities: 实体列表，每项 ``{"name", "type", "summary"}``
            relations: 关系列表，每项 ``{"subject", "relation", "object"}``
            embedding: 事件内容的嵌入向量（1536 维）
            explicit_detection: 显式陈述检测结果（可选），携带 explicit_* 属性
                与 subject 实体种子。非空时：
                - 将 explicit_category/polarity/subject 写入 Episode 节点属性
                - 将 subject 作为实体种子注入 entities 列表头部
                - 根据 predicate/object 补充三元组关系

        Returns:
            ``{episode_node_id, entity_count, edge_count, vector_id}``；
            若 Neo4j 不可用，``episode_node_id`` 为 None 且 ``error="neo4j_unavailable"``。
        """
        with observe_latency(lambda s: MetricsCollector.record_write(s)):
            return self._write_full_path_impl(
                event, entities, relations, embedding, explicit_detection
            )

    def _write_full_path_impl(
        self,
        event: MemoryEvent,
        entities: list[dict],
        relations: list[dict],
        embedding: list[float],
        explicit_detection: Optional[ExplicitDetectionResult] = None,
    ) -> dict:
        """write_full_path 的原始实现。"""
        now = datetime.utcnow()
        driver = self._get_driver()

        # 显式陈述实体种子注入：将 subject 作为实体种子插入 entities 头部
        merged_entities = list(entities or [])
        if explicit_detection and explicit_detection.is_explicit and explicit_detection.subject:
            seed_entity = {
                "name": explicit_detection.subject,
                "type": explicit_detection.category.value if explicit_detection.category else "explicit_subject",
                "summary": f"显式陈述主体：{explicit_detection.predicate or ''}",
            }
            # 避免重复
            existing_names = {e.get("name") for e in merged_entities if e.get("name")}
            if seed_entity["name"] not in existing_names:
                merged_entities.insert(0, seed_entity)

        # 显式陈述三元组关系补充：subject -> predicate -> object
        merged_relations = list(relations or [])
        if (
            explicit_detection
            and explicit_detection.is_explicit
            and explicit_detection.subject
            and explicit_detection.predicate
        ):
            # 若有 object，构建完整三元组；否则 subject -> predicate -> "user"
            obj_name = explicit_detection.object or "user"
            seed_relation = {
                "subject": explicit_detection.subject,
                "relation": explicit_detection.predicate.upper().replace(" ", "_"),
                "object": obj_name,
            }
            merged_relations.append(seed_relation)

        episode_node_id: Optional[str] = None
        entity_count = 0
        edge_count = 0

        if driver is None:
            logger.warning(
                "write_full_path: Neo4j 不可用，降级跳过图写入 event_id=%s",
                event.event_id,
            )
        else:
            try:
                # 1. 创建 Episode 节点（完整原文，hot 层，携带 explicit_* 属性）
                episode_node_id = self._create_episode_node(
                    driver, event, now, explicit_detection=explicit_detection
                )

                # 2. 合并实体并建立 Episode -> Entity 的 CONTAINS 边
                entity_id_map: dict[str, str] = {}
                for ent in merged_entities:
                    try:
                        eid = self._merge_entity_node(driver, ent, now, event.user_id)
                    except Exception:
                        logger.warning(
                            "write_full_path: 合并实体失败 name=%s",
                            ent.get("name"),
                            exc_info=True,
                        )
                        continue
                    name = ent.get("name", "")
                    if name and eid:
                        entity_id_map[name] = eid
                        entity_count += 1
                        try:
                            self._create_edge(
                                driver,
                                source_id=episode_node_id,
                                target_id=eid,
                                relation_type="CONTAINS",
                                t_valid_at=now,
                            )
                            edge_count += 1
                        except Exception:
                            logger.warning(
                                "write_full_path: CONTAINS 边创建失败 episode=%s entity=%s",
                                episode_node_id,
                                eid,
                                exc_info=True,
                            )

                # 3. 处理三元组关系：subject -> object
                for rel in merged_relations:
                    subj_name = rel.get("subject")
                    obj_name = rel.get("object")
                    rel_type = rel.get("relation")
                    if not subj_name or not obj_name or not rel_type:
                        continue

                    subj_id = entity_id_map.get(subj_name)
                    obj_id = entity_id_map.get(obj_name)
                    # 若实体未在 entities 列表中，则补建
                    if not subj_id:
                        try:
                            subj_id = self._merge_entity_node(
                                driver,
                                {"name": subj_name, "type": "unknown", "summary": ""},
                                now,
                                event.user_id,
                            )
                            entity_id_map[subj_name] = subj_id
                            entity_count += 1
                        except Exception:
                            logger.warning(
                                "write_full_path: 补建主体实体失败 name=%s",
                                subj_name,
                                exc_info=True,
                            )
                            continue
                    if not obj_id:
                        try:
                            obj_id = self._merge_entity_node(
                                driver,
                                {"name": obj_name, "type": "unknown", "summary": ""},
                                now,
                                event.user_id,
                            )
                            entity_id_map[obj_name] = obj_id
                            entity_count += 1
                        except Exception:
                            logger.warning(
                                "write_full_path: 补建客体实体失败 name=%s",
                                obj_name,
                                exc_info=True,
                            )
                            continue

                    try:
                        self._create_edge(
                            driver,
                            source_id=subj_id,
                            target_id=obj_id,
                            relation_type=rel_type,
                            t_valid_at=now,
                        )
                        edge_count += 1
                    except Exception:
                        logger.warning(
                            "write_full_path: 关系边创建失败 %s-%s->%s",
                            subj_name,
                            rel_type,
                            obj_name,
                            exc_info=True,
                        )
            except Exception:
                logger.exception(
                    "write_full_path: 图写入整体异常 event_id=%s", event.event_id
                )
                episode_node_id = episode_node_id or None

        # 4. 写入 pgvector 向量（携带 explicit_* 属性）
        vector_payload = {
            "content": event.content,
            "event_type": "episode",
            "tier": "hot",
            "timestamp": now.isoformat(),
            "user_id": event.user_id,
            "node_id": episode_node_id,
            "session_id": event.session_id,
            "source": event.source.value if event.source else None,
            "event_id": str(event.event_id),
        }
        if explicit_detection and explicit_detection.is_explicit:
            vector_payload["explicit_category"] = (
                explicit_detection.category.value if explicit_detection.category else None
            )
            vector_payload["explicit_polarity"] = explicit_detection.polarity.value
            vector_payload["explicit_subject"] = explicit_detection.subject
        vector_id = self._upsert_vector(
            point_id=episode_node_id or str(uuid4()),
            vector=embedding,
            payload=vector_payload,
        )

        result = {
            "episode_node_id": episode_node_id,
            "entity_count": entity_count,
            "edge_count": edge_count,
            "vector_id": vector_id,
        }
        if driver is None:
            result["error"] = "neo4j_unavailable"
        return result

    def write_summary_path(
        self,
        event: MemoryEvent,
        summary: str,
        entities: list[dict],
        relations: list[dict],
        embedding: list[float],
    ) -> dict:
        """摘要写入路径：仅写入摘要内容与前 5 个实体/关系。

        Args:
            event: 原始记忆事件
            summary: LLM 生成的摘要文本
            entities: 实体列表（仅处理前 5 个）
            relations: 关系列表（仅处理前 5 个）
            embedding: 摘要内容的嵌入向量

        Returns:
            写入结果摘要字典
        """
        with observe_latency(lambda s: MetricsCollector.record_write(s)):
            return self._write_summary_path_impl(
                event, summary, entities, relations, embedding
            )

    def _write_summary_path_impl(
        self,
        event: MemoryEvent,
        summary: str,
        entities: list[dict],
        relations: list[dict],
        embedding: list[float],
    ) -> dict:
        """write_summary_path 的原始实现。"""
        now = datetime.utcnow()
        driver = self._get_driver()

        episode_node_id: Optional[str] = None
        entity_count = 0
        edge_count = 0

        if driver is None:
            logger.warning(
                "write_summary_path: Neo4j 不可用，降级跳过图写入 event_id=%s",
                event.event_id,
            )
        else:
            try:
                # 1. 创建 Episode 节点（摘要内容，hot 层）
                episode_node_id = self._create_episode_node(
                    driver, event, now, content_override=summary
                )

                # 2. 仅处理前 5 个实体与关系
                top_entities = (entities or [])[:5]
                top_relations = (relations or [])[:5]

                entity_id_map: dict[str, str] = {}
                for ent in top_entities:
                    try:
                        eid = self._merge_entity_node(driver, ent, now, event.user_id)
                    except Exception:
                        logger.warning(
                            "write_summary_path: 合并实体失败 name=%s",
                            ent.get("name"),
                            exc_info=True,
                        )
                        continue
                    name = ent.get("name", "")
                    if name and eid:
                        entity_id_map[name] = eid
                        entity_count += 1
                        try:
                            self._create_edge(
                                driver,
                                source_id=episode_node_id,
                                target_id=eid,
                                relation_type="CONTAINS",
                                t_valid_at=now,
                            )
                            edge_count += 1
                        except Exception:
                            logger.warning(
                                "write_summary_path: CONTAINS 边创建失败 episode=%s entity=%s",
                                episode_node_id,
                                eid,
                                exc_info=True,
                            )

                for rel in top_relations:
                    subj_name = rel.get("subject")
                    obj_name = rel.get("object")
                    rel_type = rel.get("relation")
                    if not subj_name or not obj_name or not rel_type:
                        continue

                    subj_id = entity_id_map.get(subj_name)
                    obj_id = entity_id_map.get(obj_name)
                    if not subj_id or not obj_id:
                        # 摘要路径不补建缺失实体，保持轻量
                        continue

                    try:
                        self._create_edge(
                            driver,
                            source_id=subj_id,
                            target_id=obj_id,
                            relation_type=rel_type,
                            t_valid_at=now,
                        )
                        edge_count += 1
                    except Exception:
                        logger.warning(
                            "write_summary_path: 关系边创建失败 %s-%s->%s",
                            subj_name,
                            rel_type,
                            obj_name,
                            exc_info=True,
                        )
            except Exception:
                logger.exception(
                    "write_summary_path: 图写入整体异常 event_id=%s", event.event_id
                )

        # 3. 写入 pgvector 向量（warm 标记）
        vector_id = self._upsert_vector(
            point_id=episode_node_id or str(uuid4()),
            vector=embedding,
            payload={
                "content": summary,
                "event_type": "episode_summary",
                "tier": "warm",
                "timestamp": now.isoformat(),
                "user_id": event.user_id,
                "node_id": episode_node_id,
                "session_id": event.session_id,
                "source": event.source.value if event.source else None,
                "event_id": str(event.event_id),
            },
        )

        result = {
            "episode_node_id": episode_node_id,
            "entity_count": entity_count,
            "edge_count": edge_count,
            "vector_id": vector_id,
        }
        if driver is None:
            result["error"] = "neo4j_unavailable"
        return result

    def write_stats_path(
        self,
        event: MemoryEvent,
        entities: list[dict],
    ) -> dict:
        """草稿写入路径：仅更新实体访问计数与共现统计，不写 Episode 与向量。

        Args:
            event: 原始记忆事件（仅取 user_id）
            entities: 实体列表

        Returns:
            ``{updated_entities: N, vector_id: None}``
        """
        with observe_latency(lambda s: MetricsCollector.record_write(s)):
            return self._write_stats_path_impl(event, entities)

    def _write_stats_path_impl(
        self,
        event: MemoryEvent,
        entities: list[dict],
    ) -> dict:
        """write_stats_path 的原始实现。"""
        now = datetime.utcnow()
        driver = self._get_driver()

        updated_entities = 0

        if driver is None:
            logger.warning(
                "write_stats_path: Neo4j 不可用，降级跳过 stats 写入 event_id=%s",
                event.event_id,
            )
            return {"updated_entities": 0, "vector_id": None, "error": "neo4j_unavailable"}

        entity_names: list[str] = []
        for ent in entities or []:
            name = ent.get("name")
            if not name:
                continue
            try:
                self._increment_entity_access(driver, name, now, event.user_id)
                entity_names.append(name)
                updated_entities += 1
            except Exception:
                logger.warning(
                    "write_stats_path: 更新实体访问计数失败 name=%s", name, exc_info=True
                )

        # 两两更新共现计数
        for i in range(len(entity_names)):
            for j in range(i + 1, len(entity_names)):
                try:
                    self._increment_cooccurrence(
                        driver,
                        entity_names[i],
                        entity_names[j],
                        now,
                        event.user_id,
                    )
                except Exception:
                    logger.warning(
                        "write_stats_path: 共现计数更新失败 %s / %s",
                        entity_names[i],
                        entity_names[j],
                        exc_info=True,
                    )

        return {"updated_entities": updated_entities, "vector_id": None}

    # =========================================================
    # Neo4j 内部方法
    # =========================================================

    def _create_episode_node(
        self,
        driver,
        event: MemoryEvent,
        now: datetime,
        content_override: Optional[str] = None,
        explicit_detection: Optional[ExplicitDetectionResult] = None,
    ) -> str:
        """创建 Episode 节点并返回其 node_id。

        Args:
            driver: Neo4j 驱动
            event: 记忆事件
            now: 当前时间戳
            content_override: 非空时用其替代 ``event.content``（摘要路径用）
            explicit_detection: 显式陈述检测结果（可选），非空且 is_explicit 时
                将 explicit_category/polarity/subject 写入节点属性

        Returns:
            新建 Episode 节点的 node_id（uuid4 字符串）
        """
        node_id = str(uuid4())
        content = content_override if content_override is not None else event.content
        # summary 取 content 前 200 字符
        summary = content[:200] if content else ""

        # 显式陈述属性
        explicit_category = None
        explicit_polarity = None
        explicit_subject = None
        if explicit_detection and explicit_detection.is_explicit:
            explicit_category = (
                explicit_detection.category.value if explicit_detection.category else None
            )
            explicit_polarity = explicit_detection.polarity.value
            explicit_subject = explicit_detection.subject

        cypher = """
        CREATE (e:Episode:MemoryNode {
            node_id: $node_id,
            id: $node_id,
            content: $content,
            summary: $summary,
            source: $source,
            tier: 'hot',
            storage_tier: 'hot',
            memory_type: 'episode',
            created_at: $now,
            updated_at: $now,
            last_accessed: $now,
            access_count: 0,
            is_active: true,
            user_id: $user_id,
            session_id: $session_id,
            explicit_category: $explicit_category,
            explicit_polarity: $explicit_polarity,
            explicit_subject: $explicit_subject
        })
        RETURN e.node_id AS node_id
        """
        params = {
            "node_id": node_id,
            "content": content,
            "summary": summary,
            "source": event.source.value if event.source else None,
            "now": now.isoformat(),
            "user_id": event.user_id,
            "session_id": event.session_id,
            "explicit_category": explicit_category,
            "explicit_polarity": explicit_polarity,
            "explicit_subject": explicit_subject,
        }

        with driver.session() as session:
            result = session.run(cypher, params)
            record = result.single()

        if record is None:
            logger.warning("_create_episode_node: 未返回记录，使用本地 node_id")
            return node_id
        return record["node_id"] or node_id

    def _merge_entity_node(
        self,
        driver,
        entity: dict,
        now: datetime,
        user_id: str,
    ) -> str:
        """合并（MERGE）实体节点，返回其 node_id。

        已存在则更新 ``last_accessed`` 与 ``access_count``，否则新建。

        Args:
            driver: Neo4j 驱动
            entity: ``{"name", "type", "summary"}``
            now: 当前时间戳
            user_id: 用户标识（与 name 共同唯一确定实体）

        Returns:
            实体节点的 node_id
        """
        name = entity.get("name", "")
        if not name:
            raise ValueError("entity.name 不能为空")

        node_id = str(uuid4())
        cypher = """
        MERGE (e:Entity:MemoryNode {name: $name, user_id: $user_id})
        ON CREATE SET e.node_id = $node_id,
                      e.id = $node_id,
                      e.type = $type,
                      e.summary = $summary,
                      e.tier = 'hot',
                      e.storage_tier = 'hot',
                      e.memory_type = 'entity',
                      e.created_at = $now,
                      e.updated_at = $now,
                      e.last_accessed = $now,
                      e.access_count = 0,
                      e.is_active = true
        ON MATCH SET e.last_accessed = $now,
                     e.access_count = e.access_count + 1
        RETURN e.node_id AS node_id
        """
        params = {
            "name": name,
            "user_id": user_id,
            "node_id": node_id,
            "type": entity.get("type", "unknown"),
            "summary": entity.get("summary", ""),
            "now": now.isoformat(),
        }

        with driver.session() as session:
            result = session.run(cypher, params)
            record = result.single()

        if record is None:
            return node_id
        return record["node_id"] or node_id

    def _create_edge(
        self,
        driver,
        source_id: str,
        target_id: str,
        relation_type: str,
        t_valid_at: datetime,
        properties: Optional[dict] = None,
    ) -> None:
        """创建关系边（四时间戳双时间模型）。

        Args:
            driver: Neo4j 驱动
            source_id: 起始节点 node_id
            target_id: 目标节点 node_id
            relation_type: 关系类型（仅允许 ``[A-Za-z0-9_]``，防注入）
            t_valid_at: 事实开始有效时间
            properties: 额外边属性（可选）
        """
        if not _RELATION_TYPE_RE.match(relation_type or ""):
            raise ValueError(
                f"非法 relation_type: {relation_type!r}（仅允许字母数字下划线）"
            )

        now = datetime.utcnow()
        edge_id = str(uuid4())

        # relation_type 不能参数化，需拼接（已通过白名单校验防注入）
        cypher = f"""
        MATCH (s {{node_id: $source_id}}), (t {{node_id: $target_id}})
        CREATE (s)-[r:{relation_type} {{
            edge_id: $edge_id,
            weight: 1.0,
            t_valid_at: $t_valid_at,
            t_invalidated_at: null,
            t_transaction_start: $now,
            t_transaction_end: null,
            is_active: true,
            invalidated_by: null,
            created_at: $now,
            last_accessed_at: $now,
            access_count: 0,
            cooccurrence_count: 0
        }}]->(t)
        RETURN r
        """
        params = {
            "source_id": source_id,
            "target_id": target_id,
            "edge_id": edge_id,
            "t_valid_at": t_valid_at.isoformat(),
            "now": now.isoformat(),
        }
        if properties:
            params.update(properties)

        with driver.session() as session:
            session.run(cypher, params).consume()

    def _increment_entity_access(
        self,
        driver,
        entity_name: str,
        now: datetime,
        user_id: str,
    ) -> None:
        """自增实体访问计数并更新最后访问时间。"""
        cypher = """
        MATCH (e:Entity {name: $name, user_id: $user_id})
        SET e.access_count = e.access_count + 1,
            e.last_accessed = $now
        """
        params = {
            "name": entity_name,
            "user_id": user_id,
            "now": now.isoformat(),
        }
        with driver.session() as session:
            session.run(cypher, params).consume()

    def _increment_cooccurrence(
        self,
        driver,
        entity_a: str,
        entity_b: str,
        now: datetime,
        user_id: str,
    ) -> None:
        """自增两个实体间的 CO_OCCUR_WITH 共现计数。"""
        cypher = """
        MATCH (a:Entity {name: $name_a, user_id: $user_id}),
              (b:Entity {name: $name_b, user_id: $user_id})
        MERGE (a)-[r:CO_OCCUR_WITH]->(b)
        ON CREATE SET r.count = 1,
                      r.last_seen = $now,
                      r.weight = 0.1
        ON MATCH SET r.count = r.count + 1,
                     r.last_seen = $now
        """
        params = {
            "name_a": entity_a,
            "name_b": entity_b,
            "user_id": user_id,
            "now": now.isoformat(),
        }
        with driver.session() as session:
            session.run(cypher, params).consume()

    # =========================================================
    # pgvector 内部方法
    # =========================================================

    def _upsert_vector(
        self,
        point_id: str,
        vector: list[float],
        payload: dict,
    ) -> Optional[str]:
        """将向量写入维度分表，元数据写入 user_memory 表。

        按维度分表架构：
            1. 元数据（content/memory_type/scope 等）写入 user_memory 表（不含 embedding）
            2. 向量写入 user_memory_embedding_{dim} 表（含 memory_id 引用）

        维度来源：系统默认 embedding 模型（priority 最高的 active 模型）。

        Args:
            point_id: 与 Neo4j 节点关联的 ID（写入 embedding_node_id）
            vector: 嵌入向量（维度由系统默认 embedding 模型决定）
            payload: 元数据字典，含 ``content`` / ``event_type`` / ``user_id`` 等

        Returns:
            成功写入的 user_memory.id（字符串），失败时返回 None。
        """
        if not vector:
            logger.warning("_upsert_vector: 向量为空，跳过写入 point_id=%s", point_id)
            return None

        content = payload.get("content", "") or ""
        user_id_raw = payload.get("user_id")

        # owner_account_id 是 UUID 外键，需校验合法性
        owner_account_id: Optional[UUID] = None
        if user_id_raw is not None:
            try:
                owner_account_id = UUID(str(user_id_raw))
            except (ValueError, AttributeError, TypeError):
                logger.warning(
                    "_upsert_vector: user_id 非合法 UUID，owner_account_id 置空 user_id=%r",
                    user_id_raw,
                )
                owner_account_id = None

        if owner_account_id is None:
            # 外键约束要求非空，无法写入，降级跳过
            logger.warning(
                "_upsert_vector: owner_account_id 为空，跳过 pgvector 写入 point_id=%s",
                point_id,
            )
            return None

        # 解析系统默认维度并确保维度表已创建
        from internal.service.embedding_table_router import EmbeddingTableRouter
        router = EmbeddingTableRouter.get_instance()
        dimension = router.resolve_system_default_dimension()
        if not router.ensure_tables_for_dimension(dimension):
            logger.warning(
                "_upsert_vector: 维度 %d 表创建失败，跳过向量写入 point_id=%s",
                dimension, point_id,
            )
            return None
        table_name = router.get_user_memory_table_name(dimension)

        memory_id = uuid4()
        user_memory = UserMemory(
            id=memory_id,
            owner_account_id=owner_account_id,
            memory_type=payload.get("event_type", "episode"),
            content=content,
            embedding_node_id=point_id,
            scope="user_memory",
            created_from="memory_system",
            metadata_=payload,
        )

        try:
            # 1. 写入元数据到 user_memory 表（不含 embedding）
            self.db.session.add(user_memory)
            self.db.session.flush()

            # 2. 写入向量到维度分表
            from sqlalchemy import text as _text
            self.db.session.execute(
                _text(f"""
                    INSERT INTO {table_name} (memory_id, owner_account_id, embedding, embedding_node_id)
                    VALUES (:memory_id, :owner_id, :embedding, :node_id)
                    ON CONFLICT (memory_id) DO UPDATE SET
                        embedding = EXCLUDED.embedding,
                        updated_at = CURRENT_TIMESTAMP(0)
                """),
                {
                    "memory_id": str(memory_id),
                    "owner_id": str(owner_account_id),
                    "embedding": vector,
                    "node_id": point_id,
                },
            )
            self.db.session.commit()
            return str(memory_id)
        except Exception:
            logger.warning(
                "_upsert_vector: pgvector 写入失败 point_id=%s", point_id, exc_info=True
            )
            self.db.session.rollback()
            return None

    def _get_driver(self):
        """获取 Neo4j 驱动，不可用时返回 None 触发降级。

        优先从 ``current_app.extensions['neo4j']`` 获取（应用初始化时挂载），
        其次回退到 ``internal.extension.neo4j_extension.get_driver()`` 模块级单例。
        """
        try:
            driver = current_app.extensions.get("neo4j")
        except RuntimeError:
            # 在 Flask 应用上下文外调用
            driver = None
        if driver is None:
            try:
                from internal.extension.neo4j_extension import get_driver
                driver = get_driver()
            except Exception:
                logger.warning("_get_driver: get_driver() 调用异常", exc_info=True)
                driver = None
        return driver
