from dataclasses import dataclass
from uuid import UUID as uuid_UUID
import uuid

from injector import inject

from internal.entity.knowledge_entity import KnowledgeCreatedFrom, KnowledgeScope, OperationContext, VisibilityScope
from internal.exception import ForbiddenException, NotFoundException
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

    def list_system_knowledge(self) -> list[KnowledgeBase]:
        return (
            self.db.session.query(KnowledgeBase)
            .filter(KnowledgeBase.knowledge_scope == KnowledgeScope.SYSTEM.value)
            .order_by(KnowledgeBase.created_at.desc())
            .all()
        )

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
    ) -> KnowledgeBase:
        knowledge_base = self.get_system_knowledge(knowledge_base_id)
        update_kwargs: dict = {}
        if name is not None:
            update_kwargs["name"] = name
        if description is not None:
            update_kwargs["description"] = description
        if enabled is not None:
            update_kwargs["enabled"] = enabled
        if update_kwargs:
            self.update(knowledge_base, **update_kwargs)
        return knowledge_base

    def delete_system_knowledge(self, knowledge_base_id) -> None:
        knowledge_base = self.get_system_knowledge(knowledge_base_id)
        self.update(knowledge_base, enabled=False)


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
        memory = self.create(
            UserMemory,
            owner_account_id=account.id,
            memory_type=memory_type,
            content=content,
            confidence=confidence,
            status="active",
            created_from=created_from,
        )
        try:
            self._get_memory_vector_service().index_memory(memory)
        except Exception:
            import logging
            logging.getLogger(__name__).warning("记忆写入向量库失败，不影响主流程", exc_info=True)
        return memory

    def list_memories(self, account: Account) -> list[UserMemory]:
        return (
            self.db.session.query(UserMemory)
            .filter_by(owner_account_id=account.id)
            .order_by(UserMemory.created_at.desc())
            .all()
        )

    def get_memory(self, memory_id: uuid.UUID, account: Account) -> UserMemory | None:
        return (
            self.db.session.query(UserMemory)
            .filter_by(id=memory_id, owner_account_id=account.id)
            .one_or_none()
        )

    def update_memory(
        self,
        memory_id: uuid.UUID,
        account: Account,
        *,
        content: str | None = None,
        memory_type: str | None = None,
        enabled: bool = True,
    ) -> UserMemory | None:
        memory = self.get_memory(memory_id, account)
        if memory is None:
            return None
        if content is not None:
            memory.content = content
        if memory_type is not None:
            memory.memory_type = memory_type
        memory.status = "active" if enabled else "disabled"
        self.db.session.commit()
        try:
            self._get_memory_vector_service().index_memory(memory)
        except Exception:
            import logging
            logging.getLogger(__name__).warning("记忆更新向量库失败，不影响主流程", exc_info=True)
        return memory

    def delete_memory(self, memory_id: uuid.UUID, account: Account) -> bool:
        memory = self.get_memory(memory_id, account)
        if memory is None:
            return False
        try:
            self._get_memory_vector_service().remove_memory(memory)
        except Exception:
            import logging
            logging.getLogger(__name__).warning("记忆删除向量库失败，不影响主流程", exc_info=True)
        self.db.session.delete(memory)
        self.db.session.commit()
        return True

    def recall_relevant_memories(
        self, account: Account, query: str, top_k: int = 5
    ) -> list[dict]:
        results = self._get_memory_vector_service().search_relevant_memories(
            account, query, top_k=top_k
        )
        memory_ids = [r["memory_id"] for r in results if r.get("memory_id")]
        active_map: dict[str, UserMemory] = {}
        if memory_ids:
            rows = (
                self.db.session.query(UserMemory)
                .filter(
                    UserMemory.id.in_([uuid.UUID(mid) for mid in memory_ids]),
                    UserMemory.owner_account_id == account.id,
                    UserMemory.status == "active",
                )
                .all()
            )
            active_map = {str(row.id): row for row in rows}
        recalled: list[dict] = []
        for r in results:
            mid = r.get("memory_id")
            if mid and mid in active_map:
                recalled.append(r)
        return recalled

    def _get_memory_vector_service(self):
        from flask import current_app
        from internal.service.memory_vector_service import MemoryVectorService
        return current_app.injector.get(MemoryVectorService)


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
