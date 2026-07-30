from dataclasses import dataclass, field
from uuid import UUID

from flask import Flask
from injector import inject
from langchain_core.documents import Document as LCDocument
from sqlalchemy import func
from langchain_core.tools import BaseTool, tool
from internal.entity.dataset_entity import RetrievalStrategy
from internal.entity.knowledge_entity import KnowledgeScope
from internal.model import KnowledgeBase, KnowledgeSegment
from pkg.sqlalchemy import SQLAlchemy
from .base_service import BaseService
from .jieba_service import JiebaService
from pydantic import BaseModel, Field
from .knowledge_vector_service import KnowledgeVectorService
from .rerank_service import RerankService
from internal.core.agent.entities.tool_policy_entity import KNOWLEDGE_RETRIEVAL_TOOL_NAME


# 分层检索的作用域优先级顺序：用户个人 → 项目 → 租户 → 系统
# 对应架构文档 11.4 的分层检索要求
_LAYERED_SCOPE_ORDER: list[str] = [
    KnowledgeScope.USER_MEMORY.value,
    KnowledgeScope.USER_CONTENT.value,
    KnowledgeScope.PROJECT.value,
    KnowledgeScope.TENANT.value,
    KnowledgeScope.SYSTEM.value,
]


@dataclass
class SearchResult:
    """分层检索结果数据结构，保留来源作用域信息（架构文档 11.4 第 4 点）"""
    content: str
    score: float
    knowledge_base_id: str
    knowledge_scope: str
    document_id: str = ""
    segment_id: str = ""
    # 透传的额外元数据，便于上游消费
    metadata: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "content": self.content,
            "score": self.score,
            "knowledge_base_id": self.knowledge_base_id,
            "knowledge_scope": self.knowledge_scope,
            "document_id": self.document_id,
            "segment_id": self.segment_id,
            "metadata": self.metadata,
        }


