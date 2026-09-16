import logging
from dataclasses import dataclass, field
from typing import Any
from uuid import UUID

from injector import inject
from langchain_core.documents import Document as LCDocument
from sqlalchemy import func
from langchain_core.tools import BaseTool, tool
from internal.entity.dataset_entity import DocumentStatus, RetrievalStrategy
from internal.entity.knowledge_entity import DocumentMediaType, KnowledgeScope
from internal.model import KnowledgeBase, KnowledgeSegment
from pkg.sqlalchemy import SQLAlchemy
from .base_service import BaseService
from .jieba_service import JiebaService
from pydantic import BaseModel, Field
from .knowledge_tag_service import KnowledgeTagService
from .knowledge_vector_service import KnowledgeVectorService
from .rerank_service import RerankService
from .visual_embedding_service import VisualEmbeddingService
from internal.core.agent.entities.tool_policy_entity import KNOWLEDGE_RETRIEVAL_TOOL_NAME
from internal.lib.runtime_context import app_session_scope


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


@dataclass
class RetrievalFilter:
    """检索过滤条件（结构化）。

    标签会在服务层解析为 document_ids 后与结构化条件合并下推；
    分区/媒体类型同样先解析出受限素材 id，保证**所有检索分支**受同一约束，
    避免某一分支绕过过滤。
    """

    partition_id: UUID | None = None
    media_types: list[str] | None = None
    tag_ids: list[UUID] | None = None
    match_all_tags: bool = False
    score_threshold: float | None = None

    def structured_only(self) -> bool:
        """是否只含可直接下推的结构化条件（不含标签）。"""
        return not self.tag_ids


