from abc import ABC, abstractmethod
from typing import Any

from internal.entity.knowledge_entity import ExternalAuthorizationStatus
from internal.model.knowledge import ExternalDataSource


class BaseConnector(ABC):
    @abstractmethod
    def authorize(
        self,
        data_source: ExternalDataSource,
        auth_config: dict[str, Any],
    ) -> str:
        ...

    @abstractmethod
    def sync(self, data_source: ExternalDataSource) -> list[dict[str, str]]:
        ...

    @staticmethod
    def _granted() -> str:
        return ExternalAuthorizationStatus.GRANTED.value

    @staticmethod
    def _revoked() -> str:
        return ExternalAuthorizationStatus.REVOKED.value
