import logging
from dataclasses import dataclass
from pathlib import Path
from uuid import UUID

from internal.context import current_app
from injector import inject
from sqlalchemy import desc, asc, func
from sqlalchemy.exc import IntegrityError
from werkzeug.datastructures import FileStorage

from internal.entity.dataset_entity import DocumentStatus
from internal.entity.knowledge_entity import (
    DocumentMediaType,
    KnowledgeBaseType,
    KnowledgeCreatedFrom,
    KnowledgeScope,
    OperationContext,
    PartitionMode,
    VisibilityScope,
)
from internal.entity.upload_file_entity import allowed_extensions_for_base_type, media_type_for_extension
from internal.exception import ForbiddenException, FailException, NotFoundException, ValidateErrorException
from internal.lib.helper import datetime_to_timestamp, escape_like_pattern
from internal.model import (
    Account,
    AdminUser,
    KnowledgeBase,
    KnowledgeDocument,
    KnowledgeSegment,
    UploadFile,
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


# 系统预置成品库的固定名称（每用户唯一，系统托管，禁止手动上传）
RENDER_OUTPUT_BASE_NAME = "成品库"


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
        base_type: str = KnowledgeBaseType.MIXED.value,
        partition_mode: str = PartitionMode.NONE.value,
    ) -> KnowledgeBase:
        if operation_context != OperationContext.USER.value:
            raise ForbiddenException("用户资料库必须在普通用户上下文创建")
        if base_type not in {member.value for member in KnowledgeBaseType}:
            raise ValidateErrorException(
                f"不支持的板块类型：{base_type}",
                {"base_type": [f"可选值：{[m.value for m in KnowledgeBaseType]}"]},
            )
        if partition_mode not in {member.value for member in PartitionMode}:
            raise ValidateErrorException(
                f"不支持的分区模式：{partition_mode}",
                {"partition_mode": [f"可选值：{[m.value for m in PartitionMode]}"]},
            )
        return self._create_base(
            name=name,
            description=description,
            knowledge_scope=KnowledgeScope.USER_CONTENT.value,
            owner_account_id=account.id,
            owner_admin_user_id=None,
            operation_context=OperationContext.USER.value,
            visibility_scope=VisibilityScope.PRIVATE.value,
            created_from=created_from,
            base_type=base_type,
            partition_mode=partition_mode,
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

    def get_or_create_render_output_base(self, account: Account) -> KnowledgeBase:
        """取当前账号的系统预置成品库，不存在则幂等创建。

        设计 §4.2：首次需要写成品时才建库，避免给从未出片的用户平白建库。

        并发安全：两个请求可能同时查不到而各建一个。DB 侧的
        `knowledge_base_render_output_uniq`（部分唯一索引）会拒绝第二个，
        此处捕获 IntegrityError 后 rollback 并重查，返回先建成的那个。

        按 `created_from` 查而非按名称查——用户完全可能已手建一个叫「成品库」
        的普通素材库，按名称查会错误地复用它。
        """
        def _find() -> KnowledgeBase | None:
            return (
                self.db.session.query(KnowledgeBase)
                .filter_by(
                    owner_account_id=account.id,
                    created_from=KnowledgeCreatedFrom.RENDER_OUTPUT.value,
                )
                .one_or_none()
            )

        existing = _find()
        if existing is not None:
            return existing

        try:
            knowledge_base = self.create(
                KnowledgeBase,
                name=RENDER_OUTPUT_BASE_NAME,
                description="系统预置：渲染成品的归集处（系统托管，不支持手动上传）",
                knowledge_scope=KnowledgeScope.USER_CONTENT.value,
                base_type=KnowledgeBaseType.VIDEO.value,
                partition_mode=PartitionMode.NONE.value,
                owner_account_id=account.id,
                owner_admin_user_id=None,
                operation_context=OperationContext.USER.value,
                visibility_scope=VisibilityScope.PRIVATE.value,
                created_from=KnowledgeCreatedFrom.RENDER_OUTPUT.value,
                settings={"operation_context": OperationContext.USER.value},
            )
        except IntegrityError:
            # 并发下已被另一请求建成：回滚后取既有库
            self.db.session.rollback()
            concurrent = _find()
            if concurrent is None:
                raise
            return concurrent

        # 与 create_user_content_base_with_req 同口径：自动选 embedding 模型，
        # 使成品可被检索复用（设计 §4.1「用户可让小钰从成品库翻旧片翻新」）
        selected_model = self.auto_select_embedding_model()
        return self.update(knowledge_base, embedding_model_id=selected_model.id)

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
        base_type: str = KnowledgeBaseType.MIXED.value,
        partition_mode: str = PartitionMode.NONE.value,
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
            base_type=base_type,
            partition_mode=partition_mode,
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
        """上传素材到知识库并触发索引构建。

        先按扩展名做板块类型硬约束校验（避免被拒绝的文件落盘占用配额），
        再执行上传与索引构建。
        """
        knowledge_base = self.get_accessible_base(knowledge_base_id, account)
        self._assert_not_render_output_base(knowledge_base)

        # 先校验后上传：被拒绝的文件不应写入存储、不应占用用户配额
        filename = getattr(file, "filename", "") or ""
        incoming_extension = filename.rsplit(".", 1)[-1] if "." in filename else ""
        self._assert_media_type_allowed(knowledge_base, incoming_extension)

        cos_service = self._get_cos_service()
        upload_file = cos_service.upload_file(file=file, only_image=False, account=account)

        return self.create_document_from_upload_file(
            knowledge_base_id=knowledge_base.id,
            upload_file=upload_file,
            account=account,
        )

    def create_document_from_upload_file(
            self,
            *,
            knowledge_base_id,
            upload_file: UploadFile,
            account: Account,
            partition_id=None,
    ) -> KnowledgeDocument:
        """由已存在的 UploadFile 创建知识库文档并触发索引。

        用于分片上传完成后的建档；会做板块类型硬约束校验。
        """
        knowledge_base = self.get_accessible_base(knowledge_base_id, account)
        self._assert_not_render_output_base(knowledge_base)

        extension = (upload_file.extension or "").lower()
        self._assert_media_type_allowed(knowledge_base, extension)
        media_type = media_type_for_extension(extension)

        document = self.create(
            KnowledgeDocument,
            knowledge_base_id=knowledge_base.id,
            owner_account_id=account.id,
            name=upload_file.name,
            content_type="document",
            source_type=KnowledgeCreatedFrom.MANUAL_UPLOAD.value,
            source_id=str(upload_file.id),
            upload_file_id=upload_file.id,
            partition_id=partition_id,
            media_type=media_type,
            parse_profile={},
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

    def store_render_output(
        self,
        *,
        account: Account,
        video_path,
        name: str,
        base: KnowledgeBase | None = None,
    ) -> KnowledgeDocument:
        """把渲染成品写入成品库并建索引（设计 §4）。

        这是**系统写入**路径，供渲染链路调用，因此**不**经过
        `_assert_not_render_output_base`（那条只拦用户手动上传）。

        步骤：取/建成品库 → MP4 落 COS → 建 KnowledgeDocument → 触发索引。
        索引不可省：不建索引的成品检索不到，「可复用」即落空。
        """
        path = Path(video_path)
        if not path.is_file():
            raise NotFoundException(f"渲染产物不存在：{path}")

        knowledge_base = base or self.get_or_create_render_output_base(account)

        content = path.read_bytes()
        # 成品是系统写入，按设计 §6.3 走「宽让」配额：剩余 > 0 即放行（允许溢出），
        # 避免因配额差一点让整轮渲染白干；恰好为 0 仍拒绝。
        upload_file = self._get_cos_service().upload_bytes(
            filename=path.name,
            content=content,
            account_id=account.id,
            mime_type="video/mp4",
            allow_overflow=True,
        )

        document = self.create(
            KnowledgeDocument,
            knowledge_base_id=knowledge_base.id,
            owner_account_id=account.id,
            name=(name or path.stem),
            content_type="document",
            source_type=KnowledgeCreatedFrom.RENDER_OUTPUT.value,
            source_id=str(upload_file.id),
            upload_file_id=upload_file.id,
            partition_id=None,
            media_type=DocumentMediaType.VIDEO.value,
            parse_profile={},
            metadata_={
                "upload_file_id": str(upload_file.id),
                "operation_context": OperationContext.USER.value,
            },
            character_count=0,
            status=DocumentStatus.WAITING.value,
        )

        self._get_knowledge_indexing_service().build_document(document.id, account)
        return document

    def build_output_artifact(self, document: KnowledgeDocument) -> dict:
        """把成品文档转成对话侧可播放的 artifact 载荷。

        为什么单独成方法：产物入库后需要「回给对话前端一个可播放地址」，
        而 store_render_output 的返回值（KnowledgeDocument）不含 URL，
        故在此按文档关联的 upload_file 生成访问地址。

        URL 生成**不传 download_name**：传了会带上
        `response-content-disposition: attachment`，浏览器会把视频当附件下载
        而不是内联播放——那正好与「成片预览」的目标相反。
        """
        upload_file = None
        upload_file_id = getattr(document, "upload_file_id", None)
        if upload_file_id:
            upload_file = self.db.session.query(UploadFile).filter(
                UploadFile.id == upload_file_id,
            ).one_or_none()
        if upload_file is None:
            return {}

        key = str(getattr(upload_file, "key", "") or "")
        if not key:
            return {}

        try:
            url = self._get_cos_service().get_file_url(key)
        except Exception:
            logging.warning(
                "成品访问地址生成失败 document_id=%s key=%s", document.id, key, exc_info=True,
            )
            return {}
        if not url:
            return {}

        name = str(getattr(document, "name", "") or "") or str(getattr(upload_file, "name", "") or "")
        artifact = {
            "id": str(document.id),
            "name": name,
            "url": url,
            "mime_type": str(getattr(upload_file, "mime_type", "") or "video/mp4"),
        }
        extension = str(getattr(upload_file, "extension", "") or "")
        if extension:
            artifact["extension"] = extension.lstrip(".")
        size = getattr(upload_file, "size", None)
        if size:
            try:
                artifact["size"] = int(size)
            except (TypeError, ValueError):
                pass
        return artifact

    @staticmethod
    def _assert_not_render_output_base(knowledge_base: KnowledgeBase) -> None:
        """成品库为系统托管，禁止任何手动上传（设计 §4.1）。

        系统自身的成品写入走 store_render_output()，不经此校验——
        本校验只拦「用户上传」这条路径。
        """
        if (
            getattr(knowledge_base, "created_from", None)
            == KnowledgeCreatedFrom.RENDER_OUTPUT.value
        ):
            raise ForbiddenException("成品库为系统托管，不支持手动上传素材，请在素材库中上传")

    @staticmethod
    def _assert_media_type_allowed(knowledge_base: KnowledgeBase, extension: str) -> None:
        """板块类型硬约束：扩展名必须属于该板块允许的媒体类型。

        板块 base_type 为空时视为 mixed（兼容存量库）；扩展名为空时不拦截。
        """
        normalized = (extension or "").strip().lower()
        if not normalized:
            return
        base_type = getattr(knowledge_base, "base_type", None) or KnowledgeBaseType.MIXED.value
        allowed = allowed_extensions_for_base_type(base_type)
        if normalized not in allowed:
            raise ValidateErrorException(
                f"当前知识库不允许上传 .{normalized} 文件",
                {"file": [f"板块类型 {base_type} 允许的扩展名：{'/'.join(allowed)}"]},
            )

    def assert_upload_allowed(self, knowledge_base_id, extension: str, account: Account) -> KnowledgeBase:
        """预校验某扩展名能否上传到指定知识库；不合格抛 ValidateErrorException。

        供分片上传在合并前预校验使用，避免先落盘后拒绝造成的浪费与残留。
        """
        knowledge_base = self.get_accessible_base(knowledge_base_id, account)
        self._assert_not_render_output_base(knowledge_base)
        self._assert_media_type_allowed(knowledge_base, extension)
        return knowledge_base

    def trigger_document_l2(
            self,
            knowledge_base_id: UUID,
            document_id: UUID,
            account: Account,
            start_sec: float | None = None,
            end_sec: float | None = None,
    ) -> dict:
        """按需触发某素材的 L2 深度解析（用户显式要求）。

        L1 上传即跑、保证素材「能被找到」；L2 逐帧视觉详述最贵，故**只在显式要求时触发**，
        不做定时轮询。派发走 Celery，不可用时回退同步执行，避免请求静默丢失。

        `start_sec` / `end_sec` 均给出时按显式区间密抽（规格 §2「A+B」）；
        缺省时由 L1 命中帧的 `time_offset` 自动推导窗口。

        校验顺序与 `get_document_detail` 一致：先校验知识库归属，再校验文档是否属于该库，
        防止越权触发他人素材的付费解析。
        """
        # 1.校验知识库归属
        self.get_user_content_base(knowledge_base_id, account)

        # 2.查询文档并校验归属
        document = self.get(KnowledgeDocument, document_id)
        if document is None or str(document.knowledge_base_id) != str(knowledge_base_id):
            raise NotFoundException("该文档不存在，请核实后重试")

        # 3.派发 L2 任务（Celery 优先，不可用时同步兜底）
        return self._dispatch_document_l2(
            document.id, start_sec=start_sec, end_sec=end_sec
        )

    def _dispatch_document_l2(
        self, document_id, *, start_sec: float | None = None, end_sec: float | None = None
    ) -> dict:
        """派发 L2 深度解析：优先 Celery 后台执行，不可用时回退同步，保证解析不丢失。"""
        try:
            from internal.task.knowledge_l2_tasks import build_document_l2_task

            build_document_l2_task.delay(
                str(document_id), start_sec=start_sec, end_sec=end_sec
            )
            logging.info("L2 深度解析已派发 Celery document_id=%s", document_id)
            return {"document_id": str(document_id), "dispatched": True}
        except Exception:
            logging.warning(
                "L2 派发 Celery 失败，回退同步执行 document_id=%s", document_id, exc_info=True,
            )
            return self._get_knowledge_indexing_service().build_document_l2(
                document_id, start_sec=start_sec, end_sec=end_sec
            )

    def _get_cos_service(self):
        from .cos_service import CosService
        return current_app.injector.get(CosService)

    def _get_knowledge_indexing_service(self):
        from .knowledge_indexing_service import KnowledgeIndexingService
        return current_app.injector.get(KnowledgeIndexingService)

    def _get_knowledge_vector_service(self):
        """延迟获取知识库向量服务，避免循环依赖"""
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
        """根据请求创建用户内容知识库（含板块类型、分区模式与图标设置）"""
        # 1.创建知识库基础记录
        # req 可能是 wtforms 表单，也可能是路由层构造的 SimpleNamespace，故用 _req_value 安全取值
        knowledge_base = self.create_user_content_base(
            name=req.name.data,
            account=account,
            description=req.description.data or "",
            base_type=self._req_value(req, "base_type", KnowledgeBaseType.MIXED.value),
            partition_mode=self._req_value(req, "partition_mode", PartitionMode.NONE.value),
        )

        # 2.将图标 URL 写入 settings JSONB 字段
        settings = dict(knowledge_base.settings or {})
        settings["icon"] = req.icon.data

        # 3.自动选择 embedding 模型（用户不能自选，由系统按维度优先+健康度选择）
        selected_model = self.auto_select_embedding_model()

        self.update(knowledge_base, settings=settings, embedding_model_id=selected_model.id)

        return knowledge_base

    @staticmethod
    def _req_value(req, field: str, default: str) -> str:
        """从请求对象安全取字段值（兼容 wtforms 的 .data 与 SimpleNamespace 裸值）。"""
        raw = getattr(req, field, None)
        if raw is None:
            return default
        value = getattr(raw, "data", raw)
        return value or default

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

    def delete_user_content_base(self, knowledge_base_id: UUID, account: Account, *, retention_days: int | None = None, agent_id=None) -> KnowledgeBase:
        """删除 user_content 知识库：进入回收站（默认留存 30 天），用户/管理员可在回收站恢复。

        用户删除后资源立即从当前账号视角消失，底层存储文件在留存期内保留，
        由回收站定时任务在留存期结束后统一销毁。
        """
        # 1.校验知识库归属
        knowledge_base = self.get_user_content_base(knowledge_base_id, account)

        # 2.写入回收站并物理删除原记录（文档/分段/向量/上传文件记录一并清理）
        try:
            from internal.service.recycle_bin_service import RecycleBinService
            deleted = RecycleBinService().delete_resource(
                resource_type="knowledge_base",
                resource_id=knowledge_base.id,
                resource_key=str(knowledge_base.id),
                resource_name=knowledge_base.name,
                deleted_by=account.id,
                deleted_by_type="agent" if agent_id else "user",
                retention_days=retention_days,
                agent_id=agent_id,
            )
        except Exception as e:
            logging.exception(
                "删除知识库失败 knowledge_base_id=%s, 错误: %s",
                knowledge_base_id, str(e),
            )
            raise FailException("删除知识库失败，请稍后重试")
        if not deleted:
            raise NotFoundException("知识库不存在，请核实后重试")

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

        # 3.组装响应数据
        return self._build_hit_result(lc_documents)

    def _build_hit_result(self, lc_documents) -> list[dict]:
        """将检索结果组装为命中测试响应数据（按检索顺序排序片段并携带匹配分数）"""
        # 1.提取 segment_id 列表并查询对应的片段与文档信息
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

        # 2.按检索结果顺序排序片段
        sorted_segments = [
            segment_dict[str(lc_document.metadata["segment_id"])]
            for lc_document in lc_documents
            if str(lc_document.metadata["segment_id"]) in segment_dict
        ]

        # 3.组装响应数据
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
        partition_id = getattr(getattr(req, "partition_id", None), "data", None)
        if partition_id:
            filters.append(KnowledgeDocument.partition_id == partition_id)

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

        # 6.为每个文档注入预览字段（缩略图 / 播放直链）
        self._enrich_document_previews(documents)

        return documents, paginator

    def _enrich_document_previews(self, documents: list[KnowledgeDocument]) -> None:
        """给文档注入预览字段（frame_url 缩略图 / playback_url 视频播放地址）。

        数据源：分段的 `metadata->>'frame_url'`（COS key，需签名）与文档关联的
        `upload_file.key`（成品播放直链）。注入发生在 schema 序列化之前，schema 用
        getattr 读取，与既有 segment_count 注入同款模式。
        """
        if not documents:
            return
        cos_service = self._get_cos_service()
        doc_ids = [document.id for document in documents]

        frame_rows = (
            self.db.session.query(
                KnowledgeSegment.knowledge_document_id,
                KnowledgeSegment.metadata_["frame_url"].astext,
            )
            .filter(
                KnowledgeSegment.knowledge_document_id.in_(doc_ids),
                KnowledgeSegment.metadata_["frame_url"].astext != "",
            )
            .order_by(KnowledgeSegment.knowledge_document_id, KnowledgeSegment.position)
            .distinct(KnowledgeSegment.knowledge_document_id)
            .all()
        )
        frame_urls: dict[str, str] = {}
        for doc_id, key in frame_rows:
            try:
                url = cos_service.get_file_url(str(key))
            except Exception:
                logging.warning(
                    "帧缩略图地址生成失败 document_id=%s key=%s", doc_id, key, exc_info=True,
                )
                continue
            if url:
                frame_urls[str(doc_id)] = url

        upload_ids = [
            document.upload_file_id
            for document in documents
            if document.media_type == DocumentMediaType.VIDEO.value
            and document.upload_file_id
        ]
        uploads: dict[str, UploadFile] = {}
        if upload_ids:
            upload_rows = (
                self.db.session.query(UploadFile)
                .filter(UploadFile.id.in_(upload_ids))
                .all()
            )
            uploads = {str(row.id): row for row in upload_rows}

        for document in documents:
            setattr(document, "frame_url", frame_urls.get(str(document.id), ""))
            playback_url = ""
            upload = uploads.get(str(document.upload_file_id or ""))
            if upload is not None:
                key = str(getattr(upload, "key", "") or "")
                if key:
                    try:
                        playback_url = cos_service.get_file_url(key) or ""
                    except Exception:
                        logging.warning(
                            "播放直链生成失败 document_id=%s key=%s", document.id, key, exc_info=True,
                        )
                        playback_url = ""
            setattr(document, "playback_url", playback_url)

    def _enrich_segment_previews(self, segments: list[KnowledgeSegment]) -> None:
        """给分段注入预览字段（frame_url 缩略图 / 时间线元数据透出）。

        数据源：分段自身的 `metadata` JSONB——视觉时间线分段写入
        `source=vision_timeline`、`start_sec`/`end_sec`、`frame_url`（COS key）、
        `speech_text`。frame_url 需签名后注入，其余字段原样透出。
        """
        if not segments:
            return
        cos_service = self._get_cos_service()
        for segment in segments:
            metadata = getattr(segment, "metadata_", None) or {}
            key = str(metadata.get("frame_url", "") or "")
            frame_url = ""
            if key:
                try:
                    frame_url = cos_service.get_file_url(key) or ""
                except Exception:
                    logging.warning(
                        "分段帧缩略图地址生成失败 segment_id=%s key=%s",
                        getattr(segment, "id", None),
                        key,
                        exc_info=True,
                    )
                    frame_url = ""
            setattr(segment, "frame_url", frame_url)
            setattr(segment, "start_sec", float(metadata.get("start_sec", 0.0) or 0.0))
            setattr(segment, "end_sec", float(metadata.get("end_sec", 0.0) or 0.0))
            setattr(segment, "source", str(metadata.get("source", "") or ""))
            setattr(segment, "speech_text", str(metadata.get("speech_text", "") or ""))

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

        # 4.补充预览字段（缩略图 / 播放直链）
        self._enrich_document_previews([document])

        return document

    def delete_document(
            self,
            knowledge_base_id: UUID,
            document_id: UUID,
            account: Account,
            *,
            retention_days: int | None = None,
            agent_id=None,
    ) -> KnowledgeDocument:
        """删除知识库下指定文档：进入回收站（默认留存 30 天），用户/管理员可在回收站恢复。"""
        # 1.校验知识库归属
        self.get_user_content_base(knowledge_base_id, account)

        # 2.查询文档并校验归属
        document = self.get(KnowledgeDocument, document_id)
        if document is None or str(document.knowledge_base_id) != str(knowledge_base_id):
            raise NotFoundException("该文档不存在，请核实后重试")

        # 3.写入回收站并物理删除原记录（向量/分段/文档/上传文件记录一并清理；
        #    底层存储对象在留存期结束后由回收站定时任务统一销毁，留存期内可恢复）
        try:
            from internal.service.recycle_bin_service import RecycleBinService
            deleted = RecycleBinService().delete_resource(
                resource_type="knowledge_document",
                resource_id=document.id,
                resource_key=str(document.id),
                resource_name=document.name,
                deleted_by=account.id,
                deleted_by_type="agent" if agent_id else "user",
                retention_days=retention_days,
                agent_id=agent_id,
            )
        except Exception as e:
            logging.exception(
                "删除知识库文档失败 document_id=%s, 错误: %s",
                document_id, str(e),
            )
            raise FailException("删除文档失败，请稍后重试")
        if not deleted:
            raise NotFoundException("该文档不存在，请核实后重试")

        return document

    def _delete_document_data(self, document: KnowledgeDocument, *, delete_upload_file: bool = True) -> None:
        """物理删除文档的向量数据、分段记录与文档记录（不校验归属，供用户端与 admin 端复用）

        若文档关联了上传文件，默认同步删除文件记录与底层存储对象，
        避免删除文档后文件残留在存储文件列表中。
        """
        document_id = document.id
        upload_file_id = getattr(document, "upload_file_id", None)
        upload_file = None
        if delete_upload_file and upload_file_id is not None:
            upload_file = self.db.session.query(UploadFile).filter(
                UploadFile.id == upload_file_id,
            ).one_or_none()
        try:
            # 1.查询该文档下的所有片段，用于清理 pgvector 向量
            segments = self.db.session.query(KnowledgeSegment).filter(
                KnowledgeSegment.knowledge_document_id == document_id,
            ).all()

            # 2.清理 pgvector 中的向量数据
            knowledge_vector_service = self._get_knowledge_vector_service()
            for segment in segments:
                try:
                    knowledge_vector_service.remove_segment(segment)
                except Exception as e:
                    logging.warning(
                        "清理文档片段向量失败 segment_id=%s, 错误: %s",
                        segment.id, str(e),
                    )

            # 3.删除片段记录、文档记录与上传文件记录
            with self.db.auto_commit():
                self.db.session.query(KnowledgeSegment).filter(
                    KnowledgeSegment.knowledge_document_id == document_id,
                ).delete(synchronize_session=False)
                self.db.session.delete(document)
                if upload_file is not None:
                    self.db.session.delete(upload_file)

            # 4.删除底层存储对象（local 物理文件 / COS、OSS 对象）
            if upload_file is not None:
                try:
                    from internal.service.storage.storage_migration_service import _delete_object
                    backend = (upload_file.storage_backend or "local").strip() or "local"
                    _delete_object(backend, upload_file.key)
                except Exception as e:
                    logging.warning(
                        "删除文档关联的存储文件失败 key=%s, 错误: %s",
                        upload_file.key, str(e),
                    )
        except Exception as e:
            logging.exception(
                "删除知识库文档失败 document_id=%s, 错误: %s",
                document_id, str(e),
            )
            raise FailException("删除文档失败，请稍后重试")

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
