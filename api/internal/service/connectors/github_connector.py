from typing import Any

from internal.entity.knowledge_entity import ExternalAuthorizationStatus
from internal.model.knowledge import ExternalDataSource

from .base_connector import BaseConnector


class GithubConnector(BaseConnector):
    def authorize(
        self,
        data_source: ExternalDataSource,
        auth_config: dict[str, Any],
    ) -> str:
        token = auth_config.get("token") or data_source.config.get("token", "")
        repo = auth_config.get("repo") or data_source.config.get("repo", "")
        if not token or not repo:
            raise ValueError("GitHub 连接需要 token 和 repo（owner/repo 格式）")
        if "/" not in repo:
            raise ValueError("repo 需为 owner/repo 格式")
        return ExternalAuthorizationStatus.GRANTED.value

    def sync(self, data_source: ExternalDataSource) -> list[dict[str, str]]:
        documents = data_source.config.get("preset_documents", [])
        return [
            {
                "name": doc.get("name", doc.get("title", "github_document")),
                "content": doc.get("content", ""),
                "source_url": doc.get("source_url", doc.get("url", "")),
            }
            for doc in documents
        ]
