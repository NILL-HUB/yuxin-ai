from abc import ABC, abstractmethod
from typing import Any

from internal.entity.knowledge_entity import ExternalAuthorizationStatus
from internal.model.knowledge import ExternalDataSource


class ExternalConnectorError(Exception):
    """外部数据源连接器调用异常

    用于连接器在调用外部 API 失败（网络异常、鉴权失败、接口返回错误码等）时抛出，
    上层 manual_sync 会捕获该异常并记录到 ExternalDataSource.last_error 字段，
    不中断整体同步流程。
    """

    pass


class BaseConnector(ABC):
    @abstractmethod
    def authorize(
        self,
        data_source: ExternalDataSource,
        auth_config: dict[str, Any],
        config: dict[str, Any] | None = None,
    ) -> str:
        ...

    @abstractmethod
    def sync(
        self,
        data_source: ExternalDataSource,
        config: dict[str, Any] | None = None,
    ) -> list[dict[str, str]]:
        """config 为空时回退读取 data_source.config（保持既有调用兼容）。"""
        ...

    @staticmethod
    def _granted() -> str:
        return ExternalAuthorizationStatus.GRANTED.value

    @staticmethod
    def _revoked() -> str:
        return ExternalAuthorizationStatus.REVOKED.value
