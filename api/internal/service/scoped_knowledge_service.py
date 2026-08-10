from dataclasses import dataclass
import logging
import math

from injector import inject
from sqlalchemy import asc, desc, func

from internal.entity.dataset_entity import DocumentStatus
from internal.entity.knowledge_entity import KnowledgeCreatedFrom, KnowledgeScope, OperationContext, VisibilityScope
from internal.exception import ForbiddenException, NotFoundException
from internal.lib.helper import escape_like_pattern
from internal.model import Account, AdminUser, KnowledgeBase, KnowledgeDocument, KnowledgeSegment
from pkg.paginator import Paginator
from pkg.sqlalchemy import SQLAlchemy
from .knowledge_base_service import KnowledgeBaseService

logger = logging.getLogger(__name__)


@inject
@dataclass
class SystemKnowledgeService(KnowledgeBaseService):
    db: SQLAlchemy

    def create_system_knowledge(
        self,
        *,
        name: str,
        admin_user: AdminUser | None,
        description: str = "",
        visibility_scope: str = VisibilityScope.INTERNAL.value,
    ) -> KnowledgeBase:
        if admin_user is None:
            raise ForbiddenException("普通用户不能创建系统级知识")
        knowledge_base = self.create_system_base(
            name=name,
            admin_user=admin_user,
            description=description,
            created_from=KnowledgeCreatedFrom.ADMIN_CONFIG.value,
            visibility_scope=visibility_scope,
        )
        # 自动绑定最优 embedding 模型（同 user_content 知识库）
        selected_model = self.auto_select_embedding_model()
        self.update(knowledge_base, embedding_model_id=selected_model.id)
        # 记录系统级知识库创建审计日志
        self._emit_audit(
            admin_user_id=getattr(admin_user, "id", None),
            action="create",
            resource_id=str(getattr(knowledge_base, "id", "")),
            after_data={
                "name": name,
                "description": description,
                "visibility_scope": visibility_scope,
                "embedding_model_id": str(selected_model.id),
            },
        )
        return knowledge_base

    def list_system_knowledge(
        self,
        *,
        page: int = 1,
        page_size: int = 20,
        search_word: str = "",
    ) -> dict:
        """查询系统知识库列表，支持分页与按名称模糊搜索。

        返回结构同时包含兼容旧前端的 {items, total} 与分页器字段
        {page, page_size, total_pages, total_record}。
        """
        # 规范化分页参数，page 不小于 1，page_size 限制在 1~100（项目硬约束）
        page = max(int(page or 1), 1)
        page_size = max(min(int(page_size or 20), 100), 1)
        from internal.service.system_prompt_library_service import SYSTEM_PROMPT_LIBRARY_BASE_NAME
        query = (
            self.db.session.query(KnowledgeBase)
            .filter(KnowledgeBase.knowledge_scope == KnowledgeScope.SYSTEM.value)
            # 系统提示词库是内置提示词的存储容器，由「系统内置提示词」页签管理，
            # 不作为普通系统知识库展示在列表中
            .filter(KnowledgeBase.name != SYSTEM_PROMPT_LIBRARY_BASE_NAME)
        )
        # search_word 非空时按名称模糊匹配
        if search_word:
            query = query.filter(KnowledgeBase.name.ilike(f"%{search_word}%"))
        total = query.count()
        items = (
            query.order_by(KnowledgeBase.created_at.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
            .all()
        )
        # 计算总页数
        total_pages = math.ceil(total / page_size) if total else 0
        return {
            "items": items,
            "total": total,
            "page": page,
            "page_size": page_size,
            "total_pages": total_pages,
            "total_record": total,
        }

    def get_system_knowledge(self, knowledge_base_id) -> KnowledgeBase:
        knowledge_base = (
            self.db.session.query(KnowledgeBase)
            .filter_by(id=knowledge_base_id, knowledge_scope=KnowledgeScope.SYSTEM.value)
            .one_or_none()
        )
        if knowledge_base is None:
            raise NotFoundException("系统知识库不存在")
        return knowledge_base

    def update_system_knowledge(
        self,
        knowledge_base_id,
        *,
        name: str | None = None,
        description: str | None = None,
        enabled: bool | None = None,
        visibility_scope: str | None = None,
        embedding_model_id=None,
        admin_user: AdminUser | None = None,
    ) -> KnowledgeBase:
        from internal.exception import ValidateErrorException
        from internal.model.model_pool_entity import ModelPoolConfig

        knowledge_base = self.get_system_knowledge(knowledge_base_id)
        # 记录变更前数据用于审计
        before_data = {
            "name": knowledge_base.name,
            "description": knowledge_base.description,
            "enabled": getattr(knowledge_base, "enabled", True),
            "visibility_scope": knowledge_base.visibility_scope,
            "embedding_model_id": str(knowledge_base.embedding_model_id or ""),
        }
        update_kwargs: dict = {}
        if name is not None:
            update_kwargs["name"] = name
        if description is not None:
            update_kwargs["description"] = description
        if enabled is not None:
            update_kwargs["enabled"] = enabled
        if visibility_scope is not None:
            update_kwargs["visibility_scope"] = visibility_scope

        # embedding_model_id 同维度限制：admin 只能切换到与当前模型同维度的模型
        # 避免维度错位导致整个知识库历史向量失效
        if embedding_model_id is not None:
            new_model_id = str(embedding_model_id).strip() or None
            if new_model_id:
                new_model = self.db.session.query(ModelPoolConfig).filter_by(id=new_model_id).first()
                if new_model is None or new_model.model_type != "embedding" or new_model.status != "active":
                    raise ValidateErrorException("目标 embedding 模型不存在或不可用")
                current_dim = int(getattr(knowledge_base, "embedding_model", None).embedding_dimension or 0) if knowledge_base.embedding_model else 0
                new_dim = int(new_model.embedding_dimension or 0)
                if current_dim > 0 and new_dim != current_dim:
                    raise ValidateErrorException(
                        f"embedding 模型维度不一致（当前 {current_dim} 维，目标 {new_dim} 维），"
                        f"切换模型会导致历史向量失效，仅允许切换同维度模型"
                    )
                update_kwargs["embedding_model_id"] = new_model.id
            else:
                # 不允许清空已绑定的 embedding 模型
                if knowledge_base.embedding_model_id is not None:
                    raise ValidateErrorException("不允许清空已绑定的 embedding 模型")

        if update_kwargs:
            self.update(knowledge_base, **update_kwargs)
        # 记录系统级知识库更新审计日志
        self._emit_audit(
            admin_user_id=getattr(admin_user, "id", None),
            action="update",
            resource_id=str(getattr(knowledge_base, "id", "")),
            before_data=before_data,
            after_data=update_kwargs,
        )
        return knowledge_base

    def delete_system_knowledge(
        self,
        knowledge_base_id,
        *,
        admin_user: AdminUser | None = None,
        retention_days: int | None = None,
    ) -> None:
        """删除系统知识库（进入回收站，留存期到期后彻底销毁）。

        删除 = 写入 recycle_bin（完整快照） + 物理删除知识库及其文档/分段/向量。
        恢复由回收站按快照重建；回收站不可手动清空。
        """
        knowledge_base = self.get_system_knowledge(knowledge_base_id)
        kb_id_str = str(knowledge_base.id)
        # 内置系统知识库保护：系统提示词库不允许删除（可改为停用）
        if knowledge_base.name == "系统提示词库":
            from internal.exception import ValidateErrorException
            raise ValidateErrorException(
                "「系统提示词库」为平台内置知识库，禁止删除；如需停用请关闭启用开关"
            )
        # 记录变更前数据用于审计（在物理删除前拷贝，避免删除后 ORM 实例失效）
        before_data = {
            "name": knowledge_base.name,
            "description": knowledge_base.description,
            "enabled": getattr(knowledge_base, "enabled", True),
        }
        from internal.service.recycle_bin_service import RecycleBinService
        deleted = RecycleBinService().delete_resource(
            resource_type="knowledge_base",
            resource_id=knowledge_base.id,
            resource_key=kb_id_str,
            resource_name=knowledge_base.name,
            deleted_by=getattr(admin_user, "id", None),
            retention_days=retention_days,
        )
        if not deleted:
            raise NotFoundException("系统知识库不存在")
        # 记录系统级知识库删除审计日志
        self._emit_audit(
            admin_user_id=getattr(admin_user, "id", None),
            action="delete",
            resource_id=kb_id_str,
            before_data=before_data,
            after_data={"retention_days": retention_days},
        )

    # ==================== admin 端：库内文档管理 + 命中测试 ====================
    # 仅校验知识库为 system scope（get_system_knowledge），不校验账号归属

    def list_documents_for_admin(
        self,
        knowledge_base_id,
        req,
    ) -> tuple[list[KnowledgeDocument], Paginator]:
        """admin 分页获取系统知识库下的文档列表"""
        knowledge_base = self.get_system_knowledge(knowledge_base_id)

        paginator = Paginator(db=self.db, req=req)
        filters = [KnowledgeDocument.knowledge_base_id == knowledge_base.id]
        if req.search_word.data:
            filters.append(
                KnowledgeDocument.name.ilike(f"%{escape_like_pattern(req.search_word.data)}%")
            )

        documents = paginator.paginate(
            self.db.session.query(KnowledgeDocument).filter(*filters).order_by(desc("created_at"))
        )

        for document in documents:
            # 实时统计分段数与真实字符数（segment.character_count 可能因历史原因失真，按内容长度统计）
            seg_count, seg_chars = (
                self.db.session.query(
                    func.count(KnowledgeSegment.id),
                    func.coalesce(func.sum(func.length(KnowledgeSegment.content)), 0),
                )
                .filter(KnowledgeSegment.knowledge_document_id == document.id)
                .one()
            )
            setattr(document, "segment_count", seg_count)
            setattr(document, "segment_character_count", seg_chars)

        return documents, paginator

    def get_document_for_admin(self, knowledge_base_id, document_id) -> KnowledgeDocument:
        """admin 获取系统知识库下指定文档详情"""
        self.get_system_knowledge(knowledge_base_id)

        document = self.get(KnowledgeDocument, document_id)
        if document is None or str(document.knowledge_base_id) != str(knowledge_base_id):
            raise NotFoundException("该文档不存在，请核实后重试")

        segment_count = self.db.session.query(func.count(KnowledgeSegment.id)).filter(
            KnowledgeSegment.knowledge_document_id == document.id,
        ).scalar() or 0
        setattr(document, "segment_count", segment_count)

        return document

    def delete_document_for_admin(self, knowledge_base_id, document_id, *, admin_user=None, retention_days=None) -> KnowledgeDocument:
        """admin 删除系统知识库文档：进入回收站（销毁保护，留存期满自动销毁存储文件）。"""
        self.get_system_knowledge(knowledge_base_id)

        document = self.get(KnowledgeDocument, document_id)
        if document is None or str(document.knowledge_base_id) != str(knowledge_base_id):
            raise NotFoundException("该文档不存在，请核实后重试")

        # 系统资源删除统一走回收站：先快照（文档+分段+上传文件记录），
        # 再物理删除 DB 记录；底层存储对象留待留存期满由回收站任务销毁
        from internal.service.recycle_bin_service import RecycleBinService
        deleted = RecycleBinService().delete_resource(
            resource_type="knowledge_document",
            resource_id=document.id,
            resource_key=str(document.id),
            resource_name=document.name,
            deleted_by=getattr(admin_user, "id", None),
            retention_days=retention_days,
        )
        if not deleted:
            raise NotFoundException("该文档不存在，请核实后重试")
        return document

    def create_text_document_for_admin(self, knowledge_base_id, name, content) -> KnowledgeDocument:
        """admin 以纯文本新建系统知识库文档（内容按 txt 走完整索引链路，可被检索）"""
        knowledge_base = self.get_system_knowledge(knowledge_base_id)

        upload_file = self._upload_text_as_file(name, content)
        document = self.create(
            KnowledgeDocument,
            knowledge_base_id=knowledge_base.id,
            owner_account_id=None,
            name=name,
            content_type="document",
            source_type=KnowledgeCreatedFrom.MANUAL_UPLOAD.value,
            source_id=str(upload_file.id),
            upload_file_id=upload_file.id,
            metadata_={
                "upload_file_id": str(upload_file.id),
                "operation_context": OperationContext.ADMIN.value,
            },
            character_count=0,
            status=DocumentStatus.WAITING.value,
        )

        self._dispatch_document_indexing(document.id)
        return document

    def update_text_document_for_admin(
        self,
        knowledge_base_id,
        document_id,
        name,
        content,
    ) -> KnowledgeDocument:
        """admin 编辑系统知识库文档（重建内容索引，保持文档 id 不变）"""
        self.get_system_knowledge(knowledge_base_id)

        document = self.get(KnowledgeDocument, document_id)
        if document is None or str(document.knowledge_base_id) != str(knowledge_base_id):
            raise NotFoundException("该文档不存在，请核实后重试")

        # 1. 将新内容作为 txt 文件上传
        upload_file = self._upload_text_as_file(name, content)
        # 2. 清理旧分段与向量数据
        self._clear_document_segments(document)
        # 3. 更新文档指向新内容并重建索引
        self.update(
            document,
            name=name,
            upload_file_id=upload_file.id,
            source_id=str(upload_file.id),
            metadata_={
                "upload_file_id": str(upload_file.id),
                "operation_context": OperationContext.ADMIN.value,
            },
            character_count=0,
            token_count=0,
            status=DocumentStatus.WAITING.value,
            error="",
        )
        self._get_knowledge_indexing_service().build_document(document.id, None)
        return document

    def _upload_text_as_file(self, name, content):
        """把纯文本内容包装为 txt 文件上传到对象存储，返回 UploadFile 记录。"""
        from io import BytesIO
        from werkzeug.datastructures import FileStorage

        base_name = (name or "未命名文档").strip() or "未命名文档"
        filename = base_name if base_name.lower().endswith(".txt") else f"{base_name}.txt"
        file = FileStorage(
            stream=BytesIO(content.encode("utf-8")),
            filename=filename,
            content_type="text/plain",
        )
        return self._get_cos_service().upload_file(file=file, only_image=False, account=None)

    def _clear_document_segments(self, document) -> None:
        """删除文档下所有分段记录及其向量数据（不删除文档本身，供重建索引使用）。"""
        document_id = document.id
        segments = self.db.session.query(KnowledgeSegment).filter(
            KnowledgeSegment.knowledge_document_id == document_id,
        ).all()
        knowledge_vector_service = self._get_knowledge_vector_service()
        for segment in segments:
            try:
                knowledge_vector_service.remove_segment(segment)
            except Exception:
                import logging
                logging.getLogger(__name__).warning(
                    "清理系统知识库文档分段向量失败 segment_id=%s",
                    segment.id, exc_info=True,
                )
        with self.db.auto_commit():
            self.db.session.query(KnowledgeSegment).filter(
                KnowledgeSegment.knowledge_document_id == document_id,
            ).delete(synchronize_session=False)

    def upload_document_for_admin(self, knowledge_base_id, file) -> KnowledgeDocument:
        """admin 上传文档到系统知识库并触发索引构建（owner 置空，不校验账号归属）"""
        knowledge_base = self.get_system_knowledge(knowledge_base_id)

        cos_service = self._get_cos_service()
        upload_file = cos_service.upload_file(file=file, only_image=False, account=None)

        document = self.create(
            KnowledgeDocument,
            knowledge_base_id=knowledge_base.id,
            owner_account_id=None,
            name=upload_file.name,
            content_type="document",
            source_type=KnowledgeCreatedFrom.MANUAL_UPLOAD.value,
            source_id=str(upload_file.id),
            upload_file_id=upload_file.id,
            metadata_={
                "upload_file_id": str(upload_file.id),
                "operation_context": OperationContext.ADMIN.value,
            },
            character_count=0,
            status=DocumentStatus.WAITING.value,
        )

        self._dispatch_document_indexing(document.id)

        return document

    def _dispatch_document_indexing(self, document_id) -> None:
        """异步派发文档索引任务。

        优先通过 Celery 后台执行索引，避免阻塞上传/新建/编辑接口；
        Celery 不可用时回退为同步执行，保证索引不丢失。
        """
        try:
            from internal.task.knowledge_indexing_tasks import build_document_task

            build_document_task.delay(str(document_id), None)
            logger.info("文档索引已派发 Celery document_id=%s", document_id)
        except Exception:
            logger.warning(
                "文档索引 Celery 派发失败，回退同步执行 document_id=%s",
                document_id, exc_info=True,
            )
            self._get_knowledge_indexing_service().build_document(document_id, None)

    def get_segments_for_admin(
        self,
        knowledge_base_id,
        document_id,
        req,
    ) -> tuple[list[KnowledgeSegment], Paginator]:
        """admin 分页获取系统知识库文档下的片段列表"""
        self.get_system_knowledge(knowledge_base_id)

        document = self.get(KnowledgeDocument, document_id)
        if document is None or str(document.knowledge_base_id) != str(knowledge_base_id):
            raise NotFoundException("该文档不存在，请核实后重试")

        paginator = Paginator(db=self.db, req=req)
        filters = [
            KnowledgeSegment.knowledge_base_id == knowledge_base_id,
            KnowledgeSegment.knowledge_document_id == document_id,
        ]
        if req.search_word.data:
            filters.append(
                KnowledgeSegment.content.ilike(f"%{escape_like_pattern(req.search_word.data)}%")
            )

        segments = paginator.paginate(
            self.db.session.query(KnowledgeSegment).filter(*filters).order_by(asc("position"))
        )

        return segments, paginator

    def hit_test_for_admin(self, knowledge_base_id, req) -> list[dict]:
        """admin 对系统知识库执行召回测试（允许 system scope）"""
        knowledge_base = self.get_system_knowledge(knowledge_base_id)

        lc_documents = self.retrieval_service.search_in_knowledge_base(
            knowledge_base_ids=[knowledge_base.id],
            query=req.query.data,
            account_id=None,
            k=req.k.data,
            retrieval_strategy=req.retrieval_strategy.data,
            knowledge_scope=KnowledgeScope.SYSTEM.value,
        )

        return self._build_hit_result(lc_documents)

    def _get_audit_log_service(self):
        """获取审计日志服务实例，便于子类覆写或测试 mock。"""
        from internal.service.audit_log_service import AuditLogService
        return AuditLogService(session=self.db.session)

    def _emit_audit(
        self,
        *,
        admin_user_id,
        action: str,
        resource_id: str = "",
        before_data: dict | None = None,
        after_data: dict | None = None,
    ) -> None:
        """记录系统级知识库操作审计日志，失败不影响主流程。"""
        if not admin_user_id:
            return
        try:
            self._get_audit_log_service().record_for_write(
                admin_user_id=admin_user_id,
                action=action,
                resource_type="system_knowledge",
                resource_id=resource_id,
                before_data=before_data,
                after_data=after_data,
            )
        except Exception:
            import logging
            logging.getLogger(__name__).warning(
                "系统知识库审计日志记录失败，不影响主流程", exc_info=True
            )


@inject
@dataclass
class UserContentKnowledgeService(KnowledgeBaseService):
    """
    用户内容知识服务服务于 KnowledgeBase 抽象层。

    短期不直接替代 datasets 的后台深层管理入口，Document / Segment 仍沿用
    Dataset 管理主线，避免在收敛设计完成前提前替换后台入口语义。
    """
    db: SQLAlchemy

    def create_home_upload_base(
        self,
        *,
        name: str,
        account: Account,
        admin_user: AdminUser | None = None,
        description: str = "",
    ) -> KnowledgeBase:
        return self._create_base(
            name=name,
            description=description,
            knowledge_scope=KnowledgeScope.USER_CONTENT.value,
            owner_account_id=account.id,
            owner_admin_user_id=None,
            operation_context=OperationContext.USER.value,
            visibility_scope=VisibilityScope.PRIVATE.value,
            created_from=KnowledgeCreatedFrom.MANUAL_UPLOAD.value,
        )

    def list_authorized_bases(self, account: Account) -> list[KnowledgeBase]:
        """列出当前用户在 App 中可引用的所有知识库。

        规则：
            - 自己 owner 的 user_content / user_memory 库（enabled=True）
            - enabled=True 的系统知识库（admin 通过 enabled 开关控制对 Agent 是否可读）
        """
        bases = (
            self.db.session.query(KnowledgeBase)
            .filter(KnowledgeBase.enabled.is_(True))
            .all()
        )
        return [base for base in bases if self._is_authorized_base(base, account)]

    def list_readable_system_bases(self) -> list[KnowledgeBase]:
        """列出所有 enabled=True 的系统知识库（对 Agent 可读）。

        供用户端 App 配置选择知识库时调用。
        admin 通过 enabled 开关控制系统知识库是否对 Agent 生效：
            - enabled=True  → Agent 可读，App 可引用
            - enabled=False → Agent 不可读，已引用的 App 检索无结果
        """
        return (
            self.db.session.query(KnowledgeBase)
            .filter(
                KnowledgeBase.knowledge_scope == KnowledgeScope.SYSTEM.value,
                KnowledgeBase.enabled.is_(True),
            )
            .order_by(KnowledgeBase.created_at.desc())
            .all()
        )

    @staticmethod
    def _is_authorized_base(base: KnowledgeBase, account: Account) -> bool:
        """判断一个知识库是否对当前用户授权可引用。

        - system 库：必须 enabled=True 才授权（admin 通过 enabled 开关控制）
        - user_memory / user_content 库：必须 owner_account_id == account.id
        """
        if base.knowledge_scope == KnowledgeScope.SYSTEM.value:
            return bool(getattr(base, "enabled", False))
        if base.knowledge_scope in {
            KnowledgeScope.USER_MEMORY.value,
            KnowledgeScope.USER_CONTENT.value,
        }:
            return base.owner_account_id == account.id
        return False
