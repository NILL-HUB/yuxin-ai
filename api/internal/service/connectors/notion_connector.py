from typing import Any

from internal.entity.knowledge_entity import ExternalAuthorizationStatus
from internal.model.knowledge import ExternalDataSource

from .base_connector import BaseConnector


class NotionConnector(BaseConnector):
    def authorize(
        self,
        data_source: ExternalDataSource,
        auth_config: dict[str, Any],
    ) -> str:
        integration_token = (
            auth_config.get("integration_token")
            or data_source.config.get("integration_token", "")
        )
        if not integration_token:
            raise ValueError("Notion 连接需要 integration_token")
        return ExternalAuthorizationStatus.GRANTED.value

    def sync(self, data_source: ExternalDataSource) -> list[dict[str, str]]:
        documents = data_source.config.get("preset_documents", [])
        return [
            {
                "name": doc.get("name", doc.get("title", "notion_document")),
                "content": doc.get("content", ""),
                "source_url": doc.get("source_url", doc.get("url", "")),
            }
            for doc in documents
        ]
