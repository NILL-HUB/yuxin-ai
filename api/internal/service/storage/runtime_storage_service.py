"""运行时存储分发代理。

根据 ``storage_config`` 表中激活的后端，在请求时动态分发上传/下载/URL
生成请求到对应后端实现。取代原先启动时按 ``STORAGE_BACKEND`` 环境变量
固定绑定的方案，使 Admin 端切换存储后端后，**新上传文件立即进入新后端**。

下载/URL 生成优先按文件记录的 ``storage_backend`` 路由（历史文件仍可从
原后端访问），未命中记录时回退到当前激活后端。

与 ``ObjectStoragePort`` / ``CosService`` 两个 DI 绑定对接，
保持既有调用方（handler / agent / 记忆系统等）无需改动即可路由到
运行时激活的后端。
"""
import logging
from dataclasses import dataclass

from injector import inject

from internal.exception import FailException
from internal.model import UploadFile
from internal.service.upload_file_service import UploadFileService
from internal.service.storage.storage_config_service import StorageConfigService
from pkg.sqlalchemy import SQLAlchemy

logger = logging.getLogger(__name__)


@inject
@dataclass
class RuntimeStorageProxy:
    """运行时存储分发代理。"""

    upload_file_service: UploadFileService
    storage_config_service: StorageConfigService
    db: SQLAlchemy

    def _resolve_backend(self) -> str:
        return self.storage_config_service.get_active_backend()

    def _resolve_file_backend(self, key: str) -> str | None:
        """按对象 key 反查文件记录的后端（供下载/URL 路由）。

        有 storage_backend 的记录按其路由；历史文件（为空）归属 legacy
        后端（STORAGE_BACKEND 环境变量），保证切换激活后端后旧文件仍可访问。
        """
        try:
            file = self.db.session.query(UploadFile).filter(UploadFile.key == key).first()
        except Exception:
            logger.warning("resolve file backend failed: key=%s", key, exc_info=True)
            return None
        if file is None:
            return None
        backend = (file.storage_backend or "").strip().lower()
        if backend:
            return backend
        import os
        return (os.getenv("STORAGE_BACKEND") or "local").strip().lower()

    def _get_service(self, backend: str | None = None):
        """返回指定后端（默认激活后端）的服务实例。"""
        backend = (backend or self._resolve_backend()).strip().lower()

        if backend == "local":
            from internal.service.storage.local_storage_service import LocalStorageService
            return LocalStorageService(upload_file_service=self.upload_file_service)

        if backend == "cos":
            from internal.service.cos_service import CosService
            return CosService(upload_file_service=self.upload_file_service)

        if backend == "oss":
            from internal.service.storage.aliyun_oss_service import AliyunOSSService
            return AliyunOSSService(upload_file_service=self.upload_file_service)

        raise FailException(f"不支持的存储后端: {backend}（可选值: local / cos / oss）")

    # ------------------------------------------------------------------
    # 上传（跟随激活后端）
    # ------------------------------------------------------------------
    def upload_file(self, file, only_image: bool = False, account=None):
        """上传文件到当前激活后端并创建 UploadFile 记录。"""
        return self._get_service().upload_file(file, only_image, account)

    def upload_bytes(
        self,
        *,
        filename: str,
        content: bytes,
        account_id,
        mime_type: str | None = None,
        folder: str = "artifacts",
    ):
        """上传内存字节到当前激活后端并创建 UploadFile 记录。"""
        return self._get_service().upload_bytes(
            filename=filename,
            content=content,
            account_id=account_id,
            mime_type=mime_type,
            folder=folder,
        )

    def upload_bytes_without_record(
        self,
        *,
        filename: str,
        content: bytes,
        folder: str = "generated-images",
    ) -> str:
        """上传内存字节到当前激活后端，不创建记录，返回 URL。"""
        return self._get_service().upload_bytes_without_record(
            filename=filename,
            content=content,
            folder=folder,
        )

    # ------------------------------------------------------------------
    # 下载 / URL（按文件记录后端路由，支持显式指定后端）
    # ------------------------------------------------------------------
    def download_file(self, key: str, target_file_path: str, backend: str | None = None) -> None:
        """下载文件到本地路径。

        优先使用文件记录的 storage_backend，其次显式 backend，最后激活后端。
        """
        resolved = backend or self._resolve_file_backend(key)
        return self._get_service(resolved).download_file(key, target_file_path)

    def get_file_url(self, key: str, download_name: str | None = None, backend: str | None = None) -> str:
        """生成文件访问 URL，路由规则同 download_file。"""
        resolved = backend or self._resolve_file_backend(key)
        return self._get_service(resolved).get_file_url(key, download_name)
