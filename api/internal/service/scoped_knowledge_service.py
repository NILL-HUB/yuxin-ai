from dataclasses import dataclass

from injector import inject

from internal.entity.knowledge_entity import KnowledgeCreatedFrom, KnowledgeScope, OperationContext, VisibilityScope
from internal.exception import ForbiddenException
from internal.model import Account, AdminUser, KnowledgeBase, UserMemory
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
    ) -> KnowledgeBase:
        if admin_user is None:
            raise ForbiddenException("普通用户不能创建系统级知识")
        return self.create_system_base(
            name=name,
            admin_user=admin_user,
            description=description,
            created_from=KnowledgeCreatedFrom.ADMIN_CONFIG.value,
        )


@inject
@dataclass
class UserMemoryService(BaseService):
    db: SQLAlchemy

    def remember(
        self,
        *,
        account: Account,
        memory_type: str,
        content: str,
        confidence: int,
        created_from: str = KnowledgeCreatedFrom.CONVERSATION_MEMORY.value,
    ) -> UserMemory:
        return self.create(
            UserMemory,
            owner_account_id=account.id,
            memory_type=memory_type,
            content=content,
            confidence=confidence,
            status="active",
            created_from=created_from,
        )


@inject
@dataclass
class UserContentKnowledgeService(KnowledgeBaseService):
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
        bases = self.db.session.query(KnowledgeBase).filter(KnowledgeBase.enabled.is_(True)).all()
        return [base for base in bases if self._is_authorized_base(base, account)]

    @staticmethod
    def _is_authorized_base(base: KnowledgeBase, account: Account) -> bool:
        return base.knowledge_scope == KnowledgeScope.SYSTEM.value or (
            base.knowledge_scope in {
                KnowledgeScope.USER_MEMORY.value,
                KnowledgeScope.USER_CONTENT.value,
            }
            and base.owner_account_id == account.id
        )