@inject
@dataclass
class RetrievalService(BaseService):
    """检索服务"""
    db: SQLAlchemy
    jieba_service: JiebaService
    knowledge_vector_service: KnowledgeVectorService
    rerank_service: RerankService = None

    def search_in_knowledge_base(
            self,
            knowledge_base_ids: list[UUID],
            query: str,
            account_id: UUID,
            k: int = 4,
            retrieval_strategy: str = RetrievalStrategy.HYBRID.value,
            knowledge_scope: str | None = None,
    ) -> list[LCDocument]:
        """在新版知识库（KnowledgeBase/KnowledgeSegment）中执行 RAG 检索，返回 LangChain 文档列表"""
        knowledge_bases = self.db.session.query(KnowledgeBase).filter(
            KnowledgeBase.id.in_(knowledge_base_ids),
            KnowledgeBase.enabled.is_(True),
        ).all()
        if not knowledge_bases:
            return []

        if retrieval_strategy == RetrievalStrategy.SEMANTIC.value:
            documents = self._semantic_search_knowledge_base(knowledge_bases, query, k, knowledge_scope=knowledge_scope)
        elif retrieval_strategy == RetrievalStrategy.FULL_TEXT.value:
            documents = self._full_text_search_knowledge_base(knowledge_base_ids, query, k)
        else:
            documents = self._hybrid_search_knowledge_base(knowledge_bases, knowledge_base_ids, query, k, knowledge_scope=knowledge_scope, account_id=account_id)

        segment_ids = [
            document.metadata.get("segment_id")
            for document in documents
            if document.metadata.get("segment_id")
        ]
        if segment_ids:
            with self.db.auto_commit():
                self.db.session.query(KnowledgeSegment).filter(
                    KnowledgeSegment.id.in_(segment_ids),
                ).update({
                    "hit_count": KnowledgeSegment.hit_count + 1,
                })

        return documents[:k]

    def _semantic_search_knowledge_base(
            self,
            knowledge_bases: list[KnowledgeBase],
            query: str,
            k: int,
            knowledge_scope: str | None = None,
    ) -> list[LCDocument]:
        documents: list[LCDocument] = []
        for knowledge_base in knowledge_bases:
            hits = self.knowledge_vector_service.search(knowledge_base, query, top_k=k, knowledge_scope=knowledge_scope)
            for hit in hits:
                documents.append(LCDocument(
                    page_content=hit.get("content", ""),
                    metadata={
                        "knowledge_base_id": hit.get("knowledge_base_id") or str(knowledge_base.id),
                        "knowledge_document_id": hit.get("document_id"),
                        "segment_id": hit.get("segment_id"),
                        "source": "knowledge_base",
                        "score": hit.get("score", 0),
                        "retrieval": "semantic",
                    },
                ))
        documents.sort(key=lambda d: d.metadata.get("score", 0), reverse=True)
        return documents

    def _full_text_search_knowledge_base(
            self,
            knowledge_base_ids: list[UUID],
            query: str,
            k: int,
    ) -> list[LCDocument]:
        keywords = self.jieba_service.extract_keywords(query, 10)
        if not keywords:
            return []

        segments = self.db.session.query(KnowledgeSegment).filter(
            KnowledgeSegment.knowledge_base_id.in_(knowledge_base_ids),
            KnowledgeSegment.enabled.is_(True),
            func.jsonb_exists_any(KnowledgeSegment.keywords, keywords),
        ).all()

        scored: list[tuple[int, KnowledgeSegment]] = []
        query_keyword_set = set(keywords)
        for segment in segments:
            overlap = len(set(segment.keywords or []) & query_keyword_set)
            if overlap > 0:
                scored.append((overlap, segment))

        scored.sort(key=lambda item: item[0], reverse=True)

        return [LCDocument(
            page_content=segment.content,
            metadata={
                "knowledge_base_id": str(segment.knowledge_base_id),
                "knowledge_document_id": str(segment.knowledge_document_id),
                "segment_id": str(segment.id),
                "source": "knowledge_base",
                "score": 0,
                "retrieval": "full_text",
            },
        ) for _, segment in scored[:k]]

    def _hybrid_search_knowledge_base(
            self,
            knowledge_bases: list[KnowledgeBase],
            knowledge_base_ids: list[UUID],
            query: str,
            k: int,
            knowledge_scope: str | None = None,
            account_id=None,
    ) -> list[LCDocument]:
        semantic_docs = self._semantic_search_knowledge_base(knowledge_bases, query, k, knowledge_scope=knowledge_scope)
        full_text_docs = self._full_text_search_knowledge_base(knowledge_base_ids, query, k)

        merged: list[LCDocument] = []
        seen_segment_ids: set[str] = set()
        for document in semantic_docs + full_text_docs:
            segment_id = document.metadata.get("segment_id")
            if segment_id and segment_id in seen_segment_ids:
                continue
            if segment_id:
                seen_segment_ids.add(segment_id)
            merged.append(document)

        semantic_scores = {d.metadata.get("segment_id"): d.metadata.get("score", 0) for d in semantic_docs}
        merged.sort(
            key=lambda d: (
                d.metadata.get("segment_id") in semantic_scores,
                d.metadata.get("score", 0),
            ),
            reverse=True,
        )

        rerank_service = getattr(self, "rerank_service", None)
        if rerank_service is not None:
            try:
                merged = rerank_service.rerank_documents(query, merged, top_n=k, account_id=account_id)
            except Exception:
                pass

        return merged

    def layered_search(
            self,
            account_id: UUID,
            query: str,
            knowledge_base_ids: list[UUID],
            retrieval_config: dict | None = None,
            top_k_per_layer: int | None = None,
    ) -> list[SearchResult]:
        """分层检索：将 knowledge_base_ids 按 knowledge_scope 分组为 5 层，对每层独立调用
        search_in_knowledge_base，严格按作用域隔离检索，合并结果时保留来源作用域标记。

        架构文档 11.4 要求：
        - 分层：user_memory / user_content / project / tenant / system
        - 作用域隔离：不跨作用域合并向量，用户个人库结果不混入系统级结果
        - 结果保留来源作用域，供下游 ResultSynthesizer 区分系统规则 vs 用户偏好

        :param account_id: 账户 ID（透传给 search_in_knowledge_base 用于命中统计）
        :param query: 检索 query
        :param knowledge_base_ids: 待检索的知识库 ID 列表
        :param retrieval_config: 检索配置，支持 retrieval_strategy / k
        :param top_k_per_layer: 每层取多少条；None 时使用 retrieval_config 中的 k（默认 4）
        :return: List[SearchResult]，按作用域优先级顺序合并
        """
        retrieval_config = retrieval_config or {}
        retrieval_strategy = retrieval_config.get(
            "retrieval_strategy", RetrievalStrategy.HYBRID.value
        )
        k = int(retrieval_config.get("k", 4) or 4)
        # 每层 top_k：显式传入优先；否则使用全局 k（相当于每层平均分配 top_k 的上限）
        layer_top_k = int(top_k_per_layer) if top_k_per_layer is not None else k

        # 1.查询所有启用的知识库，按 knowledge_scope 分组（严格隔离，不跨作用域合并向量）
        knowledge_bases = self.db.session.query(KnowledgeBase).filter(
            KnowledgeBase.id.in_(knowledge_base_ids),
            KnowledgeBase.enabled.is_(True),
        ).all()
        if not knowledge_bases:
            return []

        layers: dict[str, list[UUID]] = {}
        for kb in knowledge_bases:
            scope = kb.knowledge_scope or KnowledgeScope.USER_CONTENT.value
            layers.setdefault(scope, []).append(kb.id)

        # 2.按作用域优先级顺序逐层独立检索，保留来源作用域标记
        results: list[SearchResult] = []
        for scope in _LAYERED_SCOPE_ORDER:
            scope_kb_ids = layers.get(scope)
            if not scope_kb_ids:
                continue
            # 显式传入 knowledge_scope 强化隔离：向量库 metadata 过滤 + 此处分组双重保证
            documents = self.search_in_knowledge_base(
                knowledge_base_ids=scope_kb_ids,
                query=query,
                account_id=account_id,
                retrieval_strategy=retrieval_strategy,
                k=layer_top_k,
                knowledge_scope=scope,
            )
            for doc in documents:
                metadata = doc.metadata or {}
                results.append(SearchResult(
                    content=doc.page_content,
                    score=float(metadata.get("score", 0) or 0),
                    knowledge_base_id=str(metadata.get("knowledge_base_id", "") or ""),
                    knowledge_scope=scope,
                    document_id=str(metadata.get("knowledge_document_id", "") or ""),
                    segment_id=str(metadata.get("segment_id", "") or ""),
                    metadata={
                        "retrieval": metadata.get("retrieval", ""),
                        "source": metadata.get("source", "knowledge_base"),
                    },
                ))

        return results

    def create_knowledge_retrieval_tool(
            self,
            flask_app: Flask,
            knowledge_base_ids: list[UUID],
            account_id: UUID,
            retrieval_strategy: str = RetrievalStrategy.HYBRID.value,
            k: int = 4,
            top_k_per_layer: int | None = None,
    ) -> BaseTool:
        """根据传递的参数构建一个新版知识库 LangChain 检索工具

        架构文档 11.4 第 3 点要求工具返回结果中保留来源作用域信息，
        因此工具内部改为调用 layered_search 进行分层检索，并在返回
        字符串中为每条片段标注来源作用域（knowledge_scope）。
        """

        class KnowledgeRetrievalInput(BaseModel):
            """知识库检索工具接入结构"""
            query: str = Field(description="知识库搜索query语句,类型为字符串")

        @tool(KNOWLEDGE_RETRIEVAL_TOOL_NAME, args_schema=KnowledgeRetrievalInput)
        def knowledge_retrieval(query: str) -> str:
            """如果需要搜索用户知识库中的相关内容,当你觉得用户的提问超过你的知识范围时,可以尝试调用工具,输入为检索query语句,返回数据为检索内容字符串"""
            with flask_app.app_context():
                # 调用分层检索：按 knowledge_scope 分层独立检索并保留来源作用域
                search_results = self.layered_search(
                    account_id=account_id,
                    query=query,
                    knowledge_base_ids=knowledge_base_ids,
                    retrieval_config={
                        "retrieval_strategy": retrieval_strategy,
                        "k": k,
                    },
                    top_k_per_layer=top_k_per_layer,
                )

            if len(search_results) == 0:
                return "知识库内没有检索到对应内容"

            # 合并结果时显式标注来源作用域，供下游 Agent / ResultSynthesizer 区分
            # 系统规则（system/tenant）与用户偏好（user_memory/user_content）
            parts: list[str] = []
            for result in search_results:
                scope_tag = f"[来源作用域: {result.knowledge_scope}]"
                parts.append(f"{scope_tag}\n{result.content}")
            return "\n\n".join(parts)

        return knowledge_retrieval



