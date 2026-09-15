"""视觉编码服务（Qwen3-VL-Embedding，硅基流动）。

**为什么独立于 EmbeddingsService**：
该模型的 embeddings 接口入参与 OpenAI 不兼容——文本传裸字符串，
图片传 {"image": ...}，图文混合传对象数组。用 langchain 的
OpenAIEmbeddings 只能表达文本形态，会静默只编码文本，
导致「以图搜图」拿到的其实是文本向量，结果完全错误。

**为什么能跨模态检索**：
Qwen3-VL-Embedding 把文本、图片、视频映射到**同一语义空间**，
因此文本 query 可直接与库内图片向量比对余弦相似度，
不需要设计稿最初假设的「两个独立空间 + 融合排序」。
"""
import logging
from dataclasses import dataclass
from uuid import UUID

import requests
from injector import inject
from sqlalchemy import text

from internal.model.video_visual_embedding import VISUAL_EMBEDDING_DIMENSION
from pkg.sqlalchemy import SQLAlchemy
from .base_service import BaseService
from .language_model_service import LanguageModelService

logger = logging.getLogger(__name__)

# 视觉编码请求超时（秒）
_REQUEST_TIMEOUT = 30
# 视觉编码模型类型标识，与模型池 model_type 对齐
VISUAL_MODEL_TYPE = "visual_embedding"


