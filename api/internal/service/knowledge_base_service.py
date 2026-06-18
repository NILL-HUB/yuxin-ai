from dataclasses import dataclass

from injector import inject

from internal.entity.knowledge_entity import KnowledgeCreatedFrom, KnowledgeScope, OperationContext, VisibilityScope
from internal.exception import ForbiddenException, NotFoundException, ValidateErrorException
from internal.model import Account, AdminUser, KnowledgeBase
from pkg.sqlalchemy import SQLAlchemy
from .base_service import BaseService


@inject
@dataclass
class KnowledgeBaseService(BaseService):
    db: SQLAlchemy

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
            visibility_scope=VisibilityScope.INTERNAL.value,
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
