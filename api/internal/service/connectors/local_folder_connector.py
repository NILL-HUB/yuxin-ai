import logging
import os
import tempfile
from typing import Any

from internal.entity.knowledge_entity import ExternalAuthorizationStatus
from internal.model.knowledge import ExternalDataSource

from .base_connector import BaseConnector


logger = logging.getLogger(__name__)

_ALLOWED_EXTENSIONS = (".md", ".txt", ".markdown")


def _load_allowed_roots() -> list[str]:
    raw = os.getenv("LOCAL_FOLDER_CONNECTOR_ALLOWED_ROOTS", "")
    roots = [part.strip() for part in raw.split(";")]
    roots = [os.path.realpath(root) for root in roots if root]
    if not roots:
        roots = [os.path.realpath(tempfile.gettempdir())]
    return roots


def _is_within_allowed_roots(resolved_path: str, allowed_roots: list[str]) -> bool:
    for root in allowed_roots:
        try:
            common = os.path.commonpath([resolved_path, root])
        except ValueError:
            continue
        if common == root:
            return True
    return False


class LocalFolderConnector(BaseConnector):
    def authorize(
        self,
        data_source: ExternalDataSource,
        auth_config: dict[str, Any],
    ) -> str:
        folder_path = self._resolve_folder(
            auth_config.get("folder_path") or data_source.config.get("folder_path", "")
        )
        if not folder_path or not os.path.isdir(folder_path):
            raise ValueError("文件夹路径无效或不存在")
        return ExternalAuthorizationStatus.GRANTED.value

    def sync(self, data_source: ExternalDataSource) -> list[dict[str, str]]:
        folder_path = self._resolve_folder(data_source.config.get("folder_path", ""))
        if not folder_path or not os.path.isdir(folder_path):
            raise ValueError("文件夹路径无效或不存在")
        documents: list[dict[str, str]] = []
        for filename in sorted(os.listdir(folder_path)):
            if not filename.endswith(_ALLOWED_EXTENSIONS):
                continue
            filepath = os.path.realpath(os.path.join(folder_path, filename))
            if not _is_within_allowed_roots(filepath, _load_allowed_roots()):
                logger.warning("本地文件夹连接器拒绝越界文件读取: %s", filepath)
                continue
            if not os.path.isfile(filepath):
                continue
            with open(filepath, "r", encoding="utf-8") as f:
                content = f.read()
            documents.append({
                "name": filename,
                "content": content,
                "source_url": f"file://{filepath}",
            })
        return documents

    @staticmethod
    def _resolve_folder(folder_path: str) -> str:
        if not folder_path:
            return ""
        resolved = os.path.realpath(folder_path)
        allowed_roots = _load_allowed_roots()
        if not _is_within_allowed_roots(resolved, allowed_roots):
            logger.warning("本地文件夹连接器拒绝越界目录访问: %s", resolved)
            raise ValueError("文件夹路径不在允许的根目录范围内")
        return resolved