@inject
@dataclass
class RetrievalService(BaseService):
    """检索服务"""
    db: SQLAlchemy
    jieba_service: JiebaService
    knowledge_vector_service: KnowledgeVectorService
    rerank_service: RerankService = None
    # 标签过滤依赖；必须用具体类型标注（injector 不支持 Any 注入）
    knowledge_tag_service: KnowledgeTagService = None
    # 视觉向量召回（补充通道）；同样必须是具体类型
    visual_embedding_service: VisualEmbeddingService = None

    def _resolve_tag_document_ids(self, retrieval_filter: RetrievalFilter) -> list[UUID] | None:
        """解析标签过滤对应的素材 id。

        必须用 `is None` 而非真假值判断：`tag_ids == []` 表示「有标签过滤但一个都没匹配上」，
        属于 fail closed 情形；若写成 `if not tag_ids` 会让空列表退化成「无标签过滤」，
        静默召回全库——这是最危险的失效模式。

        Returns:
            None 表示未使用标签过滤；[] 表示无任何素材命中（调用方须直接返回空）。
        """
        if retrieval_filter.tag_ids is None:
            return None
        service = getattr(self, "knowledge_tag_service", None)
        if service is None:
            return []
        return list(
            service.document_ids_for_tags(
                retrieval_filter.tag_ids, match_all=retrieval_filter.match_all_tags
            )
        )

    def _resolve_structural_document_ids(self, retrieval_filter: RetrievalFilter) -> list[UUID] | None:
        """把分区/媒体类型过滤解析为素材 id，供全文分支使用。

        向量分支无需此步（分区与媒体类型已下推进向量 SQL，命中 HNSW 索引），
        但全文检索作用于 knowledge_segment，必须显式限定素材范围。

        Returns:
            None 表示无结构化过滤；[] 表示无素材命中（调用方须直接返回空）。
        """
        if retrieval_filter.partition_id is None and not retrieval_filter.media_types:
            return None

        from internal.model import KnowledgeDocument

        query = self.db.session.query(KnowledgeDocument).filter(
            KnowledgeDocument.status == DocumentStatus.COMPLETED.value,
        )
        if retrieval_filter.partition_id is not None:
            query = query.filter(KnowledgeDocument.partition_id == retrieval_filter.partition_id)
        if retrieval_filter.media_types:
            query = query.filter(KnowledgeDocument.media_type.in_(retrieval_filter.media_types))
        return [row.id for row in query.all()]

    def _restricted_document_ids_for_full_text(
        self, retrieval_filter: RetrievalFilter, tag_document_ids: list[UUID] | None
    ) -> list[UUID] | None:
        """为全文分支求「标签 ∩ 结构化」的受限素材范围。

        Returns:
            None 表示全文分支不受限；[] 表示无命中（调用方须直接返回空）。
        """
        structural = self._resolve_structural_document_ids(retrieval_filter)
        if structural == []:
            return []
        if tag_document_ids is None:
            return structural
        if structural is None:
            return tag_document_ids
        overlap = set(tag_document_ids) & set(structural)
        return list(overlap)

    def search_in_knowledge_base(
            self,
            knowledge_base_ids: list[UUID],
            query: str,
            account_id: UUID,
            k: int = 4,
            retrieval_strategy: str = RetrievalStrategy.HYBRID.value,
            knowledge_scope: str | None = None,
            retrieval_filter: RetrievalFilter | None = None,
    ) -> list[LCDocument]:
        """在新版知识库（KnowledgeBase/KnowledgeSegment）中执行 RAG 检索，返回 LangChain 文档列表

        retrieval_filter 的分区/媒体类型直接下推进向量 SQL；标签与全文分支所需的
        素材范围在服务层解析。**所有分支共享同一过滤语义**，任一分支都不得绕过。
        """
        knowledge_bases = self.db.session.query(KnowledgeBase).filter(
            KnowledgeBase.id.in_(knowledge_base_ids),
            KnowledgeBase.enabled.is_(True),
        ).all()
        if not knowledge_bases:
            return []

        vector_kwargs: dict = {}
        restricted_document_ids: list[UUID] | None = None
        # 标签收敛出的素材范围：视觉补充召回必须复用同一范围，否则等于绕过标签过滤
        tag_document_ids: list[UUID] | None = None
        if retrieval_filter is not None:
            tag_document_ids = self._resolve_tag_document_ids(retrieval_filter)
            # 标签无命中：直接返回空，**不得**退化为不过滤
            if tag_document_ids == []:
                return []

            if retrieval_filter.partition_id is not None:
                vector_kwargs["partition_id"] = retrieval_filter.partition_id
            if retrieval_filter.media_types:
                vector_kwargs["media_types"] = list(retrieval_filter.media_types)
            if retrieval_filter.score_threshold is not None:
                vector_kwargs["score_threshold"] = float(retrieval_filter.score_threshold)
            if tag_document_ids:
                vector_kwargs["document_ids"] = tag_document_ids

            if retrieval_strategy != RetrievalStrategy.SEMANTIC.value:
                restricted_document_ids = self._restricted_document_ids_for_full_text(
                    retrieval_filter, tag_document_ids
                )
                if restricted_document_ids == []:
                    return []
                self._last_restricted_document_ids = restricted_document_ids

        if retrieval_strategy == RetrievalStrategy.SEMANTIC.value:
            documents = self._semantic_search_knowledge_base(
                knowledge_bases, query, k, knowledge_scope=knowledge_scope, **vector_kwargs
            )
        elif retrieval_strategy == RetrievalStrategy.FULL_TEXT.value:
            documents = self._full_text_search_knowledge_base(
                knowledge_base_ids, query, k, document_ids=restricted_document_ids
            )
        else:
            documents = self._hybrid_search_knowledge_base(
                knowledge_bases, knowledge_base_ids, query, k,
                knowledge_scope=knowledge_scope, account_id=account_id,
                restricted_document_ids=restricted_document_ids,
                vector_kwargs=vector_kwargs,
            )

        # 视觉向量补充召回：仅在语义/混合策略下并行补充（全文是关键词路径，不引入编码调用）
        if retrieval_strategy != RetrievalStrategy.FULL_TEXT.value:
            visual_documents = self._visual_recall_knowledge_base(
                knowledge_bases, query, k, retrieval_filter, tag_document_ids,
            )
            documents = self._merge_visual_documents(documents, visual_documents, k)

        # 阈值过滤放在合并之后：视觉命中同样是带真实分数的语义结果，
        # 若只滤文本分支，低分帧会绕过用户设定的相似度下限。
        documents = self._apply_score_threshold(documents, retrieval_filter)

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

    @staticmethod
    def _apply_score_threshold(
        documents: list[LCDocument], retrieval_filter: RetrievalFilter | None
    ) -> list[LCDocument]:
        """对无分数语义的分支（全文为 0）不施加阈值，避免把结果全滤掉。

        仅当文档自带 retrieval=full_text 之外的真实分数时才过滤；
        向量分支已在 SQL 侧过滤，此处为全文/混合的兜底。
        """
        if retrieval_filter is None or retrieval_filter.score_threshold is None:
            return documents
        threshold = float(retrieval_filter.score_threshold)
        kept: list[LCDocument] = []
        for document in documents:
            retrieval = (document.metadata or {}).get("retrieval")
            if retrieval == "full_text":
                kept.append(document)
                continue
            if float((document.metadata or {}).get("score", 0) or 0) >= threshold:
                kept.append(document)
        return kept

    def _semantic_search_knowledge_base(
            self,
            knowledge_bases: list[KnowledgeBase],
            query: str,
            k: int,
            knowledge_scope: str | None = None,
            **vector_kwargs: Any,
    ) -> list[LCDocument]:
        documents: list[LCDocument] = []
        for knowledge_base in knowledge_bases:
            hits = self.knowledge_vector_service.search(
                knowledge_base, query, top_k=k,
                knowledge_scope=knowledge_scope, **vector_kwargs,
            )
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

    def _merge_visual_documents(
        self,
        documents: list[LCDocument],
        visual_documents: list[LCDocument],
        k: int,
    ) -> list[LCDocument]:
        """合并视觉补充召回，按 segment_id 去重并保持总数不超过 k。

        去重必要性：视频帧片段同时带有视觉描述文本，可能已被文本召回命中；
        若不去重，同一帧会以两条结果出现，挤占 top-k 名额。
        已有文本命中优先保留（文本分支已带真实分数且语义描述更完整）。
        """
        if not visual_documents:
            return documents

        seen = {
            document.metadata.get("segment_id")
            for document in documents
            if document.metadata.get("segment_id")
        }
        merged = list(documents)
        for document in visual_documents:
            segment_id = document.metadata.get("segment_id")
            if segment_id and segment_id in seen:
                continue
            if segment_id:
                seen.add(segment_id)
            merged.append(document)
        return merged[:k]

    def _visual_recall_knowledge_base(
            self,
            knowledge_bases: list[KnowledgeBase],
            query: str,
            k: int,
            retrieval_filter: RetrievalFilter | None,
            restricted_document_ids: list[UUID] | None,
    ) -> list[LCDocument]:
        """视觉向量补充召回：文本 query 跨模态召回视频关键帧。

        Qwen3-VL-Embedding 把文本/图片映射到**同一语义空间**，故文本 query 可直接
        与库内帧向量比对余弦相似度，无需融合排序；本通道与文本召回并行，由上层合并去重。

        三重成本/安全护栏（缺一不可）：
        1. 未注入视觉服务（未配置该能力）→ 直接跳过，检索照常工作；
        2. **预检库内是否有帧向量**→ 没有则不发编码调用（视觉编码按次计费，白跑纯浪费）；
        3. 过滤条件必须与文本检索同源下推，**不得绕过**分区/媒体类型/素材范围/标签。

        视觉是补充通道，任何异常都只记日志、返回空，**不得反噬主检索结果**。
        """
        service = getattr(self, "visual_embedding_service", None)
        if service is None:
            return []

        # 媒体类型过滤若明确排除了视频，则帧向量必然不在范围内——fail closed
        if retrieval_filter is not None and retrieval_filter.media_types:
            if DocumentMediaType.VIDEO.value not in retrieval_filter.media_types:
                return []

        # 标签过滤已收敛出的素材范围：空列表表示无命中，此时不应再发起编码
        document_ids = restricted_document_ids
        if document_ids == []:
            return []

        try:
            if not service.has_vectors([kb.id for kb in knowledge_bases]):
                return []

            documents: list[LCDocument] = []
            for knowledge_base in knowledge_bases:
                hits = service.search_by_text(
                    query=query,
                    knowledge_base_id=knowledge_base.id,
                    limit=k,
                    document_ids=document_ids,
                    partition_id=(
                        retrieval_filter.partition_id if retrieval_filter is not None else None
                    ),
                    media_types=(
                        retrieval_filter.media_types if retrieval_filter is not None else None
                    ),
                )
                for hit in hits:
                    documents.append(LCDocument(
                        page_content=hit.get("content", ""),
                        metadata={
                            "knowledge_base_id": str(knowledge_base.id),
                            "knowledge_document_id": hit.get("knowledge_document_id"),
                            "segment_id": hit.get("segment_id"),
                            "frame_url": hit.get("frame_url"),
                            "scene_index": hit.get("scene_index", 0),
                            "source": "knowledge_base",
                            "score": hit.get("score", 0),
                            "retrieval": "visual",
                        },
                    ))
            return documents
        except Exception:
            logging.exception("视觉向量补充召回失败，已降级为仅文本召回")
            return []

    def _full_text_search_knowledge_base(
            self,
            knowledge_base_ids: list[UUID],
            query: str,
            k: int,
            document_ids: list[UUID] | None = None,
    ) -> list[LCDocument]:
        keywords = self.jieba_service.extract_keywords(query, 10)
        if not keywords:
            return []

        segment_query = self.db.session.query(KnowledgeSegment).filter(
            KnowledgeSegment.knowledge_base_id.in_(knowledge_base_ids),
            KnowledgeSegment.enabled.is_(True),
            func.jsonb_exists_any(KnowledgeSegment.keywords, keywords),
        )
        # 受限素材范围必须同样作用于全文分支，否则会绕过分区/媒体类型/标签过滤
        if document_ids:
            segment_query = segment_query.filter(
                KnowledgeSegment.knowledge_document_id.in_(document_ids)
            )
        segments = segment_query.all()

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
            restricted_document_ids: list[UUID] | None = None,
            vector_kwargs: dict | None = None,
    ) -> list[LCDocument]:
        semantic_docs = self._semantic_search_knowledge_base(
            knowledge_bases, query, k,
            knowledge_scope=knowledge_scope, **(vector_kwargs or {}),
        )
        full_text_docs = self._full_text_search_knowledge_base(
            knowledge_base_ids, query, k, document_ids=restricted_document_ids
        )

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
            retrieval_filter: RetrievalFilter | None = None,
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
                retrieval_filter=retrieval_filter,
            )
            for doc in documents:
                metadata = doc.metadata or {}
                carried = {
                    "retrieval": metadata.get("retrieval", ""),
                    "source": metadata.get("source", "knowledge_base"),
                }
                # 视觉召回命中的帧必须带上帧地址与序号：上游要据此展示缩略图/定位画面
                # （设计稿 §4.1「返回候选素材（带缩略图 / 时间戳）」），
                # 只透传 retrieval/source 会让视觉结果退化成一段无图文本。
                if metadata.get("frame_url"):
                    carried["frame_url"] = metadata.get("frame_url")
                    carried["scene_index"] = metadata.get("scene_index", 0)
                results.append(SearchResult(
                    content=doc.page_content,
                    score=float(metadata.get("score", 0) or 0),
                    knowledge_base_id=str(metadata.get("knowledge_base_id", "") or ""),
                    knowledge_scope=scope,
                    document_id=str(metadata.get("knowledge_document_id", "") or ""),
                    segment_id=str(metadata.get("segment_id", "") or ""),
                    metadata=carried,
                ))

        return results

    def create_knowledge_retrieval_tool(
            self,
            flask_app: Any,
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
            partition_id: str | None = Field(
                default=None,
                description="可选，限定在某分区内检索，传分区 ID",
            )
            media_types: list[str] | None = Field(
                default=None,
                description="可选，限定素材类型，取值 image/video/audio/document",
            )
            tags: list[str] | None = Field(
                default=None,
                description="可选，限定素材标签名，多个标签取并集",
            )
            score_threshold: float | None = Field(
                default=None,
                description="可选，相似度下限（0~1），低于该值的结果不返回",
            )

        @tool(KNOWLEDGE_RETRIEVAL_TOOL_NAME, args_schema=KnowledgeRetrievalInput)
        def knowledge_retrieval(
            query: str,
            partition_id: str | None = None,
            media_types: list[str] | None = None,
            tags: list[str] | None = None,
            score_threshold: float | None = None,
        ) -> str:
            """如果需要搜索用户知识库中的相关内容,当你觉得用户的提问超过你的知识范围时,可以尝试调用工具,输入为检索query语句,返回数据为检索内容字符串"""
            retrieval_filter = self._build_retrieval_filter(
                partition_id=partition_id,
                media_types=media_types,
                tags=tags,
                score_threshold=score_threshold,
            )
            # app_session_scope：工具可能在 Agent 自建线程内调用，
            # 退出时归还 session（否则检索事务悬空占用连接）。
            with app_session_scope():
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
                    retrieval_filter=retrieval_filter,
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

    def _build_retrieval_filter(
        self,
        *,
        partition_id: str | None = None,
        media_types: list[str] | None = None,
        tags: list[str] | None = None,
        score_threshold: float | None = None,
    ) -> RetrievalFilter | None:
        """把工具入参组装成 RetrievalFilter；全部为空时返回 None（不过滤）。

        标签名会解析为 tag_id；名称解析不到任何标签时返回空 tag_ids 的 filter，
        由检索层 fail closed 处理（返回空结果而非退化为不过滤）。
        """
        parsed_partition_id: UUID | None = None
        if partition_id:
            try:
                parsed_partition_id = UUID(str(partition_id))
            except (TypeError, ValueError):
                logger.warning("检索工具收到非法 partition_id=%s，忽略该过滤", partition_id)

        normalized_media_types = [item for item in (media_types or []) if item]
        normalized_tags = [item.strip() for item in (tags or []) if item and item.strip()]

        if not (parsed_partition_id or normalized_media_types or normalized_tags
                or score_threshold is not None):
            return None

        tag_ids: list[UUID] | None = None
        if normalized_tags:
            service = getattr(self, "knowledge_tag_service", None)
            # 显式保留空列表语义：有标签名但解析不到 => tag_ids=[] => 检索层 fail closed。
            # 若此处写成 `or None`，就会静默退化成「不过滤」并召回全库。
            tag_ids = (
                list(service.resolve_tag_ids_by_names(normalized_tags))
                if service is not None
                else []
            )

        return RetrievalFilter(
            partition_id=parsed_partition_id,
            media_types=normalized_media_types or None,
            tag_ids=tag_ids,
            score_threshold=score_threshold,
        )



