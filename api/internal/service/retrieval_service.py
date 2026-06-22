from dataclasses import dataclass
from uuid import UUID

from flask import Flask
from injector import inject
from langchain_classic.retrievers.ensemble import EnsembleRetriever
from langchain_core.documents import Document as LCDocument
from sqlalchemy import func, update
from langchain_core.tools import BaseTool, tool
from internal.entity.dataset_entity import RetrievalStrategy, RetrievalSource
from internal.exception import NotFoundException
from internal.lib.helper import combine_documents
from internal.model import Dataset, DatasetQuery, KnowledgeBase, KnowledgeSegment, Segment
from pkg.sqlalchemy import SQLAlchemy
from .base_service import BaseService
from .jieba_service import JiebaService
from pydantic import BaseModel, Field
from .vector_database_service import VectorDatabaseService
from .knowledge_vector_service import KnowledgeVectorService
from .rerank_service import RerankService
from internal.core.agent.entities.agent_entity import DATASET_RETRIEVAL_TOOL_NAME
from internal.core.agent.entities.tool_policy_entity import KNOWLEDGE_RETRIEVAL_TOOL_NAME


@inject
@dataclass
class RetrievalService(BaseService):
    """检索服务"""
    db: SQLAlchemy
    jieba_service: JiebaService
    vector_database_service: VectorDatabaseService
    knowledge_vector_service: KnowledgeVectorService
    rerank_service: RerankService = None

    def search_in_datasets(
            self,
            dataset_ids: list[UUID],
            query: str,
            account_id: UUID,
            retrieval_strategy: str = RetrievalStrategy.SEMANTIC.value,
            k: int = 4,
            score: float = 0,
            retrieval_source: str = RetrievalSource.HIT_TESTING.value,
    ) -> list[LCDocument]:
        """根据传递的query+知识库列表执行检索，并返回检索的文档+得分数据（如果检索策略为全文检索，则得分为0）"""
        # 1.提取知识库列表并校验权限同时更新知识库id
        datasets = self.db.session.query(Dataset).filter(
            Dataset.id.in_(dataset_ids),
            Dataset.account_id == account_id,
        ).all()
        if datasets is None or len(datasets) == 0:
            raise NotFoundException("当前无知识库可执行检索")
        dataset_ids = [dataset.id for dataset in datasets]

        # 2.构建不同种类的检索器
        from internal.core.retrievers import SemanticRetriever, FullTextRetriever
        semantic_retriever = SemanticRetriever(
            dataset_ids=dataset_ids,
            vector_store=self.vector_database_service.vector_store,
            search_kwargs={
                "k": k,
                "score_threshold": score,
            },
            rerank_service=getattr(self, "rerank_service", None),
        )
        full_text_retriever = FullTextRetriever(
            db=self.db,
            dataset_ids=dataset_ids,
            jieba_service=self.jieba_service,
            search_kwargs={
                "k": k
            },
        )
        hybrid_retriever = EnsembleRetriever(
            retrievers=[semantic_retriever, full_text_retriever],
            weights=[0.5, 0.5],
        )

        # 3.根据不同的检索策略执行检索
        if retrieval_strategy == RetrievalStrategy.SEMANTIC.value:
            lc_documents = semantic_retriever.invoke(query)[:k]
        elif retrieval_strategy == RetrievalStrategy.FULL_TEXT.value:
            lc_documents = full_text_retriever.invoke(query)[:k]
        else:
            lc_documents = hybrid_retriever.invoke(query)[:k]

        # 4.添加知识库查询记录（只存储唯一记录，也就是一个知识库如果检索了多篇文档，也只存储一条）
        unique_dataset_ids = list(set(str(lc_document.metadata["dataset_id"]) for lc_document in lc_documents))
        for dataset_id in unique_dataset_ids:
            self.create(
                DatasetQuery,
                dataset_id=dataset_id,
                query=query,
                source=retrieval_source,
                # todo:等待APP配置模块完成后进行调整
                source_app_id=None,
                created_by=account_id,
            )

        # 5.批量更新片段的命中次数，召回次数，涵盖了构建+执行语句
        with self.db.auto_commit():
            stmt = (
                update(Segment)
                .where(Segment.id.in_([lc_document.metadata["segment_id"] for lc_document in lc_documents]))
                .values(hit_count=Segment.hit_count + 1)
            )
            self.db.session.execute(stmt)

        return lc_documents

    def search_in_knowledge_base(
            self,
            knowledge_base_ids: list[UUID],
            query: str,
            account_id: UUID,
            k: int = 4,
            retrieval_strategy: str = RetrievalStrategy.HYBRID.value,
    ) -> list[LCDocument]:
        """在新版知识库（KnowledgeBase/KnowledgeSegment）中执行 RAG 检索，返回 LangChain 文档列表"""
        knowledge_bases = self.db.session.query(KnowledgeBase).filter(
            KnowledgeBase.id.in_(knowledge_base_ids),
            KnowledgeBase.enabled.is_(True),
        ).all()
        if not knowledge_bases:
            return []

        if retrieval_strategy == RetrievalStrategy.SEMANTIC.value:
            documents = self._semantic_search_knowledge_base(knowledge_bases, query, k)
        elif retrieval_strategy == RetrievalStrategy.FULL_TEXT.value:
            documents = self._full_text_search_knowledge_base(knowledge_base_ids, query, k)
        else:
            documents = self._hybrid_search_knowledge_base(knowledge_bases, knowledge_base_ids, query, k)

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
    ) -> list[LCDocument]:
        documents: list[LCDocument] = []
        for knowledge_base in knowledge_bases:
            hits = self.knowledge_vector_service.search(knowledge_base, query, top_k=k)
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
    ) -> list[LCDocument]:
        semantic_docs = self._semantic_search_knowledge_base(knowledge_bases, query, k)
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
                merged = rerank_service.rerank_documents(query, merged, top_n=k)
            except Exception:
                pass

        return merged

    def create_langchain_tool_from_search(
            self,
            flask_app: Flask,
            dataset_ids: list[UUID],
            account_id: UUID,
            retrieval_strategy: str = RetrievalStrategy.SEMANTIC.value,
            k: int = 4,
            score: float = 0,
            retrieval_source: str = RetrievalSource.HIT_TESTING.value,
    ) -> BaseTool:
        """根据传递的参数构建一个LangChain知识库检索工具"""

        class DatasetRetrivalInput(BaseModel):
            """知识库检索工具接入结构"""
            query: str = Field(description="知识库搜索query语句,类型为字符串")

        @tool(DATASET_RETRIEVAL_TOOL_NAME, args_schema=DatasetRetrivalInput)
        def dataset_retrieval(query: str) -> str:
            """如果需要搜索扩展的知识库内容,当你觉得用户的提问超过你的知识范围时,可以尝试调用工具,输入为检索query语句,返回数据为检索内容字符串"""
            # 1.调用search_in_datasets检索得到LangChain文档列表
            with flask_app.app_context():
                documents = self.search_in_datasets(
                    dataset_ids=dataset_ids,
                    query=query,
                    account_id=account_id,
                    retrieval_strategy=retrieval_strategy,
                    k=k,
                    score=score,
                    retrieval_source=retrieval_source,
                )

            # 2.将LangChain文档列表转换成字符串后返回
            if len(documents) == 0:
                return "知识库内没有检索到对应内容"
            return combine_documents(documents)

        return dataset_retrieval

    def create_knowledge_retrieval_tool(
            self,
            flask_app: Flask,
            knowledge_base_ids: list[UUID],
            account_id: UUID,
            retrieval_strategy: str = RetrievalStrategy.HYBRID.value,
            k: int = 4,
    ) -> BaseTool:
        """根据传递的参数构建一个新版知识库 LangChain 检索工具"""

        class KnowledgeRetrievalInput(BaseModel):
            """知识库检索工具接入结构"""
            query: str = Field(description="知识库搜索query语句,类型为字符串")

        @tool(KNOWLEDGE_RETRIEVAL_TOOL_NAME, args_schema=KnowledgeRetrievalInput)
        def knowledge_retrieval(query: str) -> str:
            """如果需要搜索用户知识库中的相关内容,当你觉得用户的提问超过你的知识范围时,可以尝试调用工具,输入为检索query语句,返回数据为检索内容字符串"""
            with flask_app.app_context():
                documents = self.search_in_knowledge_base(
                    knowledge_base_ids=knowledge_base_ids,
                    query=query,
                    account_id=account_id,
                    retrieval_strategy=retrieval_strategy,
                    k=k,
                )

            if len(documents) == 0:
                return "知识库内没有检索到对应内容"
            return combine_documents(documents)

        return knowledge_retrieval



