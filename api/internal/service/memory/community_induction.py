"""脑启发记忆系统（TKG）Community 层归纳 + 持久化引擎。

设计文档宣称的 P5 "新皮层层"：将 consolidation phase1 产生的 SemanticMemory
与按 name+user_id MERGE 的 Entity 归纳为长期主题（Community），完成图上的
topic/member 提升与生命周期治理。

每次 run 处理链路:
    1. 收集符合年龄条件的 SemanticMemory / Entity 聚合条目 → 候选
    2. 轻量关键词聚类（Jaccard 粗分簇）
    3. LLM 抽取主题（key/title/summary/theme_keywords）
    4. 幂等持久化 Community + TOPIC_OF/MEMBER_OF 边
    5. 候选主题治理（candidate 超 30 天无活跃 → 演化 EVOLVED_INTO / 弃用）
    6. 活跃主题治理（active 90 天未更新 → stale，再 30 天 → deprecated）

降级策略:
    - LLM 不可用/超时时返回 None/空列表，不写垃圾
    - 单步异常记录到返回 dict 的 errors，不阻断后续
    - Neo4j 不可用时返回全零统计

注意:
    - 本模块不 import consolidation_engine / ledger_writer（consolidation_engine 会
      import 本模块，由 consolidation 编排调用），仅内部构造独立的 neo4j driver。
    - (:Community) 节点不带 :MemoryNode 标签（该标签的 id 语义被 Episode 占用）。
"""

from __future__ import annotations

import json
import logging
import re
from datetime import UTC, datetime, timedelta
from typing import Optional
from uuid import uuid4

from internal.config.memory_settings import settings

logger = logging.getLogger(__name__)

# 中英停用词（模块级常量，用于轻量关键词聚类）
COMMUNITY_STOPWORDS_ZH = {
    "的", "了", "和", "与", "及", "在", "是", "我", "你", "他", "她", "它",
    "我们", "你们", "他们", "这", "那", "有", "也", "就", "都", "而", "被",
}
COMMUNITY_STOPWORDS_EN = {
    "the", "a", "an", "and", "or", "but", "of", "to", "in", "on", "for",
    "with", "is", "are", "was", "were", "am", "i", "we", "you", "it", "this",
    "that", "my", "your", "about", "have", "has", "be", "as",
}
COMMUNITY_STOPWORDS = COMMUNITY_STOPWORDS_ZH | COMMUNITY_STOPWORDS_EN


