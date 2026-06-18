from internal.entity.knowledge_entity import ExternalSourceType
from internal.service.connectors.base_connector import BaseConnector
from internal.service.connectors.github_connector import GithubConnector
from internal.service.connectors.lark_connector import LarkConnector
from internal.service.connectors.local_folder_connector import LocalFolderConnector
from internal.service.connectors.notion_connector import NotionConnector


class ConnectorFactory:
    _registry: dict[str, type[BaseConnector]] = {
        ExternalSourceType.LARK.value: LarkConnector,
        ExternalSourceType.NOTION.value: NotionConnector,
        ExternalSourceType.DRIVE.value: LocalFolderConnector,
        ExternalSourceType.GITHUB.value: GithubConnector,
        ExternalSourceType.ENTERPRISE_KNOWLEDGE.value: LocalFolderConnector,
    }

    def get_connector(self, source_type: str) -> BaseConnector:
        connector_cls = self._registry.get(source_type)
        if connector_cls is None:
            raise ValueError(f"不支持的数据源类型: {source_type}")
        return connector_cls()
