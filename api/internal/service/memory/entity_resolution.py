"""TKG 实体消解（Entity Resolution）模块。

对新提取的实体判断是创建新节点还是合并到已有实体，融合三路信号：
  1. 向量相似度（pgvector 余弦相似度）
  2. BM25 文本匹配（Neo4j 全文索引 score + Levenshtein 编辑距离）
  3. LLM 判定（结构化输出 0.0-1.0 评分）

三路信号加权融合后与 merge_threshold 比较，决定合并或新建。
任一信号异常时降级为 0.0，主流程不中断。
"""

import logging
from dataclasses import dataclass
from typing import Optional
from uuid import UUID

from injector import inject
from pydantic import BaseModel, Field
from sqlalchemy import select

from internal.config.memory_settings import settings
from internal.model.knowledge import UserMemory
from internal.model.memory_models import EntityCandidate, EntityResolutionResult
from internal.service.language_model_service import LanguageModelService
from internal.service.memory.llm_activity_probe import (
    LLMActivityProbe,
    LLMActivityTimeoutError,
)
from pkg.sqlalchemy import SQLAlchemy

logger = logging.getLogger(__name__)


class _LLMJudgeResult(BaseModel):
    """LLM 实体同一性判定结构化输出。"""

    score: float = Field(..., ge=0.0, le=1.0, description="同一性置信度 [0, 1]")
    reasoning: str = Field(..., description="判定理由")


