import logging
from dataclasses import dataclass
from uuid import UUID

from injector import inject
from sqlalchemy import desc, asc, func
from werkzeug.datastructures import FileStorage

from internal.entity.dataset_entity import DocumentStatus, RetrievalStrategy, SegmentStatus
from internal.entity.knowledge_entity import KnowledgeCreatedFrom, KnowledgeScope, OperationContext, VisibilityScope
from internal.exception import ForbiddenException, FailException, NotFoundException, ValidateErrorException
from internal.lib.helper import datetime_to_timestamp, escape_like_pattern
from internal.model import (
    Account,
    AdminUser,
    KnowledgeBase,
    KnowledgeDocument,
    KnowledgeSegment,
)
from internal.schema.knowledge_base_schema import (
    CreateKnowledgeBaseReq,
    UpdateKnowledgeBaseReq,
    GetKnowledgeBasesWithPageReq,
    HitReq,
    GetKnowledgeDocumentsWithPageReq,
    UpdateKnowledgeSegmentReq,
)
from pkg.paginator import Paginator
from pkg.sqlalchemy import SQLAlchemy
from .base_service import BaseService
from .icon_generator_service import IconGeneratorService
from .retrieval_service import RetrievalService


@inject
@dataclass
class KnowledgeBaseService(BaseService):
    """
    KnowledgeBase 是中期统一知识抽象。

    短期后台管理主线仍然是 datasets，现有 Dataset 后台入口在收敛设计完成前
    不应被直接替换为 KnowledgeBase 后台入口。与此同时，Document / Segment
    仍短期归属 Dataset 管理链路，user_memory 也不并入 Dataset 的深层后台。
    """
    db: SQLAlchemy
    retrieval_service: RetrievalService
    icon_generator_service: IconGeneratorService

    def get_user_content_base(self, knowledge_base_id, account: Account) -> KnowledgeBase:
        base = (
            self.db.session.query(KnowledgeBase)
            .filter_by(id=knowledge_base_id, owner_account_id=account.id)
            .one_or_none()
        )
        if base is None or base.knowledge_scope != KnowledgeScope.USER_CONTENT.value:
            raise NotFoundException("知识库不存在")
        return base

    def create_user_content_base(
        self,
        *,
        name: str,
        account: Account,
        admin_user: AdminUser | None = None,
        operation_context: str = "user",
        created_from: str = "manual_upload",
        description: str = "",
    ) -> KnowledgeBase:
        if operation_context != OperationContext.USER.value:
            raise ForbiddenException("用户资料库必须在普通用户上下文创建")
        return self._create_base(
            name=name,
            description=description,
            knowledge_scope=KnowledgeScope.USER_CONTENT.value,
            owner_account_id=account.id,
            owner_admin_user_id=None,
            operation_context=OperationContext.USER.value,
            visibility_scope=VisibilityScope.PRIVATE.value,
            created_from=created_from,
        )

    def create_user_memory_base(
        self,
        *,
        name: str,
        account: Account,
        created_from: str = KnowledgeCreatedFrom.CONVERSATION_MEMORY.value,
        description: str = "",
    ) -> KnowledgeBase:
        return self._create_base(
            name=name,
            description=description,
            knowledge_scope=KnowledgeScope.USER_MEMORY.value,
            owner_account_id=account.id,
            owner_admin_user_id=None,
            operation_context=OperationContext.USER.value,
            visibility_scope=VisibilityScope.PRIVATE.value,
            created_from=created_from,
        )

    def create_system_base(
        self,
        *,
        name: str,
        admin_user: AdminUser | None,
        created_from: str = KnowledgeCreatedFrom.ADMIN_CONFIG.value,
        description: str = "",
        visibility_scope: str = VisibilityScope.INTERNAL.value,
    ) -> KnowledgeBase:
        if admin_user is None:
            raise ForbiddenException("普通用户不能创建系统级知识库")
        return self._create_base(
            name=name,
            description=description,
            knowledge_scope=KnowledgeScope.SYSTEM.value,
            owner_account_id=None,
            owner_admin_user_id=admin_user.id,
            operation_context=OperationContext.ADMIN.value,
            visibility_scope=visibility_scope,
            created_from=created_from,
        )

    def get_accessible_base(self, knowledge_base_id, account: Account) -> KnowledgeBase:
        knowledge_base = self.get(KnowledgeBase, knowledge_base_id)
        if knowledge_base is None or not getattr(knowledge_base, "enabled", True):
            raise NotFoundException("知识库不存在")
        if knowledge_base.knowledge_scope in {
            KnowledgeScope.USER_MEMORY.value,
            KnowledgeScope.USER_CONTENT.value,
        } and knowledge_base.owner_account_id != account.id:
            raise NotFoundException("知识库不存在")
        return knowledge_base

    def _create_base(
        self,
        *,
        name: str,
        description: str,
        knowledge_scope: str,
        owner_account_id,
        owner_admin_user_id,
        operation_context: str,
        visibility_scope: str,
        created_from: str,
    ) -> KnowledgeBase:
        if not name or not name.strip():
            raise ValidateErrorException("知识库名称不能为空")
        duplicated = self.db.session.query(KnowledgeBase).filter_by(
            name=name,
            knowledge_scope=knowledge_scope,
            owner_account_id=owner_account_id,
            owner_admin_user_id=owner_admin_user_id,
        ).one_or_none()
        if duplicated is not None:
            raise ValidateErrorException("知识库名称已存在")
        return self.create(
            KnowledgeBase,
            name=name,
            description=description,
            knowledge_scope=knowledge_scope,
            owner_account_id=owner_account_id,
            owner_admin_user_id=owner_admin_user_id,
            operation_context=operation_context,
            visibility_scope=visibility_scope,
            created_from=created_from,
            settings={"operation_context": operation_context},
        )

    def upload_document(
            self,
            knowledge_base_id,
            file: FileStorage,
            account: Account,
    ) -> KnowledgeDocument:
        """上传文档到知识库并触发索引构建"""
        knowledge_base = self.get_accessible_base(knowledge_base_id, account)

        cos_service = self._get_cos_service()
        upload_file = cos_service.upload_file(file=file, only_image=False, account=account)

        document = self.create(
            KnowledgeDocument,
            knowledge_base_id=knowledge_base.id,
            owner_account_id=account.id,
            name=upload_file.name,
            content_type="document",
            source_type=KnowledgeCreatedFrom.MANUAL_UPLOAD.value,
            source_id=str(upload_file.id),
            upload_file_id=upload_file.id,
            metadata_={
                "upload_file_id": str(upload_file.id),
                "operation_context": OperationContext.USER.value,
            },
            character_count=0,
            status=DocumentStatus.WAITING.value,
        )

        indexing_service = self._get_knowledge_indexing_service()
        indexing_service.build_document(document.id, account)

        return document

    def _get_cos_service(self):
        from flask import current_app
        from .cos_service import CosService
        return current_app.injector.get(CosService)

    def _get_knowledge_indexing_service(self):
        from flask import current_app
        from .knowledge_indexing_service import KnowledgeIndexingService
        return current_app.injector.get(KnowledgeIndexingService)

    def _get_knowledge_vector_service(self):
        """延迟获取知识库向量服务，避免循环依赖"""
        from flask import current_app
        from .knowledge_vector_service import KnowledgeVectorService
        return current_app.injector.get(KnowledgeVectorService)

    # ==================== Embedding 模型自动选择 ====================

    # 主维度优先：所有用户知识库优先绑定 1536 维模型，便于运维和存储压缩
    PRIMARY_EMBEDDING_DIMENSION = 1536

    def auto_select_embedding_model(self):
        """自动为新建知识库选择最优 embedding 模型。

        选择策略（按优先级）：
            1. 维度优先：优先 1536 维（主维度），其他维度按与 1536 的距离升序
            2. 同维度内：按 provider 健康度排序
               - 该 provider 下所有 active keys 的 failure_count 总和（升序）
               - 该 provider 下所有 active keys 的 used_credits 总和（升序，负载均衡）
               - ModelPoolConfig.priority（降序，优先级高者优先）
            3. 必须有至少一条 active 状态的 API key

        Returns:
            ModelPoolConfig 实例

        Raises:
            FailException: 系统无可用 embedding 模型
        """
        from internal.model.model_pool_entity import ModelKeyConfig, ModelPoolConfig

        # 1. 查询所有 active embedding 模型
        models = (
            self.db.session.query(ModelPoolConfig)
            .filter_by(model_type="embedding", status="active")
            .all()
        )
        if not models:
            raise FailException("系统无可用 embedding 模型，请联系管理员在后台配置")

        # 2. 聚合每个 provider 的 active key 健康度
        providers = {m.provider for m in models}
        provider_health: dict[str, tuple[int, float]] = {}
        for provider in providers:
            row = (
                self.db.session.query(
                    func.coalesce(func.sum(ModelKeyConfig.failure_count), 0).label("total_failure"),
                    func.coalesce(func.sum(ModelKeyConfig.used_credits), 0).label("total_used"),
                )
                .filter(
                    ModelKeyConfig.provider == provider,
                    ModelKeyConfig.status == "active",
                )
                .one()
            )
            provider_health[provider] = (int(row.total_failure or 0), float(row.total_used or 0))

        # 3. 过滤掉无 active key 的模型
        candidates = [m for m in models if m.provider in provider_health]
        if not candidates:
            raise FailException("系统 embedding 模型无可用 API key，请联系管理员配置")

        # 4. 排序：维度优先 + 健康度
        def sort_key(m):
            failure, used = provider_health.get(m.provider, (float("inf"), float("inf")))
            dim = int(m.embedding_dimension or 0)
            # 维度优先级：1536=0，其他按距离 1536 的绝对值
            dim_distance = 0 if dim == self.PRIMARY_EMBEDDING_DIMENSION else abs(dim - self.PRIMARY_EMBEDDING_DIMENSION)
            # 返回元组：维度距离, failure, used, -priority
            return (dim_distance, failure, used, -int(m.priority or 0))

        candidates.sort(key=sort_key)
        return candidates[0]

    # ==================== 用户端 user_content 知识库管理接口 ====================

    def create_user_content_base_with_req(self, req: CreateKnowledgeBaseReq, account: Account) -> KnowledgeBase:
        """根据请求创建用户内容知识库（含图标设置）"""
        # 1.创建知识库基础记录
        knowledge_base = self.create_user_content_base(
            name=req.name.data,
            account=account,
            description=req.description.data or "",
        )

        # 2.将图标 URL 写入 settings JSONB 字段
        settings = dict(knowledge_base.settings or {})
        settings["icon"] = req.icon.data

        # 3.自动选择 embedding 模型（用户不能自选，由系统按维度优先+健康度选择）
        selected_model = self.auto_select_embedding_model()

        self.update(knowledge_base, settings=settings, embedding_model_id=selected_model.id)

        return knowledge_base

    def list_user_content_bases(
            self,
            req: GetKnowledgeBasesWithPageReq,
            account: Account,
    ) -> tuple[list[KnowledgeBase], Paginator]:
        """分页查询当前用户的 user_content 知识库列表"""
        # 1.构建分页查询器
        paginator = Paginator(db=self.db, req=req)

        # 2.构建筛选条件：归属当前用户 + scope 为 user_content
        filters = [
            KnowledgeBase.owner_account_id == account.id,
            KnowledgeBase.knowledge_scope == KnowledgeScope.USER_CONTENT.value,
        ]
        if req.search_word.data:
            filters.append(
                KnowledgeBase.name.ilike(f"%{escape_like_pattern(req.search_word.data)}%")
            )

        # 3.执行分页查询
        knowledge_bases = paginator.paginate(
            self.db.session.query(KnowledgeBase).filter(*filters).order_by(desc("created_at"))
        )

        # 4.为每条知识库补充 document_count 和 character_count 动态字段
        for kb in knowledge_bases:
            self._fill_base_stats(kb)

        return knowledge_bases, paginator

    def get_user_content_base_detail(self, knowledge_base_id: UUID, account: Account) -> KnowledgeBase:
        """获取知识库详情（含动态统计字段）"""
        knowledge_base = self.get_user_content_base(knowledge_base_id, account)
        self._fill_base_stats(knowledge_base)
        return knowledge_base

    def update_user_content_base(
            self,
            knowledge_base_id: UUID,
            req: UpdateKnowledgeBaseReq,
            account: Account,
    ) -> KnowledgeBase:
        """更新 user_content 知识库的名称/描述/图标

        注意：embedding_model_id 不允许用户端修改，避免维度错位导致整个知识库向量失效。
        如需切换 embedding 模型，需 admin 端通过同维度切换接口操作。
        """
        # 1.校验知识库归属
        knowledge_base = self.get_user_content_base(knowledge_base_id, account)

        # 2.校验同名知识库（排除自身）
        duplicated = self.db.session.query(KnowledgeBase).filter(
            KnowledgeBase.owner_account_id == account.id,
            KnowledgeBase.knowledge_scope == KnowledgeScope.USER_CONTENT.value,
            KnowledgeBase.name == req.name.data,
            KnowledgeBase.id != knowledge_base_id,
        ).one_or_none()
        if duplicated is not None:
            raise ValidateErrorException(f"该知识库名称{req.name.data}已存在，请修改")

        # 3.合并 settings 并写入图标
        settings = dict(knowledge_base.settings or {})
        settings["icon"] = req.icon.data

        # 4.更新基础字段（不修改 embedding_model_id）
        self.update(
            knowledge_base,
            name=req.name.data,
            description=req.description.data or "",
            settings=settings,
        )

        return knowledge_base

    def delete_user_content_base(self, knowledge_base_id: UUID, account: Account) -> KnowledgeBase:
        """删除 user_content 知识库及其所有文档、片段、向量数据"""
        # 1.校验知识库归属
        knowledge_base = self.get_user_content_base(knowledge_base_id, account)

        try:
            # 2.查询该知识库下所有片段，用于清理 pgvector 向量
            segments = self.db.session.query(KnowledgeSegment).filter(
                KnowledgeSegment.knowledge_base_id == knowledge_base_id,
            ).all()

            # 3.清理 pgvector 中的向量数据（置 NULL）
            knowledge_vector_service = self._get_knowledge_vector_service()
            for segment in segments:
                try:
                    knowledge_vector_service.remove_segment(segment)
                except Exception as e:
                    logging.warning(
                        "清理知识库片段向量失败 segment_id=%s, 错误: %s",
                        segment.id, str(e),
                    )

            # 4.删除知识库下的所有片段、文档（数据库记录）
            with self.db.auto_commit():
                self.db.session.query(KnowledgeSegment).filter(
                    KnowledgeSegment.knowledge_base_id == knowledge_base_id,
                ).delete(synchronize_session=False)
                self.db.session.query(KnowledgeDocument).filter(
                    KnowledgeDocument.knowledge_base_id == knowledge_base_id,
                ).delete(synchronize_session=False)

            # 5.删除知识库基础记录
            self.delete(knowledge_base)
        except Exception as e:
            logging.exception(
                "删除知识库失败 knowledge_base_id=%s, 错误: %s",
                knowledge_base_id, str(e),
            )
            raise FailException("删除知识库失败，请稍后重试")

        return knowledge_base

    def hit_test(self, knowledge_base_id: UUID, req: HitReq, account: Account) -> list[dict]:
        """对 user_content 知识库执行召回测试"""
        # 1.校验知识库归属
        knowledge_base = self.get_user_content_base(knowledge_base_id, account)

        # 2.调用检索服务执行检索（限定 user_content scope）
        lc_documents = self.retrieval_service.search_in_knowledge_base(
            knowledge_base_ids=[knowledge_base.id],
            query=req.query.data,
            account_id=account.id,
            k=req.k.data,
            retrieval_strategy=req.retrieval_strategy.data,
            knowledge_scope=KnowledgeScope.USER_CONTENT.value,
        )

        # 3.提取 segment_id 列表并查询对应的片段与文档信息
        segment_id_list = [
            str(lc_document.metadata.get("segment_id"))
            for lc_document in lc_documents
            if lc_document.metadata.get("segment_id")
        ]
        if not segment_id_list:
            return []

        segments = self.db.session.query(KnowledgeSegment).filter(
            KnowledgeSegment.id.in_(segment_id_list),
        ).all()
        segment_dict = {str(segment.id): segment for segment in segments}

        # 4.按检索结果顺序排序片段
        sorted_segments = [
            segment_dict[str(lc_document.metadata["segment_id"])]
            for lc_document in lc_documents
            if str(lc_document.metadata["segment_id"]) in segment_dict
        ]

        # 5.组装响应数据
        hit_result = []
        for segment in sorted_segments:
            document = segment.knowledge_document
            # 通过 metadata 中的 score 取得匹配分数
            score = 0.0
            for lc_document in lc_documents:
                if str(lc_document.metadata.get("segment_id", "")) == str(segment.id):
                    score = float(lc_document.metadata.get("score", 0.0))
                    break
            hit_result.append({
                "id": segment.id,
                "document": {
                    "id": document.id,
                    "name": document.name,
                    "extension": "",
                    "mime_type": "",
                },
                "knowledge_base_id": segment.knowledge_base_id,
                "score": score,
                "position": segment.position,
                "content": segment.content,
                "keywords": segment.keywords or [],
                "character_count": segment.character_count,
                "token_count": segment.token_count,
                "hit_count": segment.hit_count,
                "enabled": segment.enabled,
                "disabled_at": 0,
                "status": segment.status,
                "error": "",
                "updated_at": datetime_to_timestamp(segment.updated_at),
                "created_at": datetime_to_timestamp(segment.created_at),
            })

        return hit_result

    def get_documents_with_page(
            self,
            knowledge_base_id: UUID,
            req: GetKnowledgeDocumentsWithPageReq,
            account: Account,
    ) -> tuple[list[KnowledgeDocument], Paginator]:
        """分页获取知识库下的文档列表"""
        # 1.校验知识库归属
        self.get_user_content_base(knowledge_base_id, account)

        # 2.构建分页查询器
        paginator = Paginator(db=self.db, req=req)

        # 3.构建筛选条件
        filters = [KnowledgeDocument.knowledge_base_id == knowledge_base_id]
        if req.search_word.data:
            filters.append(
                KnowledgeDocument.name.ilike(f"%{escape_like_pattern(req.search_word.data)}%")
            )

        # 4.执行分页查询
        documents = paginator.paginate(
            self.db.session.query(KnowledgeDocument).filter(*filters).order_by(desc("created_at"))
        )

        # 5.为每个文档补充 segment_count 动态字段
        for document in documents:
            segment_count = self.db.session.query(func.count(KnowledgeSegment.id)).filter(
                KnowledgeSegment.knowledge_document_id == document.id,
            ).scalar() or 0
            setattr(document, "segment_count", segment_count)

        return documents, paginator

    def get_document_detail(
            self,
            knowledge_base_id: UUID,
            document_id: UUID,
            account: Account,
    ) -> KnowledgeDocument:
        """获取知识库下指定文档的详情"""
        # 1.校验知识库归属
        self.get_user_content_base(knowledge_base_id, account)

        # 2.查询文档并校验归属
        document = self.get(KnowledgeDocument, document_id)
        if document is None or str(document.knowledge_base_id) != str(knowledge_base_id):
            raise NotFoundException("该文档不存在，请核实后重试")

        # 3.补充 segment_count 动态字段
        segment_count = self.db.session.query(func.count(KnowledgeSegment.id)).filter(
            KnowledgeSegment.knowledge_document_id == document.id,
        ).scalar() or 0
        setattr(document, "segment_count", segment_count)

        return document

    def delete_document(
            self,
            knowledge_base_id: UUID,
            document_id: UUID,
            account: Account,
    ) -> KnowledgeDocument:
        """删除知识库下指定文档及其片段和向量数据"""
        # 1.校验知识库归属
        self.get_user_content_base(knowledge_base_id, account)

        # 2.查询文档并校验归属
        document = self.get(KnowledgeDocument, document_id)
        if document is None or str(document.knowledge_base_id) != str(knowledge_base_id):
            raise NotFoundException("该文档不存在，请核实后重试")

        try:
            # 3.查询该文档下的所有片段，用于清理 pgvector 向量
            segments = self.db.session.query(KnowledgeSegment).filter(
                KnowledgeSegment.knowledge_document_id == document_id,
            ).all()

            # 4.清理 pgvector 中的向量数据
            knowledge_vector_service = self._get_knowledge_vector_service()
            for segment in segments:
                try:
                    knowledge_vector_service.remove_segment(segment)
                except Exception as e:
                    logging.warning(
                        "清理文档片段向量失败 segment_id=%s, 错误: %s",
                        segment.id, str(e),
                    )

            # 5.删除片段记录与文档记录
            with self.db.auto_commit():
                self.db.session.query(KnowledgeSegment).filter(
                    KnowledgeSegment.knowledge_document_id == document_id,
                ).delete(synchronize_session=False)
                self.db.session.delete(document)
        except Exception as e:
            logging.exception(
                "删除知识库文档失败 document_id=%s, 错误: %s",
                document_id, str(e),
            )
            raise FailException("删除文档失败，请稍后重试")

        return document

    def get_segments_with_page(
            self,
            knowledge_base_id: UUID,
            document_id: UUID,
            req,
            account: Account,
    ) -> tuple[list[KnowledgeSegment], Paginator]:
        """分页获取文档下的片段列表"""
        # 1.校验知识库归属
        self.get_user_content_base(knowledge_base_id, account)

        # 2.校验文档归属
        document = self.get(KnowledgeDocument, document_id)
        if document is None or str(document.knowledge_base_id) != str(knowledge_base_id):
            raise NotFoundException("该文档不存在，请核实后重试")

        # 3.构建分页查询器
        paginator = Paginator(db=self.db, req=req)

        # 4.构建筛选条件
        filters = [
            KnowledgeSegment.knowledge_base_id == knowledge_base_id,
            KnowledgeSegment.knowledge_document_id == document_id,
        ]
        if req.search_word.data:
            filters.append(
                KnowledgeSegment.content.ilike(f"%{escape_like_pattern(req.search_word.data)}%")
            )

        # 5.执行分页查询
        segments = paginator.paginate(
            self.db.session.query(KnowledgeSegment).filter(*filters).order_by(asc("position"))
        )

        return segments, paginator

    def update_segment(
            self,
            knowledge_base_id: UUID,
            document_id: UUID,
            segment_id: UUID,
            req: UpdateKnowledgeSegmentReq,
            account: Account,
    ) -> KnowledgeSegment:
        """更新文档片段的启用状态或内容"""
        # 1.校验知识库归属
        self.get_user_content_base(knowledge_base_id, account)

        # 2.查询片段并校验归属
        segment = self.get(KnowledgeSegment, segment_id)
        if (
                segment is None
                or str(segment.knowledge_base_id) != str(knowledge_base_id)
                or str(segment.knowledge_document_id) != str(document_id)
        ):
            raise NotFoundException("该文档片段不存在，或无权限修改，请核实后重试")

        # 3.组装更新字段
        update_fields = {}
        if req.enabled.data is not None:
            update_fields["enabled"] = req.enabled.data
        if req.content.data is not None:
            update_fields["content"] = req.content.data
            update_fields["character_count"] = len(req.content.data)

        if not update_fields:
            return segment

        # 4.执行更新
        self.update(segment, **update_fields)

        # 5.如果内容变化，重新生成向量索引
        if "content" in update_fields:
            try:
                knowledge_base = self.get(KnowledgeBase, knowledge_base_id)
                knowledge_vector_service = self._get_knowledge_vector_service()
                knowledge_vector_service.index_segment(segment, knowledge_base)
            except Exception as e:
                logging.warning(
                    "更新片段向量失败 segment_id=%s, 错误: %s",
                    segment_id, str(e),
                )

        return segment

    def regenerate_icon(self, knowledge_base_id: UUID, account: Account) -> str:
        """重新生成知识库图标"""
        # 1.校验知识库归属
        knowledge_base = self.get_user_content_base(knowledge_base_id, account)

        # 2.调用图标生成服务
        try:
            logging.info(
                "重新生成知识库图标: knowledge_base_id=%s, name=%s",
                knowledge_base_id, knowledge_base.name,
            )
            icon_url = self.icon_generator_service.generate_icon(
                name=knowledge_base.name,
                description=knowledge_base.description or "",
            )
            logging.info("重新生成知识库图标成功: %s", icon_url)
        except Exception as e:
            logging.exception(
                "重新生成知识库图标失败 knowledge_base_id=%s", knowledge_base_id, exc_info=e
            )
            raise FailException("重新生成图标失败，请稍后重试")

        # 3.写入 settings JSONB 字段
        settings = dict(knowledge_base.settings or {})
        settings["icon"] = icon_url
        self.update(knowledge_base, settings=settings)

        return icon_url

    def generate_icon_preview(self, name: str, description: str) -> str:
        """生成图标预览（不保存到知识库）"""
        try:
            logging.info("生成知识库图标预览: name=%s", name)
            icon_url = self.icon_generator_service.generate_icon(
                name=name,
                description=description or "",
            )
            logging.info("生成图标预览成功: %s", icon_url)
            return icon_url
        except Exception as e:
            logging.exception("生成图标预览失败 name=%s", name, exc_info=e)
            raise FailException("生成图标预览失败，请稍后重试")

    def _fill_base_stats(self, knowledge_base: KnowledgeBase) -> None:
        """为 KnowledgeBase 实例补充 document_count 和 character_count 动态字段"""
        try:
            document_count, character_count = self.db.session.query(
                func.count(KnowledgeDocument.id),
                func.coalesce(func.sum(KnowledgeDocument.character_count), 0),
            ).filter(
                KnowledgeDocument.knowledge_base_id == knowledge_base.id,
            ).first()
            setattr(knowledge_base, "document_count", document_count or 0)
            setattr(knowledge_base, "character_count", int(character_count or 0))
        except Exception as e:
            logging.warning("填充知识库统计字段失败 kb_id=%s, 错误: %s", knowledge_base.id, str(e))
            setattr(knowledge_base, "document_count", 0)
            setattr(knowledge_base, "character_count", 0)
