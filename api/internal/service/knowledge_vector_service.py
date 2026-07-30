"""知识库向量服务（pgvector 实现，按维度分表存储）

使用 PostgreSQL 18 + pgvector 扩展，向量存储于 knowledge_segment_embedding_{dim} 表，
HNSW 索引加速检索。利用 SQL JOIN 实现 knowledge_scope 权限过滤与原表元数据获取。

按维度分表设计：
    - 每个知识库可绑定 embedding 模型（knowledge_base.embedding_model_id）
    - 不同 embedding 模型维度不同（1024/1536/3072/4096 等）
    - 向量按维度存储到 knowledge_segment_embedding_{dim} 表
    - 原 knowledge_segment 表保留元数据，embedding 列逐步废弃
"""

import logging
from dataclasses import dataclass

from injector import inject
from sqlalchemy import text

from internal.model import KnowledgeBase, KnowledgeSegment
from internal.service.embedding_table_router import EmbeddingTableRouter
from internal.service.embeddings_service import EmbeddingsService
from internal.service.rerank_service import RerankService
from pkg.sqlalchemy import SQLAlchemy

logger = logging.getLogger(__name__)


@inject
@dataclass
class KnowledgeVectorService:
    """知识库向量服务（pgvector，按维度分表）"""
    embeddings_service: EmbeddingsService
    db: SQLAlchemy
    rerank_service: RerankService = None

    def _get_router(self) -> EmbeddingTableRouter:
        """获取 EmbeddingTableRouter 单例"""
        return EmbeddingTableRouter.get_instance()

    def _resolve_kb_embedding(self, knowledge_base: KnowledgeBase) -> tuple[list, int, str]:
        """解析知识库的 embedding 模型配置。

        Returns:
            (embeddings_client, dimension, table_name)
        """
        model_id = getattr(knowledge_base, "embedding_model_id", None)
        embeddings_client, dimension = self.embeddings_service.get_embeddings_for_model_id(model_id)
        # 确保维度表已创建
        router = self._get_router()
        router.ensure_tables_for_dimension(dimension)
        table_name = router.get_knowledge_segment_table_name(dimension)
        return embeddings_client, dimension, table_name

    def index_segment(self, segment: KnowledgeSegment, knowledge_base: KnowledgeBase) -> str:
        """为知识库片段构建向量索引并写入维度分表"""
        node_id = str(segment.id)
        try:
            embeddings_client, dimension, table_name = self._resolve_kb_embedding(knowledge_base)
            embedding = embeddings_client.embed_query(segment.content)

            # 写入维度分表（segment_id + knowledge_base_id + embedding）
            self.db.session.execute(
                text(f"""
                    INSERT INTO {table_name} (segment_id, knowledge_base_id, embedding)
                    VALUES (:segment_id, :kb_id, :embedding)
                    ON CONFLICT (segment_id) DO UPDATE SET
                        embedding = EXCLUDED.embedding,
                        updated_at = CURRENT_TIMESTAMP(0)
                """),
                {
                    "segment_id": str(segment.id),
                    "kb_id": str(knowledge_base.id),
                    "embedding": embedding,
                },
            )
            self.db.session.commit()
        except Exception:
            logger.warning("知识库片段向量写入失败 segment_id=%s", node_id, exc_info=True)
            self.db.session.rollback()
        return node_id

    def remove_segment(self, segment: KnowledgeSegment) -> None:
        """删除知识库片段的向量（从所有可能的维度表中删除）"""
        # 由于不知道该 segment 存储在哪个维度表，需要从知识库的 embedding_model_id 推断
        try:
            knowledge_base = segment.knowledge_base
            if knowledge_base is None:
                logger.warning("remove_segment: segment 无关联知识库 segment_id=%s", segment.id)
                return
            _, dimension, table_name = self._resolve_kb_embedding(knowledge_base)
            self.db.session.execute(
                text(f"DELETE FROM {table_name} WHERE segment_id = :segment_id"),
                {"segment_id": str(segment.id)},
            )
            self.db.session.commit()
        except Exception:
            logger.warning("删除知识库向量失败 segment_id=%s", segment.id, exc_info=True)
            self.db.session.rollback()

    def search(
        self,
        knowledge_base: KnowledgeBase,
        query: str,
        top_k: int = 5,
        knowledge_scope: str | None = None,
    ) -> list[dict]:
        """在指定知识库中执行向量相似度检索（按维度分表）

        利用 pgvector 的 HNSW 索引 + SQL JOIN 实现：
        - knowledge_base_id 过滤
        - knowledge_scope 权限隔离（通过 JOIN knowledge_base 表）
        - document_enabled / segment_enabled 过滤
        - 元数据从原表 JOIN 获取
        """
        try:
            embeddings_client, dimension, table_name = self._resolve_kb_embedding(knowledge_base)
            query_embedding = embeddings_client.embed_query(query)
        except Exception:
            logger.warning("查询向量生成失败 query=%s", query[:100], exc_info=True)
            return []

        # 构建 SQL：从维度分表检索 + JOIN 原表获取元数据
        # pgvector 的 <=> 操作符为余弦距离，1 - distance = similarity
        sql = f"""
            SELECT ks.id AS segment_id,
                   ks.content,
                   ks.knowledge_document_id,
                   1 - (v.embedding <=> :embedding) AS score
            FROM {table_name} v
            JOIN knowledge_segment ks ON v.segment_id = ks.id
            JOIN knowledge_base kb ON ks.knowledge_base_id = kb.id
            JOIN knowledge_document kd ON ks.knowledge_document_id = kd.id
            WHERE v.knowledge_base_id = :kb_id
              AND ks.enabled = true
              AND kb.enabled = true
              AND kd.enabled = true
        """
        params: dict = {
            "kb_id": str(knowledge_base.id),
            "embedding": query_embedding,
        }
        if knowledge_scope is not None:
            sql += " AND kb.knowledge_scope = :scope"
            params["scope"] = knowledge_scope

        sql += " ORDER BY v.embedding <=> :embedding LIMIT :limit"
        params["limit"] = top_k

        try:
            result = self.db.session.execute(text(sql), params)
            results: list[dict] = []
            for row in result:
                results.append({
                    "content": row.content,
                    "score": float(row.score),
                    "segment_id": str(row.segment_id),
                    "document_id": str(row.knowledge_document_id),
                    "knowledge_base_id": str(knowledge_base.id),
                })
        except Exception:
            logger.warning("知识库向量检索失败 kb_id=%s", knowledge_base.id, exc_info=True)
            return []

        rerank_service = getattr(self, "rerank_service", None)
        if rerank_service is not None:
            try:
                results = rerank_service.rerank(query, results, top_n=top_k)
            except Exception:
                logger.warning("知识库检索 rerank 失败，返回原始检索结果", exc_info=True)
        return results
