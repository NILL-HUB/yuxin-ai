import os
from typing import Any

from internal.entity.knowledge_entity import ExternalAuthorizationStatus
from internal.model.knowledge import ExternalDataSource

from .base_connector import BaseConnector


class LocalFolderConnector(BaseConnector):
    def authorize(
        self,
        data_source: ExternalDataSource,
        auth_config: dict[str, Any],
    ) -> str:
        folder_path = auth_config.get("folder_path") or data_source.config.get("folder_path", "")
        if not folder_path or not os.path.isdir(folder_path):
            raise ValueError("文件夹路径无效或不存在")
        return ExternalAuthorizationStatus.GRANTED.value

    def sync(self, data_source: ExternalDataSource) -> list[dict[str, str]]:
        folder_path = data_source.config.get("folder_path", "")
        if not folder_path or not os.path.isdir(folder_path):
            raise ValueError("文件夹路径无效或不存在")
        documents: list[dict[str, str]] = []
        for filename in sorted(os.listdir(folder_path)):
            if filename.endswith((".md", ".txt", ".markdown")):
                filepath = os.path.join(folder_path, filename)
                with open(filepath, "r", encoding="utf-8") as f:
                    content = f.read()
                documents.append({
                    "name": filename,
                    "content": content,
                    "source_url": f"file://{filepath}",
                })
        return documents
