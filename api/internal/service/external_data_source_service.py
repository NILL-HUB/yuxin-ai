from datetime import UTC, datetime

from injector import inject

from internal.entity.knowledge_entity import (
    ExternalAuthorizationStatus,
    ExternalSyncStatus,
    KnowledgeScope,
)
from internal.exception import NotFoundException
from internal.model import Account, ExternalDataSource, KnowledgeBase, KnowledgeDocument
from pkg.sqlalchemy import SQLAlchemy
from .base_service import BaseService


class MockExternalConnector:
    def __init__(self, documents: list[dict[str, str]] | None = None):
        self.documents = documents or []

    def sync(self, data_source: ExternalDataSource) -> list[dict[str, str]]:
        return self.documents


class ExternalDataSourceService(BaseService):
    @inject
    def __init__(self, db: SQLAlchemy, connector=None):
        self.db = db
        self.connector = connector

    def create_connection(
        self,
        *,
        account: Account,
        knowledge_base: KnowledgeBase,
        source_type: str,
        source_name: str,
        config: dict,
    ) -> ExternalDataSource:
        if not self._can_bind_base(account, knowledge_base):
            raise NotFoundException("知识库不存在")
        return self.create(
            ExternalDataSource,
            owner_account_id=account.id,
            owner_admin_user_id=None,
            knowledge_base_id=knowledge_base.id,
            source_type=source_type,
            source_name=source_name,
            authorization_status=ExternalAuthorizationStatus.PENDING.value,
            sync_status=ExternalSyncStatus.IDLE.value,
            config=config,
        )

    def manual_sync(self, data_source_id, account: Account) -> dict[str, object]:
        data_source = (
            self.db.session.query(ExternalDataSource)
            .filter_by(id=data_source_id)
            .one_or_none()
        )
        if data_source is None or data_source.owner_account_id != account.id:
            raise NotFoundException("外部数据源不存在")
        connector = self.connector or MockExternalConnector()
        data_source.sync_status = ExternalSyncStatus.SYNCING.value
        try:
            documents = connector.sync(data_source)
        except Exception as exc:
            data_source.sync_status = ExternalSyncStatus.FAILED.value
            data_source.last_error = str(exc)
            return {
                "sync_status": data_source.sync_status,
                "document_count": 0,
                "last_error": data_source.last_error,
            }
        for document in documents:
            self.create(
                KnowledgeDocument,
                knowledge_base_id=data_source.knowledge_base_id,
                owner_account_id=account.id,
                name=document.get("name", "external_document"),
                content_type="document",
                source_type=data_source.source_type,
                source_id=str(data_source.id),
                metadata_={"external_data_source_id": str(data_source.id)},
                character_count=len(document.get("content", "")),
                status="completed",
            )
            if document.get("cursor"):
                data_source.sync_cursor = document["cursor"]
        data_source.sync_status = ExternalSyncStatus.SUCCESS.value
        data_source.last_error = ""
        data_source.last_synced_at = datetime.now(UTC).replace(tzinfo=None)
        return {
            "sync_status": data_source.sync_status,
            "document_count": len(documents),
        }

    @staticmethod
    def _can_bind_base(account: Account, knowledge_base: KnowledgeBase) -> bool:
        return (
            knowledge_base.knowledge_scope == KnowledgeScope.USER_CONTENT.value
            and knowledge_base.owner_account_id == account.id
        )