@inject
@dataclass
class EntityResolver:
    """实体消解器：三信号融合判定新实体是合并还是新建。

    依赖注入：
        db: SQLAlchemy 会话工厂，用于 pgvector 向量相似度查询。
    """

    db: SQLAlchemy

    def resolve(
        self,
        entity_name: str,
        entity_type: str,
        entity_summary: str,
        embedding: list[float],
        user_id: str,
    ) -> EntityResolutionResult:
        """对单个新实体执行消解。

        Args:
            entity_name: 新实体名称。
            entity_type: 新实体类型。
            entity_summary: 新实体摘要。
            embedding: 新实体语义嵌入向量。
            user_id: 用户标识（多用户隔离）。

        Returns:
            EntityResolutionResult: merged_entity 为 None 表示新建，
            否则为合并目标实体 ID。
        """
        # 1. 获取 driver（降级检查）
        driver = self._get_driver()
        if driver is None:
            logger.warning("Neo4j 驱动不可用，实体消解降级为新建: %s", entity_name)
            return EntityResolutionResult(
                merged_entity=None,
                candidates=[],
                confidence=1.0,
                method="no_driver",
            )

        # 2. 检索候选实体（直接 MATCH + 全文索引补充，按 node_id 合并去重）
        candidates = self._retrieve_candidates(driver, entity_name, entity_type, user_id)
        if not candidates:
            logger.debug("无候选实体，新建: %s", entity_name)
            return EntityResolutionResult(
                merged_entity=None,
                candidates=[],
                confidence=1.0,
                method="no_candidates",
            )

        # 4. 向量相似度（pgvector 余弦距离）
        candidates = self._compute_vector_scores(candidates, embedding)
        # 5. BM25 文本匹配（全文索引 score + 编辑距离）
        candidates = self._compute_bm25_scores(candidates, entity_name)
        # 6. LLM 判定（仅对预筛 0.5*vector + 0.5*bm25 >= 0.6 的候选拉 LLM）
        candidates = self._compute_llm_scores(candidates, entity_name, entity_summary)

        # 7. 三信号加权融合
        er_cfg = settings.write.entity_resolution
        w_vector = er_cfg.vector_weight
        w_bm25 = er_cfg.bm25_weight
        w_llm = er_cfg.llm_judge_weight
        for c in candidates:
            c["fused_score"] = (
                w_vector * c.get("vector_score", 0.0)
                + w_bm25 * c.get("bm25_score", 0.0)
                + w_llm * c.get("llm_score", 0.0)
            )

        # 8. 取最高分候选
        best = max(candidates, key=lambda c: c.get("fused_score", 0.0))
        best_fused = best.get("fused_score", 0.0)

        # 构建候选列表（调试/审计用）
        candidate_models = [
            EntityCandidate(
                name=c.get("name", ""),
                type=entity_type,
                score=c.get("fused_score", 0.0),
            )
            for c in candidates
        ]

        # 9. 阈值判定：合并 or 新建
        if best_fused >= er_cfg.merge_threshold:
            merged_id = self._to_uuid(best.get("node_id"))
            logger.info(
                "实体消解合并: '%s' -> %s (fused=%.4f)",
                entity_name, merged_id, best_fused,
            )
            return EntityResolutionResult(
                merged_entity=merged_id,
                candidates=candidate_models,
                confidence=best_fused,
                method="fused_match",
            )

        logger.info(
            "实体消解新建: '%s' (best_fused=%.4f < %.2f)",
            entity_name, best_fused, er_cfg.merge_threshold,
        )
        return EntityResolutionResult(
            merged_entity=None,
            candidates=candidate_models,
            confidence=max(0.0, 1.0 - best_fused),
            method="below_threshold",
        )

    # ------------------------------------------------------------------
    # 三信号计算
    # ------------------------------------------------------------------

    def _retrieve_candidates(
        self,
        driver,
        entity_name: str,
        entity_type: str,
        user_id: str,
    ) -> list[dict]:
        """检索候选实体：直接类型匹配 + 全文索引补充，按 node_id 合并去重。

        Args:
            driver: Neo4j 驱动。
            entity_name: 新实体名称（同时作为全文检索查询）。
            entity_type: 实体类型（直接 MATCH 过滤）。
            user_id: 用户标识（多用户隔离）。

        Returns:
            候选字典列表，每项含 node_id / name / summary / fulltext_score。
        """
        by_node: dict[str, dict] = {}

        try:
            with driver.session() as session:
                # 直接类型 + 用户隔离匹配
                direct_result = session.run(
                    "MATCH (e:Entity {type: $type, is_active: true, user_id: $user_id}) "
                    "RETURN e.node_id AS node_id, e.name AS name, e.summary AS summary",
                    type=entity_type,
                    user_id=user_id,
                )
                for row in direct_result:
                    nid = row["node_id"]
                    by_node[nid] = {
                        "node_id": nid,
                        "name": row["name"],
                        "summary": row["summary"] or "",
                        "fulltext_score": 0.0,
                    }

                # 全文索引补充（按 user_id 过滤确保多用户隔离）
                try:
                    fulltext_result = session.run(
                        "CALL db.index.fulltext.queryNodes('entityFullText', $query) "
                        "YIELD node, score "
                        "WHERE node.user_id = $user_id AND node.is_active = true "
                        "RETURN node.node_id AS node_id, node.name AS name, "
                        "node.summary AS summary, score",
                        query=entity_name,
                        user_id=user_id,
                    )
                    for row in fulltext_result:
                        nid = row["node_id"]
                        if nid in by_node:
                            by_node[nid]["fulltext_score"] = row["score"]
                        else:
                            by_node[nid] = {
                                "node_id": nid,
                                "name": row["name"],
                                "summary": row["summary"] or "",
                                "fulltext_score": row["score"],
                            }
                except Exception:
                    logger.warning(
                        "全文索引检索失败，仅使用直接匹配候选: %s",
                        entity_name, exc_info=True,
                    )
        except Exception:
            logger.warning("Neo4j 候选检索失败: %s", entity_name, exc_info=True)
            return []

        return list(by_node.values())

    def _compute_vector_scores(
        self,
        candidates: list[dict],
        query_embedding: list[float],
    ) -> list[dict]:
        """对每个候选用 pgvector 查询余弦相似度。

        异常时该候选 vector_score 降级为 0.0。
        """
        for c in candidates:
            try:
                stmt = (
                    select(
                        UserMemory.embedding.cosine_distance(query_embedding).label("distance")
                    )
                    .where(UserMemory.embedding_node_id == c["node_id"])
                    .where(UserMemory.embedding != None)  # noqa: E711
                    .limit(1)
                )
                row = self.db.session.execute(stmt).first()
                if row and row.distance is not None:
                    c["vector_score"] = max(0.0, 1.0 - float(row.distance))
                else:
                    c["vector_score"] = 0.0
            except Exception:
                logger.warning(
                    "向量相似度查询失败，降级为 0.0: %s", c.get("name"), exc_info=True
                )
                c["vector_score"] = 0.0
        return candidates

    def _compute_bm25_scores(
        self,
        candidates: list[dict],
        query_name: str,
    ) -> list[dict]:
        """BM25 文本匹配：Neo4j 全文索引 score + Levenshtein 编辑距离，取 max。

        编辑距离在 edit_distance_threshold 内时额外加 0.2 奖励。
        """
        edit_threshold = settings.write.entity_resolution.edit_distance_threshold
        for c in candidates:
            # Neo4j fulltext score（检索阶段已获得）
            neo4j_score = float(c.get("fulltext_score", 0.0) or 0.0)
            # 编辑距离归一化
            dist = self._levenshtein_distance(
                query_name.lower(), (c.get("name") or "").lower()
            )
            max_len = max(len(query_name), len(c.get("name") or ""), 1)
            edit_score = 1.0 - min(1.0, dist / max_len)
            if dist <= edit_threshold:
                edit_score = min(1.0, edit_score + 0.2)
            # 综合取 max
            c["bm25_score"] = max(neo4j_score, edit_score)
        return candidates

    def _compute_llm_scores(
        self,
        candidates: list[dict],
        new_name: str,
        new_summary: str,
    ) -> list[dict]:
        """LLM 判定：仅对预筛 0.5*vector + 0.5*bm25 >= 0.6 的候选拉 LLM 评分。

        其余候选 llm_score = 0.0；LLM 异常时降级为 0.0。
        """
        for c in candidates:
            preliminary = 0.5 * c.get("vector_score", 0.0) + 0.5 * c.get("bm25_score", 0.0)
            if preliminary < 0.6:
                c["llm_score"] = 0.0
                continue
            from internal.service.system_prompt_library_service import SystemPromptLibraryService
            prompt = SystemPromptLibraryService().get_prompt_or_default(
                "memory_entity_resolution_prompt"
            ).format(
                new_name=new_name,
                new_summary=new_summary,
                entity_b_name=c.get("name", ""),
                entity_b_summary=c.get("summary", ""),
            )
            try:
                llm = LanguageModelService.get_feature_model("memory_entity_resolution")
                result: _LLMJudgeResult = LLMActivityProbe.invoke_structured_with_probe(
                    llm, _LLMJudgeResult, prompt,
                    feature_key="memory_entity_resolution",
                )
                c["llm_score"] = max(0.0, min(1.0, float(result.score)))
            except LLMActivityTimeoutError as exc:
                logger.warning(
                    "LLM 实体判定探针检测到死机，降级为 0.0（不写垃圾）: %s vs %s: %s",
                    new_name, c.get("name"), exc,
                )
                c["llm_score"] = 0.0
            except Exception:
                logger.warning(
                    "LLM 实体判定失败，降级为 0.0: %s vs %s",
                    new_name, c.get("name"), exc_info=True,
                )
                c["llm_score"] = 0.0
        return candidates

    # ------------------------------------------------------------------
    # 工具方法
    # ------------------------------------------------------------------

    def _levenshtein_distance(self, s1: str, s2: str) -> int:
        """纯 Python 单行 DP 实现 Levenshtein 编辑距离。"""
        if len(s1) < len(s2):
            return self._levenshtein_distance(s2, s1)
        if len(s2) == 0:
            return len(s1)
        prev = list(range(len(s2) + 1))
        for i, c1 in enumerate(s1):
            curr = [i + 1]
            for j, c2 in enumerate(s2):
                ins = prev[j + 1] + 1
                dele = curr[j] + 1
                sub = prev[j] + (c1 != c2)
                curr.append(min(ins, dele, sub))
            prev = curr
        return prev[-1]

    def _get_driver(self):
        """获取 Neo4j 驱动（降级检查）：优先 app.extensions，回退模块单例。

        Returns:
            Driver 实例或 None（不可用时降级）。
        """
        from internal.context import current_app
        driver = current_app.extensions.get("neo4j")
        if driver is None:
            from internal.extension.neo4j_extension import get_driver
            driver = get_driver()
        return driver

    @staticmethod
    def _to_uuid(node_id) -> Optional[UUID]:
        """将 Neo4j 返回的 node_id（字符串）转换为 UUID。

        转换失败时返回 None（调用方按新建处理更安全）。
        """
        if node_id is None:
            return None
        try:
            return UUID(str(node_id))
        except (ValueError, AttributeError, TypeError):
            logger.warning("node_id 无法转换为 UUID: %r", node_id)
            return None