class CommunityInductionEngine:
    """Community 归纳引擎。

    不使用 ``@inject``：Neo4j 驱动由构造函数传入或运行时获取，
    配置从 ``settings.consolidation`` 读取。方法签名全部带 ``user_id``。
    """

    def __init__(self, neo4j_driver=None, config=None) -> None:
        """初始化归纳引擎。

        Args:
            neo4j_driver: Neo4j 驱动（同步）
            config: consolidation 配置实例，None 时使用 settings.consolidation
        """
        self._driver = neo4j_driver
        self._config = config or settings.consolidation

    def run_induction(self, user_id: str) -> dict:
        """执行一轮完整的 Community 归纳。

        调用链：收集候选 → 聚类 → LLM 提取主题 → 幂等持久化 → 生命周期治理。
        单步失败仅记录 errors，不阻断后续步骤。

        Args:
            user_id: 用户标识

        Returns:
            ``{"candidates": n, "created": n, "merged": n, "evolved": n,
                "deprecated": n, "errors": [..]}``
        """
        result = {
            "candidates": 0,
            "created": 0,
            "merged": 0,
            "evolved": 0,
            "deprecated": 0,
            "errors": [],
        }
        try:
            candidates = self._collect_eligible(user_id)
        except Exception as exc:
            logger.warning("run_induction: 收集候选失败", exc_info=True)
            result["errors"].append(f"collect: {exc}")
            return result

        result["candidates"] = len(candidates)
        if not candidates:
            return result

        clusters = self._cluster_candidates(user_id, candidates)

        for cluster in clusters:
            try:
                if len(cluster) < 2:
                    continue
                theme = self._extract_theme(cluster)
                if not theme:
                    continue
                existing_id = self._find_existing_community(user_id, theme.get("key") or "")
                node_id = self._persist_community(user_id, theme, cluster)
                if node_id is None:
                    continue
                if existing_id is not None:
                    result["merged"] += 1
                else:
                    result["created"] += 1
            except Exception as exc:
                result["errors"].append(f"cluster: {exc}")
                logger.warning("run_induction: 主题持久化失败", exc_info=True)

        try:
            result["evolved"] = self._evolve_stale(user_id)
        except Exception as exc:
            result["errors"].append(f"evolve: {exc}")
            logger.warning("run_induction: 演化治理失败", exc_info=True)

        try:
            result["deprecated"] = self._deprecate_inactive(user_id)
        except Exception as exc:
            result["errors"].append(f"deprecate: {exc}")
            logger.warning("run_induction: 弃用治理失败", exc_info=True)

        return result

    # =========================================================
    # 第 1 步：收集合格候选
    # =========================================================

    def _collect_eligible(self, user_id: str) -> list[dict]:
        """收集可归纳的 SemanticMemory 与 Entity 聚合条目。

        Cypher：取本用户 ``created_at <= now - community_age_days 天`` 的
        active SemanticMemory 与 Entity；Entity 按共享相同 user_id 的同类型、
        且已与语义/事件有 CONTAINS/IS_ABSTRACTION_OF 关联的实体聚合为
        ``kind='entity_group'`` 条目。总量限制 <= 40 条避免 LLM 超时。

        Returns:
            候选 dict 列表：``{"node_id", "kind", "content"/"name", "summary",
            "members", "age_days"}``
        """
        driver = self._get_driver()
        if driver is None:
            return []

        cutoff = datetime.now(UTC) - timedelta(days=self._config.community_age_days)
        candidates: list[dict] = []
        try:
            cypher_semantic = """
            MATCH (s:SemanticMemory {user_id: $user_id})
            WHERE s.is_active <> false
              AND s.created_at <= $cutoff
              AND (s.summary IS NOT NULL OR s.content IS NOT NULL)
            RETURN s.node_id AS node_id,
                   s.content AS content,
                   s.summary AS summary,
                   s.created_at AS created_at,
                   'semantic' AS kind,
                   1 AS members
            ORDER BY s.created_at ASC
            LIMIT 40
            """
            with driver.session() as session:
                result = session.run(
                    cypher_semantic,
                    {"user_id": user_id, "cutoff": cutoff.isoformat()},
                )
                for record in result:
                    content = record.get("content") or ""
                    summary = record.get("summary") or ""
                    node_id = record.get("node_id") or record.get("id") or ""
                    if not node_id or not (content or summary):
                        continue
                    candidates.append({
                        "node_id": node_id,
                        "kind": "semantic",
                        "content": content,
                        "summary": summary,
                        "members": 1,
                        "age_days": self._compute_age_days(record.get("created_at")),
                    })
        except Exception:
            logger.warning("_collect_eligible: 查询 SemanticMemory 失败", exc_info=True)
            return []

        try:
            cypher_groups = """
            MATCH (e:Entity {user_id: $user_id})
            WHERE e.is_active <> false
              AND (e.created_at IS NULL OR e.created_at <= $cutoff)
              AND (e.summary IS NOT NULL OR e.content IS NOT NULL)
            OPTIONAL MATCH (ep:Episode)-[:CONTAINS]->(e)
            OPTIONAL MATCH (sm:SemanticMemory)-[:IS_ABSTRACTION_OF]->(ep)
            WITH e, count(DISTINCT ep) AS rel_count, count(DISTINCT sm) AS abs_count
            WHERE rel_count > 0 OR abs_count > 0
            WITH e.type AS etype, collect(e) AS members
            WHERE size(members) >= 1
            RETURN etype AS etype,
                   size(members) AS member_count,
                   collect(members[0].name)[0] AS rep_name,
                   [m IN members | coalesce(m.summary, '')] AS summaries,
                   [m IN members | m.node_id] AS node_ids,
                   [m IN members | m.created_at] AS created_ats
            """
            with driver.session() as session:
                result = session.run(cypher_groups, {"user_id": user_id})
                groups = list(result)
        except Exception:
            logger.warning("_collect_eligible: 聚合 Entity 失败", exc_info=True)
            groups = []

        for group in groups:
            if len(candidates) >= 40:
                break
            etype = group.get("etype") or "unknown"
            member_count = int(group.get("member_count", 0) or 0)
            if member_count < 1:
                continue
            rep_name = group.get("rep_name") or ""
            summaries = [s for s in (group.get("summaries") or []) if s]
            joined = "；".join(str(s)[:100] for s in summaries)[:400]
            if not rep_name and not joined:
                continue
            node_ids = [n for n in (group.get("node_ids") or []) if n]
            created_ats = group.get("created_ats") or []
            age_days = 0
            if created_ats:
                try:
                    age_days = self._compute_age_days(created_ats[0])
                except Exception:
                    age_days = 0
            candidates.append({
                "node_id": f"eg_{etype}_{node_ids[0]}" if node_ids else f"eg_{etype}",
                "kind": "entity_group",
                "name": rep_name,
                "summary": joined,
                "members": member_count,
                "age_days": age_days,
                "entity_ids": node_ids,
                "entity_type": etype,
            })

        return candidates[:40]

    def _compute_age_days(self, created_at) -> int:
        """将 Neo4j 返回的 created_at 字符串换算为天数。"""
        try:
            if created_at is None:
                return 0
            text = str(created_at)
            if text.endswith("Z"):
                text = text[:-1] + "+00:00"
            created = datetime.fromisoformat(text)
            if created.tzinfo is None:
                created = created.replace(tzinfo=UTC)
            return max(0, int((datetime.now(UTC) - created).total_seconds() // 86400))
        except Exception:
            return 0

    # =========================================================
    # 第 2 步：轻量关键词聚类
    # =========================================================

    def _cluster_candidates(self, user_id: str, candidates: list[dict]) -> list[list[dict]]:
        """用轻量关键词 overlap 对候选做贪心粗分簇。

        取 summary 前 80 字去停用词，两两 Jaccard >=
        ``community_similarity_threshold * 0.6`` 归为一簇；成员不足
        community_min_evidence 的簇仍允许输出，但至少 2 个成员才进 LLM。

        Args:
            user_id: 用户标识（保留，便于后续接入 pgvector/全文索引）
            candidates: ``_collect_eligible`` 返回的候选列表

        Returns:
            list[list[dict]]：候选簇列表（贪心：候选只加入相似度最高的既有簇，
            否则自成一簇）
        """
        if not candidates:
            return []

        tokenized = []
        for cand in candidates:
            text = str(cand.get("summary") or cand.get("content") or cand.get("name") or "")
            tokenized.append(self._tokenize(text))

        clusters: list[list[dict]] = []
        for idx, cand in enumerate(candidates):
            best_cluster = -1
            best_score = 0.0
            for c_idx, cluster in enumerate(clusters):
                for member in cluster:
                    member_text = str(
                        member.get("summary") or member.get("content") or member.get("name") or ""
                    )
                    score = self._jaccard(tokenized[idx], self._tokenize(member_text))
                    if score > best_score:
                        best_score = score
                        best_cluster = c_idx

            if best_cluster >= 0 and best_score >= self._config.community_similarity_threshold * 0.6:
                clusters[best_cluster].append(cand)
            else:
                clusters.append([cand])

        return clusters

    def _tokenize(self, text: str) -> list[str]:
        """对文本做关键词 token 化（中英各按字符/单词切分，去除停用词与噪声）。"""
        if not text:
            return []
        text = str(text)[:80]
        text_lower = text.lower()
        english = re.findall(r"[a-z][a-z0-9]{1,}", text_lower)
        chinese = re.findall(r"[\u4e00-\u9fff]", text)
        combined = english + chinese
        filtered = []
        for word in combined:
            if word in COMMUNITY_STOPWORDS:
                continue
            filtered.append(word)
        return filtered

    @staticmethod
    def _jaccard(a: list[str], b: list[str]) -> float:
        """两个 token 集合的 Jaccard 相似度（并集为空时返回 0.0）。"""
        if not a or not b:
            return 0.0
        set_a, set_b = set(a), set(b)
        union = set_a | set_b
        if not union:
            return 0.0
        return float(len(set_a & set_b)) / float(len(union))

    # =========================================================
    # 第 3 步：LLM 抽取主题
    # =========================================================

    def _extract_theme(self, cluster) -> Optional[dict]:
        """对簇调用 LLM 抽取主题（key/title/summary/theme_keywords）。

        使用 LLMActivityProbe 包装，死机/超时/解析失败返回 None（不抛、不写垃圾）。
        解析 LLM JSON 输出；key 归一化为小写连字符 slug，summary 限 400 字符。

        Args:
            cluster: 候选簇（list[dict]）

        Returns:
            ``{"key", "title", "summary", "theme_keywords"}`` 或 None
        """
        if not cluster:
            return None

        evidence_lines = []
        for cand in cluster:
            text = (
                str(cand.get("summary") or "")
                or str(cand.get("content") or "")
                or str(cand.get("name") or "")
            )
            if text:
                evidence_lines.append(f"- {self._safe_text(text, 200)}")

        if not evidence_lines:
            return None

        try:
            from internal.service.language_model_service import LanguageModelService
            from internal.service.memory.llm_activity_probe import (
                LLMActivityProbe,
                LLMActivityTimeoutError,
            )
            from internal.service.system_prompt_library_service import SystemPromptLibraryService

            prompt = SystemPromptLibraryService().get_prompt_or_default(
                "memory_community_induction_prompt"
            ).format(evidence="\n".join(evidence_lines))

            llm = LanguageModelService.get_feature_model("memory_consolidation")
            result = LLMActivityProbe.invoke_with_probe(
                llm, prompt, feature_key="memory_consolidation"
            )
            content = getattr(result, "content", None)
            if content is None:
                content = str(result)
            data = json.loads(content.strip())

            if not isinstance(data, dict):
                return None

            key = self._safe_slug(str(data.get("key") or ""))
            title = self._safe_text(str(data.get("title") or ""), 80)
            summary = self._safe_text(str(data.get("summary") or ""), 400)
            if not key or not summary:
                return None

            theme_keywords = data.get("theme_keywords") or []
            if not isinstance(theme_keywords, list):
                theme_keywords = []
            theme_keywords = [
                self._safe_text(str(kw), 30) for kw in theme_keywords if str(kw).strip()
            ]

            return {
                "key": key,
                "title": title,
                "summary": summary,
                "theme_keywords": theme_keywords,
            }
        except LLMActivityTimeoutError as exc:
            logger.warning(
                "_extract_theme: LLM 探针检测到死机，终止主题归纳（不写垃圾）: %s",
                exc,
            )
            return None
        except Exception:
            logger.warning("_extract_theme: LLM 抽取主题失败", exc_info=True)
            return None

    @staticmethod
    def _safe_slug(value: str) -> str:
        """将任意文本归一化为小写、连字符分隔的 slug。"""
        value = (value or "").strip().lower()
        value = re.sub(r"[^a-z0-9\u4e00-\u9fff]+", "-", value)
        value = re.sub(r"-{2,}", "-", value).strip("-")
        return value[:64]

    def _find_existing_community(self, user_id: str, key: str) -> Optional[str]:
        """查找用户已有 active/candidate 的 ``(:Community)``（按 key 精确匹配）。

        Returns:
            命中主题的 node_id；无命中返回 None
        """
        if not key:
            return None
        driver = self._get_driver()
        if driver is None:
            return None
        try:
            cypher = """
            MATCH (c:Community {user_id: $user_id, key: $key})
            WHERE c.status IN ['active', 'candidate']
              AND c.is_active <> false
            RETURN c.node_id AS node_id
            LIMIT 1
            """
            with driver.session() as session:
                record = session.run(
                    cypher,
                    {"user_id": user_id, "key": key},
                ).single()
            if record and record.get("node_id"):
                return record["node_id"]
            return None
        except Exception:
            logger.warning("_find_existing_community: 查重失败 key=%s", key, exc_info=True)
            return None

    # =========================================================
    # 第 4 步：幂等持久化 Community
    # =========================================================

    def _persist_community(self, user_id: str, theme: dict, cluster) -> Optional[str]:
        """幂等持久化主题：按 ``(key, user_id)`` MERGE → 更新或新建 Community + 建边。

        命中 active/candidate 的 ``(:Community {user_id, key})`` 时：更新
        ``last_active_at/summary(若新更长)/evidence_count+1``，并把命中成员建立边
        （已存在边则跳过，不重复计数）。未命中则新建 ``(:Community)`` + 建立
        TOPIC_OF/MEMBER_OF 边。节点带 ``source='community_induction'``。

        Args:
            user_id: 用户标识
            theme: ``_extract_theme`` 返回的主题 dict
            cluster: 候选簇（list[dict]）

        Returns:
            Community 的 node_id；失败返回 None
        """
        driver = self._get_driver()
        if driver is None:
            return None

        now_iso = datetime.now(UTC).isoformat()
        community_id = uuid4().hex
        key = theme.get("key") or ""
        if not key:
            return None

        evidence_count = max(1, sum(int(m.get("members", 1) or 1) for m in cluster))
        summary = theme.get("summary") or ""
        title = theme.get("title") or summary[:40]
        keywords = theme.get("theme_keywords") or []
        maturity = self._compute_maturity(cluster)

        try:
            cypher = """
            MERGE (c:Community {user_id: $user_id, key: $key})
            ON CREATE SET c.node_id = $community_id,
                          c.id = $community_id,
                          c.title = $title,
                          c.summary = $summary,
                          c.theme_keywords = $keywords,
                          c.status = 'candidate',
                          c.maturity = $maturity,
                          c.evidence_count = $evidence_count,
                          c.member_count = $member_count,
                          c.created_at = $now_iso,
                          c.updated_at = $now_iso,
                          c.last_active_at = $now_iso,
                          c.evolution_of = null,
                          c.is_active = true,
                          c.source = 'community_induction'
            ON MATCH SET c.last_active_at = $now_iso,
                         c.evidence_count = coalesce(c.evidence_count, 0) + 1,
                         c.updated_at = CASE
                             WHEN coalesce(c.updated_at, '') = ''
                               OR size(coalesce(c.summary, '')) < size($summary)
                             THEN $now_iso ELSE c.updated_at END,
                         c.summary = CASE
                             WHEN size(coalesce(c.summary, '')) < size($summary)
                             THEN $summary ELSE c.summary END,
                         c.title = CASE
                             WHEN coalesce(c.title, '') = '' THEN $title
                             ELSE c.title END,
                         c.maturity = CASE
                             WHEN c.maturity IS NULL THEN $maturity
                             WHEN $maturity > coalesce(c.maturity, 0.0) THEN $maturity
                             ELSE c.maturity END,
                         c.is_active = true
            RETURN c.node_id AS node_id
            """
            with driver.session() as session:
                record = session.run(
                    cypher,
                    {
                        "community_id": community_id,
                        "user_id": user_id,
                        "key": key,
                        "title": title,
                        "summary": summary,
                        "keywords": keywords,
                        "maturity": maturity,
                        "evidence_count": evidence_count,
                        "member_count": len(cluster),
                        "now_iso": now_iso,
                    },
                ).single()

            node_id = record["node_id"] if record else community_id
            self._link_members(user_id, node_id, cluster, now_iso)
            return node_id
        except Exception:
            logger.warning("_persist_community: 持久化主题失败 key=%s", key, exc_info=True)
            return None

    @staticmethod
    def _compute_maturity(cluster) -> float:
        """依据成员数与年龄粗算成熟度（0~1）。"""
        if not cluster:
            return 0.0
        member_count = sum(int(m.get("members", 1) or 1) for m in cluster)
        evidence = max(1.0, float(member_count))
        raw = 1.0 - 1.0 / evidence
        return max(0.0, min(1.0, round(raw, 4)))

    def _link_members(self, user_id: str, community_id: str, cluster, now_iso: str) -> None:
        """为 Community 建立 TOPIC_OF/MEMBER_OF 边（已存在则跳过）。

        semantic 成员建 ``(c)-[:TOPIC_OF {edge_id, weight, created_at,
        is_active:true}]->(s:SemanticMemory)``；entity_group 成员对组内每个
        Entity 建 ``(c)-[:MEMBER_OF {...}]->(e:Entity)``。
        """
        driver = self._get_driver()
        if driver is None or not cluster:
            return

        semantic_ids = [
            m.get("node_id", "") for m in cluster if m.get("kind") == "semantic" and m.get("node_id")
        ]
        entity_ids: list[str] = []
        for member in cluster:
            if member.get("kind") != "entity_group":
                continue
            ids = member.get("entity_ids") or []
            for nid in ids:
                if nid and nid not in entity_ids:
                    entity_ids.append(nid)

        try:
            for sid in semantic_ids:
                edge_id = uuid4().hex
                cypher = """
                MATCH (c:Community {node_id: $cid}), (s:SemanticMemory {node_id: $sid})
                MERGE (c)-[r:TOPIC_OF]->(s)
                ON CREATE SET r.edge_id = $edge_id,
                              r.weight = $weight,
                              r.created_at = $now_iso,
                              r.is_active = true
                ON MATCH SET r.weight = CASE WHEN r.weight IS NULL THEN $weight
                                             ELSE r.weight END,
                             r.created_at = CASE WHEN r.created_at IS NULL
                                                 THEN $now_iso ELSE r.created_at END,
                             r.is_active = true
                """
                with driver.session() as session:
                    session.run(
                        cypher,
                        {
                            "cid": community_id,
                            "sid": sid,
                            "edge_id": edge_id,
                            "weight": 1.0,
                            "now_iso": now_iso,
                        },
                    ).consume()
        except Exception:
            logger.warning("_link_members: 建立 TOPIC_OF 边失败", exc_info=True)

        try:
            for eid in entity_ids:
                edge_id = uuid4().hex
                cypher = """
                MATCH (c:Community {node_id: $cid}), (e:Entity {node_id: $eid})
                MERGE (c)-[r:MEMBER_OF]->(e)
                ON CREATE SET r.edge_id = $edge_id,
                              r.weight = $weight,
                              r.created_at = $now_iso,
                              r.is_active = true
                ON MATCH SET r.weight = CASE WHEN r.weight IS NULL THEN $weight
                                             ELSE r.weight END,
                             r.created_at = CASE WHEN r.created_at IS NULL
                                                 THEN $now_iso ELSE r.created_at END,
                             r.is_active = true
                """
                with driver.session() as session:
                    session.run(
                        cypher,
                        {
                            "cid": community_id,
                            "eid": eid,
                            "edge_id": edge_id,
                            "weight": 1.0,
                            "now_iso": now_iso,
                        },
                    ).consume()
        except Exception:
            logger.warning("_link_members: 建立 MEMBER_OF 边失败", exc_info=True)

    # =========================================================
    # 第 5 步：候选主题演化治理
    # =========================================================

    def _evolve_stale(self, user_id: str) -> int:
        """对超 30 天无活跃的 candidate Community 执行演化（限 3/run 防抖）。

        治理开关 ``community_governance_enabled=False`` 时跳过。每个候选复用其
        当前成员证据 + 该用户最新 hot SemanticMemory 追加条目再抽主题；新主题与
        老主题 summary 相似度 >= community_merge_threshold 则跳过；否则创建新
        Community（``evolution_of=老 node_id``）+ EVOLVED_INTO 边 + 迁移
        TOPIC_OF/MEMBER_OF 边，老节点 ``status='deprecated', is_active:false``。

        Args:
            user_id: 用户标识

        Returns:
            演化成功数
        """
        if not self._config.community_governance_enabled:
            return 0
        driver = self._get_driver()
        if driver is None:
            return 0

        stale_cutoff = datetime.now(UTC) - timedelta(days=30)
        evolved = 0
        try:
            cypher = """
            MATCH (c:Community {user_id: $user_id})
            WHERE c.status = 'candidate'
              AND (c.last_active_at IS NULL OR c.last_active_at < $cutoff)
            RETURN c.node_id AS node_id,
                   c.key AS key,
                   c.title AS title,
                   c.summary AS summary
            ORDER BY c.updated_at ASC
            LIMIT 5
            """
            with driver.session() as session:
                records = list(session.run(
                    cypher,
                    {"user_id": user_id, "cutoff": stale_cutoff.isoformat()},
                ))
        except Exception:
            logger.warning("_evolve_stale: 查询候选主题失败", exc_info=True)
            return 0

        for record in records[:3]:
            try:
                old_id = record.get("node_id")
                old_key = record.get("key") or ""
                old_summary = record.get("summary") or ""
                if not old_id:
                    continue

                members = self._load_community_members(user_id, old_id)
                fresh = self._load_latest_semantics(user_id)
                evidence_cluster = members + fresh
                if not evidence_cluster:
                    continue

                theme = self._extract_theme(evidence_cluster)
                if not theme:
                    continue

                if self._text_similarity(theme.get("summary") or "", old_summary) >= self._config.community_merge_threshold:
                    continue

                new_id = self._create_evolved_community(user_id, old_id, theme, members)
                if new_id is not None:
                    evolved += 1
            except Exception as exc:
                logger.warning("_evolve_stale: 单个主题演化失败", exc_info=True)
                continue

        return evolved

    def _load_community_members(self, user_id: str, community_id: str) -> list[dict]:
        """读取一个 Community 的当前证据（TOPIC_OF/MEMBER_OF 边指向的成员）。"""
        driver = self._get_driver()
        if driver is None:
            return []
        try:
            cypher = """
            MATCH (c:Community {user_id: $user_id, node_id: $cid})-[r:TOPIC_OF|MEMBER_OF]->(m)
            RETURN m.node_id AS node_id,
                   type(r) AS rel,
                   m.summary AS summary,
                   m.content AS content,
                   m.name AS name
            """
            with driver.session() as session:
                records = list(session.run(
                    cypher,
                    {"user_id": user_id, "cid": community_id},
                ))
            members = []
            for record in records:
                rel = record.get("rel")
                node_id = record.get("node_id") or ""
                if not node_id:
                    continue
                members.append({
                    "node_id": node_id,
                    "kind": "semantic" if rel == "TOPIC_OF" else "entity",
                    "summary": record.get("summary") or record.get("content") or record.get("name") or "",
                    "members": 1,
                })
            return members
        except Exception:
            logger.warning("_load_community_members: 读取成员失败", exc_info=True)
            return []

    def _load_latest_semantics(self, user_id: str) -> list[dict]:
        """读取用户最新的 hot SemanticMemory，作为演化时的追加证据。"""
        driver = self._get_driver()
        if driver is None:
            return []
        try:
            cypher = """
            MATCH (s:SemanticMemory {user_id: $user_id})
            WHERE s.is_active <> false
              AND (s.storage_tier IS NULL OR s.storage_tier = 'hot')
            RETURN s.node_id AS node_id,
                   s.summary AS summary,
                   s.content AS content,
                   s.created_at AS created_at
            ORDER BY s.created_at DESC
            LIMIT 3
            """
            with driver.session() as session:
                records = list(session.run(cypher, {"user_id": user_id}))
            result = []
            for record in records:
                node_id = record.get("node_id") or ""
                if not node_id:
                    continue
                result.append({
                    "node_id": node_id,
                    "kind": "semantic",
                    "summary": record.get("summary") or record.get("content") or "",
                    "members": 1,
                })
            return result
        except Exception:
            logger.warning("_load_latest_semantics: 读取失败", exc_info=True)
            return []

    def _create_evolved_community(
        self,
        user_id: str,
        old_community_id: str,
        theme: dict,
        members,
    ) -> Optional[str]:
        """创建演化后的新 Community + EVOLVED_INTO 边，并迁移成员边、弃用老节点。

        Returns:
            新 Community 的 node_id；失败返回 None
        """
        driver = self._get_driver()
        if driver is None:
            return None
        now_iso = datetime.now(UTC).isoformat()
        new_id = uuid4().hex
        key = theme.get("key") or uuid4().hex[:12]
        summary = theme.get("summary") or ""
        title = theme.get("title") or summary[:40]

        try:
            cypher = """
            MATCH (old:Community {node_id: $old_id})
            CREATE (new:Community {
                node_id: $new_id,
                id: $new_id,
                key: $key,
                title: $title,
                summary: $summary,
                user_id: $user_id,
                status: 'candidate',
                maturity: $maturity,
                evidence_count: $evidence_count,
                member_count: $member_count,
                created_at: $now_iso,
                updated_at: $now_iso,
                last_active_at: $now_iso,
                evolution_of: $old_id,
                is_active: true,
                source: 'community_induction'
            })
            CREATE (old)-[:EVOLVED_INTO {
                edge_id: $edge_id,
                created_at: $now_iso,
                is_active: true
            }]->(new)
            SET old.status = 'deprecated',
                old.is_active = false,
                old.updated_at = $now_iso
            RETURN new.node_id AS node_id
            """
            with driver.session() as session:
                record = session.run(
                    cypher,
                    {
                        "old_id": old_community_id,
                        "new_id": new_id,
                        "key": key,
                        "title": title,
                        "summary": summary,
                        "user_id": user_id,
                        "maturity": self._compute_maturity(members or [{"members": 1}]),
                        "evidence_count": sum(
                            int(m.get("members", 1) or 1) for m in (members or [])
                        ),
                        "member_count": len(members or []),
                        "edge_id": uuid4().hex,
                        "now_iso": now_iso,
                    },
                ).single()

            created_id = record["node_id"] if record else new_id
            self._migrate_member_edges(old_community_id, created_id)
            return created_id
        except Exception:
            logger.warning("_create_evolved_community: 演化失败", exc_info=True)
            return None

    def _migrate_member_edges(self, old_id: str, new_id: str) -> None:
        """将老 Community 的 TOPIC_OF/MEMBER_OF 边迁移到新 Community，并弃用老边。"""
        driver = self._get_driver()
        if driver is None:
            return
        try:
            now_iso = datetime.now(UTC).isoformat()
            for rel_type, target_label in (("TOPIC_OF", "SemanticMemory"), ("MEMBER_OF", "Entity")):
                cypher = f"""
                MATCH (old:Community {{node_id: $old_id}})-[r:{rel_type}]->(m:{target_label})
                MATCH (new:Community {{node_id: $new_id}})
                MERGE (new)-[nr:{rel_type}]->(m)
                ON CREATE SET nr.edge_id = $edge_id,
                              nr.weight = coalesce(r.weight, 1.0),
                              nr.created_at = $now_iso,
                              nr.is_active = true
                ON MATCH SET nr.weight = CASE WHEN nr.weight IS NULL
                                              THEN coalesce(r.weight, 1.0)
                                              ELSE nr.weight END,
                             nr.created_at = CASE WHEN nr.created_at IS NULL
                                                  THEN $now_iso ELSE nr.created_at END,
                             nr.is_active = true
                SET r.is_active = false
                """
                with driver.session() as session:
                    session.run(
                        cypher,
                        {
                            "old_id": old_id,
                            "new_id": new_id,
                            "edge_id": uuid4().hex,
                            "now_iso": now_iso,
                        },
                    ).consume()
        except Exception:
            logger.warning("_migrate_member_edges: 迁移失败", exc_info=True)

    def _text_similarity(self, a: str, b: str) -> float:
        """对两段 summary 计算 Jaccard 文本相似度（中文按字 + 英文按词）。"""
        return self._jaccard(self._tokenize(a), self._tokenize(b))

    # =========================================================
    # 第 6 步：活跃主题弃用治理
    # =========================================================

    def _deprecate_inactive(self, user_id: str) -> int:
        """活跃主题生命周期转移：active 超 90 天 → stale，stale 再超 30 天 → deprecated。

        治理开关 ``community_governance_enabled=False`` 时跳过。

        Args:
            user_id: 用户标识

        Returns:
            发生状态转移（或弃用）的主题数
        """
        if not self._config.community_governance_enabled:
            return 0
        driver = self._get_driver()
        if driver is None:
            return 0

        now = datetime.now(UTC)
        stale_cutoff = now - timedelta(days=90)
        deprecated_cutoff = now - timedelta(days=120)
        changed = 0
        try:
            cypher = """
            MATCH (c:Community {user_id: $user_id})
            WHERE c.status = 'active'
              AND (c.updated_at IS NULL OR c.updated_at < $stale_cutoff)
              AND (c.is_active <> false)
            SET c.status = 'stale',
                c.updated_at = CASE
                    WHEN c.updated_at IS NULL THEN $now_iso ELSE c.updated_at END
            RETURN count(c) AS n
            """
            with driver.session() as session:
                record = session.run(
                    cypher,
                    {
                        "user_id": user_id,
                        "stale_cutoff": stale_cutoff.isoformat(),
                        "now_iso": now.isoformat(),
                    },
                ).single()
            if record:
                changed += int(record.get("n", 0) or 0)
        except Exception:
            logger.warning("_deprecate_inactive: active→stale 失败", exc_info=True)

        try:
            cypher = """
            MATCH (c:Community {user_id: $user_id})
            WHERE c.status = 'stale'
              AND (c.updated_at IS NULL OR c.updated_at < $deprecated_cutoff)
            SET c.status = 'deprecated',
                c.is_active = false,
                c.updated_at = $now_iso
            RETURN count(c) AS n
            """
            with driver.session() as session:
                record = session.run(
                    cypher,
                    {
                        "user_id": user_id,
                        "deprecated_cutoff": deprecated_cutoff.isoformat(),
                        "now_iso": now.isoformat(),
                    },
                ).single()
            if record:
                changed += int(record.get("n", 0) or 0)
        except Exception:
            logger.warning("_deprecate_inactive: stale→deprecated 失败", exc_info=True)

        return changed

    # =========================================================
    # 辅助
    # =========================================================

    @staticmethod
    def _safe_text(value, limit: int) -> str:
        """截断任意文本到指定长度并清洗空白。"""
        text = str(value or "")
        text = re.sub(r"\s+", " ", text).strip()
        return text[:limit]

    def _get_driver(self):
        """获取 Neo4j 驱动：优先参数 → current_app.extensions['neo4j'] → 回退扩展。"""
        if self._driver is not None:
            return self._driver
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
