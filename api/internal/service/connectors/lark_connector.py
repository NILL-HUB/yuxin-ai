from typing import Any

from internal.entity.knowledge_entity import ExternalAuthorizationStatus
from internal.model.knowledge import ExternalDataSource

from .base_connector import BaseConnector


class LarkConnector(BaseConnector):
    def authorize(
        self,
        data_source: ExternalDataSource,
        auth_config: dict[str, Any],
    ) -> str:
        app_id = auth_config.get("app_id") or data_source.config.get("app_id", "")
        app_secret = auth_config.get("app_secret") or data_source.config.get("app_secret", "")
        if not app_id or not app_secret:
            raise ValueError("飞书连接需要 app_id 和 app_secret")
        return ExternalAuthorizationStatus.GRANTED.value

    def sync(self, data_source: ExternalDataSource) -> list[dict[str, str]]:
        documents = data_source.config.get("preset_documents", [])
        return [
            {
                "name": doc.get("name", doc.get("title", "lark_document")),
                "content": doc.get("content", ""),
                "source_url": doc.get("source_url", doc.get("url", "")),
            }
            for doc in documents
        ]
