import uuid
import logging
from dataclasses import dataclass

from injector import inject
from flask_weaviate import FlaskWeaviate
from langchain_core.documents import Document as LCDocument
from langchain_weaviate import WeaviateVectorStore
from weaviate.collections import Collection
from weaviate.classes.query import Filter

from internal.model import Account, UserMemory
from internal.service.embeddings_service import EmbeddingsService
from internal.service.rerank_service import RerankService
from pkg.sqlalchemy import SQLAlchemy

logger = logging.getLogger(__name__)


@inject
@dataclass
class MemoryVectorService:
    weaviate: FlaskWeaviate
    embeddings_service: EmbeddingsService
    db: SQLAlchemy
    rerank_service: RerankService = None

    COLLECTION_NAME = "UserMemory"

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

    def index_memory(self, memory: UserMemory) -> str:
        if memory.embedding_node_id:
            self._delete_node_id(memory.embedding_node_id)
        node_id = str(uuid.uuid4())
        lc_document = LCDocument(
            page_content=memory.content,
            metadata={
                "memory_id": str(memory.id),
                "memory_type": memory.memory_type,
                "owner_account_id": str(memory.owner_account_id),
            },
        )
        self.vector_store.add_documents(documents=[lc_document], ids=[node_id])
        memory.embedding_node_id = node_id
        self.db.session.commit()
        return node_id

    def remove_memory(self, memory: UserMemory) -> None:
        if not memory.embedding_node_id:
            return
        self._delete_node_id(memory.embedding_node_id)

    def search_relevant_memories(
        self, account: Account, query: str, top_k: int = 5
    ) -> list[dict]:
        search_result = self.vector_store.similarity_search_with_relevance_scores(
            query=query,
            k=top_k,
            filters=Filter.by_property("owner_account_id").equal(str(account.id)),
        )
        results: list[dict] = []
        for doc, score in search_result or []:
            results.append({
                "content": doc.page_content,
                "score": score,
                "memory_id": doc.metadata.get("memory_id"),
                "memory_type": doc.metadata.get("memory_type"),
            })
        rerank_service = getattr(self, "rerank_service", None)
        if rerank_service is not None:
            try:
                results = rerank_service.rerank(query, results, top_n=top_k)
            except Exception:
                logger.warning("用户记忆检索 rerank 失败，返回原始检索结果", exc_info=True)
        return results

    def _delete_node_id(self, node_id: str) -> None:
        try:
            self.collection.data.delete_by_id(node_id)
        except Exception:
            logger.warning("删除向量节点失败 node_id=%s", node_id, exc_info=True)
