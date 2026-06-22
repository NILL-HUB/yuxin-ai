import logging
from dataclasses import dataclass

from injector import inject
from flask_weaviate import FlaskWeaviate
from langchain_core.documents import Document as LCDocument
from langchain_weaviate import WeaviateVectorStore
from weaviate.collections import Collection
from weaviate.classes.query import Filter

from internal.model import KnowledgeBase, KnowledgeSegment
from internal.service.embeddings_service import EmbeddingsService
from pkg.sqlalchemy import SQLAlchemy

logger = logging.getLogger(__name__)


@inject
@dataclass
class KnowledgeVectorService:
    weaviate: FlaskWeaviate
    embeddings_service: EmbeddingsService
    db: SQLAlchemy

    COLLECTION_NAME = "KnowledgeBase"

    @property
    def vector_store(self) -> WeaviateVectorStore:
        return WeaviateVectorStore(
            client=self.weaviate.client,
            index_name=self.COLLECTION_NAME,
            text_key="content",
            embedding=self.embeddings_service.cache_backed_embeddings,
        )

    @property
    def collection(self) -> Collection:
        return self.weaviate.client.collections.get(self.COLLECTION_NAME)

    def index_segment(self, segment: KnowledgeSegment, knowledge_base: KnowledgeBase) -> str:
        node_id = str(segment.id)
        lc_document = LCDocument(
            page_content=segment.content,
            metadata={
                "segment_id": str(segment.id),
                "knowledge_base_id": str(knowledge_base.id),
                "owner_account_id": str(knowledge_base.owner_account_id) if knowledge_base.owner_account_id else "",
                "knowledge_scope": knowledge_base.knowledge_scope,
                "document_id": str(segment.knowledge_document_id),
                "document_enabled": True,
                "segment_enabled": bool(segment.enabled),
            },
        )
        self.vector_store.add_documents(documents=[lc_document], ids=[node_id])
        return node_id

    def remove_segment(self, segment: KnowledgeSegment) -> None:
        self._delete_node_id(str(segment.id))

    def search(self, knowledge_base: KnowledgeBase, query: str, top_k: int = 5) -> list[dict]:
        search_result = self.vector_store.similarity_search_with_relevance_scores(
            query=query,
            k=top_k,
            filters=Filter.all_of([
                Filter.by_property("knowledge_base_id").equal(str(knowledge_base.id)),
                Filter.by_property("document_enabled").equal(True),
                Filter.by_property("segment_enabled").equal(True),
            ]),
        )
        results: list[dict] = []
        for doc, score in search_result or []:
            results.append({
                "content": doc.page_content,
                "score": score,
                "segment_id": doc.metadata.get("segment_id"),
                "document_id": doc.metadata.get("document_id"),
                "knowledge_base_id": doc.metadata.get("knowledge_base_id"),
            })
        return results

    def _delete_node_id(self, node_id: str) -> None:
        try:
            self.collection.data.delete_by_id(node_id)
        except Exception:
            logger.warning("删除知识库向量节点失败 node_id=%s", node_id, exc_info=True)