@inject
@dataclass
class VisualEmbeddingService(BaseService):
    """关键帧/图片的视觉向量编码与检索。"""

    db: SQLAlchemy

    def _credentials(self) -> dict:
        """从模型池取视觉编码模型凭证（复用既有 provider 凭证链路）。"""
        return LanguageModelService.get_provider_credentials(model_type=VISUAL_MODEL_TYPE) or {}

    def _post(self, url, json, headers, timeout):
        """HTTP POST（独立方法便于测试替换）。"""
        return requests.post(url, json=json, headers=headers, timeout=timeout)

    def _request_embedding(self, payload_input) -> list[float]:
        """调用 embeddings 接口并校验维度；任何异常都返回空列表而非抛出。

        空列表表示「本次编码失败」，调用方据此跳过该帧，
        不得写入错误向量破坏索引一致性。
        """
        creds = self._credentials()
        api_key = str(creds.get("api_key") or "")
        base_url = str(creds.get("base_url") or "").rstrip("/")
        model = str(creds.get("model") or "")
        if not api_key or not base_url or not model:
            logger.warning("视觉编码模型未配置（缺少 api_key/base_url/model）")
            return []

        try:
            response = self._post(
                f"{base_url}/embeddings",
                json={
                    "model": model,
                    "input": payload_input,
                    "dimensions": VISUAL_EMBEDDING_DIMENSION,
                },
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                },
                timeout=_REQUEST_TIMEOUT,
            )
            response.raise_for_status()
            data = (response.json() or {}).get("data") or []
            if not data:
                logger.warning("视觉编码返回空数据")
                return []
            vector = [float(item) for item in (data[0].get("embedding") or [])]
        except Exception:
            logger.warning("视觉编码请求失败", exc_info=True)
            return []

        if len(vector) != VISUAL_EMBEDDING_DIMENSION:
            logger.warning(
                "视觉编码维度不符：期望 %s 实际 %s", VISUAL_EMBEDDING_DIMENSION, len(vector)
            )
            return []
        return vector

    def embed_text(self, content: str) -> list[float]:
        """文本编码（与图片共享语义空间，可直接跨模态比对）。"""
        return self._request_embedding(content)

    def embed_image(self, data_uri: str) -> list[float]:
        """图片编码。入参用 {"image": ...} 对象，而非 OpenAI 的裸字符串。"""
        return self._request_embedding({"image": data_uri})

    def embed_mixed(self, text_content: str, data_uri: str) -> list[float]:
        """图文混合编码（融合为一个向量）。"""
        return self._request_embedding([{"text": text_content}, {"image": data_uri}])

    def _fetch_rows(
        self,
        *,
        knowledge_base_id: UUID,
        limit: int = 500,
        document_ids: list[UUID] | None = None,
        partition_id: UUID | None = None,
        media_types: list[str] | None = None,
    ) -> list[dict]:
        """读取库内视觉向量（独立方法便于测试替换）。

        结构化过滤在 SQL 侧下推，与文本检索保持同一套过滤语义——
        视觉召回是补充通道，**不得绕过**分区/媒体类型/素材范围约束。
        """
        sql = [
            "SELECT v.segment_id, v.knowledge_document_id, v.frame_url, v.scene_index,",
            "       v.embedding, COALESCE(s.content, '') AS content",
            "FROM video_visual_embedding v",
            "JOIN knowledge_document d ON d.id = v.knowledge_document_id",
            "LEFT JOIN knowledge_segment s ON s.id = v.segment_id",
            "WHERE v.knowledge_base_id = CAST(:kb_id AS uuid)",
        ]
        params: dict = {"kb_id": str(knowledge_base_id), "limit": limit}
        if document_ids:
            sql.append("AND v.knowledge_document_id = ANY(CAST(:document_ids AS uuid[]))")
            params["document_ids"] = [str(doc_id) for doc_id in document_ids]
        if partition_id is not None:
            sql.append("AND d.partition_id = CAST(:partition_id AS uuid)")
            params["partition_id"] = str(partition_id)
        if media_types:
            sql.append("AND d.media_type = ANY(CAST(:media_types AS text[]))")
            params["media_types"] = list(media_types)
        sql.append("ORDER BY v.scene_index LIMIT :limit")

        result = self.db.session.execute(text(" ".join(sql)), params)
        return [
            {
                "segment_id": str(row.segment_id),
                "knowledge_document_id": str(row.knowledge_document_id),
                "frame_url": row.frame_url,
                "scene_index": row.scene_index,
                "content": row.content or "",
                "embedding": list(row.embedding),
            }
            for row in result
        ]

    def has_vectors(self, knowledge_base_ids: list[UUID]) -> bool:
        """预检这些库内是否存在视觉向量。

        供检索链路决定**是否值得发起编码调用**：视觉编码按次计费，
        库内没有帧时白跑一次 HTTP 纯属浪费。
        """
        kb_ids = [str(kb_id) for kb_id in knowledge_base_ids]
        if not kb_ids:
            return False
        row = self.db.session.execute(
            text("""
                SELECT 1 FROM video_visual_embedding
                WHERE knowledge_base_id = ANY(CAST(:kb_ids AS uuid[]))
                LIMIT 1
            """),
            {"kb_ids": kb_ids},
        ).first()
        return row is not None

    def search_by_image(
        self, *, image_uri: str, knowledge_base_id: UUID, limit: int = 10,
        document_ids: list[UUID] | None = None,
        partition_id: UUID | None = None,
        media_types: list[str] | None = None,
    ) -> list[dict]:
        """以图搜图：库内视觉向量按余弦相似度排序。"""
        query_vector = self.embed_image(image_uri)
        if not query_vector:
            return []
        return self._rank(
            query_vector, knowledge_base_id, limit,
            document_ids=document_ids, partition_id=partition_id, media_types=media_types,
        )

    def search_by_text(
        self, *, query: str, knowledge_base_id: UUID, limit: int = 10,
        document_ids: list[UUID] | None = None,
        partition_id: UUID | None = None,
        media_types: list[str] | None = None,
    ) -> list[dict]:
        """跨模态文本召回：文本与图片在同一语义空间，可直接比对。"""
        query_vector = self.embed_text(query)
        if not query_vector:
            return []
        return self._rank(
            query_vector, knowledge_base_id, limit,
            document_ids=document_ids, partition_id=partition_id, media_types=media_types,
        )

    def _rank(
        self, query_vector: list[float], knowledge_base_id: UUID, limit: int,
        document_ids: list[UUID] | None = None,
        partition_id: UUID | None = None,
        media_types: list[str] | None = None,
    ) -> list[dict]:
        """按余弦相似度降序返回 top-N。

        向量规模可控（每视频数帧），在 Python 侧计算即可；
        若单库帧数显著增长，可改为 SQL 侧 pgvector 查询（表已建 HNSW 索引）。
        """
        rows = self._fetch_rows(
            knowledge_base_id=knowledge_base_id,
            document_ids=document_ids,
            partition_id=partition_id,
            media_types=media_types,
        )
        scored = [
            {
                "segment_id": row["segment_id"],
                "frame_url": row["frame_url"],
                "scene_index": row.get("scene_index", 0),
                "score": _cosine_similarity(query_vector, row["embedding"]),
            }
            for row in rows
        ]
        scored.sort(key=lambda item: item["score"], reverse=True)
        return scored[:limit]

    def index_frame(
        self,
        *,
        knowledge_base_id: UUID,
        knowledge_document_id: UUID,
        segment_id: UUID,
        account_id: UUID,
        frame_url: str,
        scene_index: int = 0,
        embedding: list[float],
        model_id: str | None = None,
    ) -> str:
        """写入（或覆盖）一条帧视觉向量。

        以 segment_id 为冲突键 upsert：重解析时同一片段覆盖旧向量，不累积重复行。
        """
        self.db.session.execute(
            text("""
                INSERT INTO video_visual_embedding
                    (account_id, knowledge_base_id, knowledge_document_id, segment_id,
                     frame_url, scene_index, model_id, embedding)
                VALUES (:account_id, :kb_id, :doc_id, :segment_id,
                        :frame_url, :scene_index, :model_id, CAST(:embedding AS vector))
                ON CONFLICT (segment_id) DO UPDATE SET
                    frame_url = EXCLUDED.frame_url,
                    scene_index = EXCLUDED.scene_index,
                    model_id = EXCLUDED.model_id,
                    embedding = EXCLUDED.embedding,
                    updated_at = CURRENT_TIMESTAMP(0)
            """),
            {
                "account_id": str(account_id),
                "kb_id": str(knowledge_base_id),
                "doc_id": str(knowledge_document_id),
                "segment_id": str(segment_id),
                "frame_url": frame_url,
                "scene_index": int(scene_index or 0),
                "model_id": str(model_id) if model_id else None,
                "embedding": embedding,
            },
        )
        self.db.session.commit()
        return str(segment_id)

    def delete_by_document(self, knowledge_document_id: UUID) -> None:
        """清空某素材的全部视觉向量（重解析前调用，保证幂等）。"""
        self.db.session.execute(
            text("DELETE FROM video_visual_embedding WHERE knowledge_document_id = :doc_id"),
            {"doc_id": str(knowledge_document_id)},
        )
        self.db.session.commit()


def _cosine_similarity(left: list[float], right: list[float]) -> float:
    """余弦相似度；维度不符或存在零向量时返回 0，避免除零与错配比较。"""
    if not left or not right or len(left) != len(right):
        return 0.0
    dot = sum(a * b for a, b in zip(left, right))
    norm_left = sum(a * a for a in left) ** 0.5
    norm_right = sum(b * b for b in right) ** 0.5
    if norm_left == 0 or norm_right == 0:
        return 0.0
    return dot / (norm_left * norm_right)
