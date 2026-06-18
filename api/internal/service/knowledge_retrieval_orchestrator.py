from dataclasses import dataclass
from uuid import UUID

from injector import inject
from langchain_core.documents import Document as LCDocument

from internal.entity.knowledge_entity import KnowledgeScope
from internal.model import Account, KnowledgeBase
from pkg.sqlalchemy import SQLAlchemy
from .base_service import BaseService
from .retrieval_service import RetrievalService


_SYSTEM_FIRST_INTENTS = {"vertical_agent_task", "agent_operation"}
_MEMORY_FIRST_INTENTS = {"preference_query"}
_CONTENT_FIRST_INTENTS = {"content_query", "general_qa"}


@inject
@dataclass
class KnowledgeRetrievalOrchestrator(BaseService):
    db: SQLAlchemy
    retrieval_service: RetrievalService

    def retrieve(self, query: str, task_intent: str, account: Account) -> list[LCDocument]:
        priority_scopes = self._scope_priority(task_intent)
        merged: list[LCDocument] = []
        seen_segment_ids: set[str] = set()
        for scope in priority_scopes:
            base_ids = self._list_knowledge_base_ids(scope, account)
            if not base_ids:
                continue
            documents = self.retrieval_service.search_in_knowledge_base(
                knowledge_base_ids=base_ids,
                query=query,
                account_id=account.id,
            )
            for document in documents:
                segment_id = document.metadata.get("segment_id")
                if segment_id is not None:
                    if segment_id in seen_segment_ids:
                        continue
                    seen_segment_ids.add(segment_id)
                document.metadata["knowledge_scope"] = scope
                merged.append(document)
        return merged

    @staticmethod
    def _scope_priority(task_intent: str) -> list[str]:
        if task_intent in _SYSTEM_FIRST_INTENTS:
            return [KnowledgeScope.SYSTEM.value, KnowledgeScope.USER_CONTENT.value]
        if task_intent in _MEMORY_FIRST_INTENTS:
            return [KnowledgeScope.USER_MEMORY.value]
        return [KnowledgeScope.USER_CONTENT.value, KnowledgeScope.USER_MEMORY.value]

    def _list_knowledge_base_ids(self, scope: str, account: Account) -> list[UUID]:
        query = self.db.session.query(KnowledgeBase.id).filter(
            KnowledgeBase.knowledge_scope == scope,
            KnowledgeBase.enabled.is_(True),
        )
        if scope in {KnowledgeScope.USER_MEMORY.value, KnowledgeScope.USER_CONTENT.value}:
            query = query.filter(KnowledgeBase.owner_account_id == account.id)
        rows = query.all()
        return [row[0] for row in rows]
