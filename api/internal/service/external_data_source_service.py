from datetime import UTC, datetime

from injector import inject

from internal.entity.knowledge_entity import (
    ExternalAuthorizationStatus,
    ExternalSyncStatus,
    KnowledgeScope,
)
from internal.exception import NotFoundException
from internal.model import Account, ExternalDataSource, KnowledgeBase, KnowledgeDocument, KnowledgeSegment
from internal.service.external_data_source_connector_factory import ConnectorFactory
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
        self.connector_factory = ConnectorFactory()

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

    def authorize_data_source(
        self,
        data_source_id,
        account: Account,
        auth_config: dict,
    ) -> ExternalDataSource:
        data_source = self._get_owned_data_source(data_source_id, account)
        connector = self.connector_factory.get_connector(data_source.source_type)
        data_source.authorization_status = connector.authorize(data_source, auth_config)
        return data_source

    def manual_sync(self, data_source_id, account: Account) -> dict[str, object]:
        data_source = self._get_owned_data_source(data_source_id, account)
        if data_source.authorization_status != ExternalAuthorizationStatus.GRANTED.value:
            raise ValueError("数据源未授权，请先完成授权")
        connector = self.connector or self.connector_factory.get_connector(data_source.source_type)
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
        segment_count = 0
        for document in documents:
            content = document.get("content", "")
            knowledge_doc = self.create(
                KnowledgeDocument,
                knowledge_base_id=data_source.knowledge_base_id,
                owner_account_id=account.id,
                name=document.get("name", "external_document"),
                content_type="document",
                source_type=data_source.source_type,
                source_id=str(data_source.id),
                metadata_={"external_data_source_id": str(data_source.id)},
                character_count=len(content),
                status="completed",
            )
            segments = self._split_document(content)
            for idx, segment_text in enumerate(segments):
                self.create(
                    KnowledgeSegment,
                    knowledge_base_id=data_source.knowledge_base_id,
                    knowledge_document_id=knowledge_doc.id,
                    owner_account_id=account.id,
                    position=idx + 1,
                    content=segment_text,
                    keywords=[],
                    metadata_={"source": "external_sync"},
                    character_count=len(segment_text),
                    status="completed",
                    enabled=True,
                )
                segment_count += 1
            if document.get("cursor"):
                data_source.sync_cursor = document["cursor"]
        data_source.sync_status = ExternalSyncStatus.SUCCESS.value
        data_source.last_error = ""
        data_source.last_synced_at = datetime.now(UTC).replace(tzinfo=None)
        return {
            "sync_status": data_source.sync_status,
            "document_count": len(documents),
            "segment_count": segment_count,
        }

    def list_data_sources(self, account: Account, status: str = "") -> list[ExternalDataSource]:
        query = self.db.session.query(ExternalDataSource).filter_by(owner_account_id=account.id)
        if status:
            query = query.filter(ExternalDataSource.sync_status == status)
        return query.order_by(ExternalDataSource.created_at.desc()).all()

    def get_data_source(self, data_source_id, account: Account) -> ExternalDataSource:
        return self._get_owned_data_source(data_source_id, account)

    def delete_data_source(self, data_source_id, account: Account) -> None:
        data_source = self._get_owned_data_source(data_source_id, account)
        self.db.session.delete(data_source)

    def _get_owned_data_source(self, data_source_id, account: Account) -> ExternalDataSource:
        data_source = (
            self.db.session.query(ExternalDataSource)
            .filter_by(id=data_source_id)
            .one_or_none()
        )
        if data_source is None or data_source.owner_account_id != account.id:
            raise NotFoundException("外部数据源不存在")
        return data_source

    @staticmethod
    def _split_document(content: str, chunk_size: int = 500) -> list[str]:
        if not content:
            return []
        paragraphs = [p.strip() for p in content.split("\n\n") if p.strip()]
        if not paragraphs:
            paragraphs = [content.strip()]
        segments: list[str] = []
        current_chunk = ""
        for para in paragraphs:
            if len(current_chunk) + len(para) > chunk_size and current_chunk:
                segments.append(current_chunk)
                current_chunk = para
            else:
                current_chunk = f"{current_chunk}\n\n{para}" if current_chunk else para
        if current_chunk:
            segments.append(current_chunk)
        return segments

    @staticmethod
    def _can_bind_base(account: Account, knowledge_base: KnowledgeBase) -> bool:
        return (
            knowledge_base.knowledge_scope == KnowledgeScope.USER_CONTENT.value
            and knowledge_base.owner_account_id == account.id
        )
