from dataclasses import dataclass
import math

from injector import inject

from internal.entity.knowledge_entity import KnowledgeCreatedFrom, KnowledgeScope, OperationContext, VisibilityScope
from internal.exception import ForbiddenException, NotFoundException
from internal.model import Account, AdminUser, KnowledgeBase
from pkg.sqlalchemy import SQLAlchemy
from .base_service import BaseService
from .knowledge_base_service import KnowledgeBaseService


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
        query = (
            self.db.session.query(KnowledgeBase)
            .filter(KnowledgeBase.knowledge_scope == KnowledgeScope.SYSTEM.value)
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
    ) -> None:
        knowledge_base = self.get_system_knowledge(knowledge_base_id)
        # 记录变更前数据用于审计
        before_data = {
            "name": knowledge_base.name,
            "description": knowledge_base.description,
            "enabled": getattr(knowledge_base, "enabled", True),
        }
        self.update(knowledge_base, enabled=False)
        # 记录系统级知识库删除审计日志
        self._emit_audit(
            admin_user_id=getattr(admin_user, "id", None),
            action="delete",
            resource_id=str(getattr(knowledge_base, "id", "")),
            before_data=before_data,
        )

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
