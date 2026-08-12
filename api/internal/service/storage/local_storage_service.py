"""本地文件存储后端实现。

依据 ``STORAGE_BACKEND=local`` 启用，将上传文件持久化到容器本地磁盘，
并通过 ``/storage/local/<path:key>`` HTTP 路由对外提供访问。

文件存储路径格式：``{LOCAL_STORAGE_ROOT}/{year}/{month}/{day}/[folder/]{uuid}.{ext}``
默认根目录 ``storage/uploads``，通过 docker volume ``./volumes/app/storage:/app/api/storage`` 持久化。
"""

import hashlib
import logging
import mimetypes
import os
import uuid
from dataclasses import dataclass
from urllib.parse import quote

from injector import inject
from werkzeug.datastructures import FileStorage

from internal.entity.upload_file_entity import ALLOWED_DOCUMENT_EXTENSION, ALLOWED_IMAGE_EXTENSION
from internal.exception import FailException
from internal.lib.helper import utc_now_naive
from internal.model import UploadFile
from internal.service.upload_file_service import UploadFileService

# 本地存储访问 URL 前缀（与 router.py 中注册的路由保持一致）
LOCAL_STORAGE_URL_PREFIX = "/storage/local"

# 默认本地存储根目录（相对于容器工作目录 /app/api）
DEFAULT_LOCAL_STORAGE_ROOT = "storage/uploads"


def _get_local_storage_root() -> str:
    """读取本地存储根目录，未配置时使用默认值。"""
    return (os.getenv("LOCAL_STORAGE_ROOT") or DEFAULT_LOCAL_STORAGE_ROOT).strip() or DEFAULT_LOCAL_STORAGE_ROOT


def _get_local_storage_base_url() -> str:
    """读取本地存储访问基础 URL，默认为空（使用相对路径）。"""
    return (os.getenv("LOCAL_STORAGE_BASE_URL") or "").strip()


def _build_object_key(filename: str, folder: str = "") -> str:
    """生成对象存储 key，格式：{year}/{month}/{day}/[folder/]{uuid}.{ext}"""
    extension = filename.rsplit(".", 1)[-1] if "." in filename else ""
    random_filename = str(uuid.uuid4()) + (f".{extension}" if extension else "")
    now = utc_now_naive()
    prefix = f"{now.year}/{now.month:02d}/{now.day:02d}"
    normalized_folder = folder.strip("/")
    if normalized_folder:
        return f"{prefix}/{normalized_folder}/{random_filename}"
    return f"{prefix}/{random_filename}"


def _ensure_parent_dir(file_path: str) -> None:
    """确保文件父目录存在。"""
    parent = os.path.dirname(file_path)
    if parent:
        os.makedirs(parent, exist_ok=True)


def _safe_join(root: str, key: str) -> str:
    """安全拼接根目录与 key，防止路径穿越。"""
    normalized_key = key.replace("\\", "/").lstrip("/")
    if ".." in normalized_key.split("/"):
        raise FailException("非法存储路径")
    return os.path.join(root, *normalized_key.split("/"))


@inject
@dataclass
class LocalStorageService:
    """本地文件存储服务。

    通过依赖注入绑定到 ``ObjectStoragePort`` 与 ``CosService``，
    在 ``STORAGE_BACKEND=local`` 时接管所有上传/下载/URL 生成请求。

    类方法 ``upload_bytes_without_record`` / ``get_file_url`` 兼容
    ``CosService`` 中静态分发的调用约定。
    """

    upload_file_service: UploadFileService

    # ------------------------------------------------------------------
    # 文件上传
    # ------------------------------------------------------------------
    def upload_file(self, file: FileStorage, only_image: bool, account) -> UploadFile:
        """上传文件到本地磁盘，并创建 UploadFile 记录。"""
        filename = file.filename or "unnamed"
        extension = filename.rsplit(".", 1)[-1] if "." in filename else ""
        extension_lower = extension.lower()

        if extension_lower not in (ALLOWED_IMAGE_EXTENSION + ALLOWED_DOCUMENT_EXTENSION):
            raise FailException(f"该.{extension}扩展的文件不允许上传")
        if only_image and extension_lower not in ALLOWED_IMAGE_EXTENSION:
            raise FailException(f"该.{extension}扩展的文件不支持上传，请上传正确的图片")

        upload_filename = _build_object_key(filename)
        file_content = file.stream.read()

        try:
            storage_root = _get_local_storage_root()
            file_path = _safe_join(storage_root, upload_filename)
            _ensure_parent_dir(file_path)
            with open(file_path, "wb") as f:
                f.write(file_content)
        except Exception:
            logging.exception(
                "Local storage upload failed: key=%s account_id=%s",
                upload_filename,
                getattr(account, "id", None),
            )
            raise FailException("上传文件失败，请稍后重试")

        return self.upload_file_service.create_upload_file(
            account_id=account.id if account is not None else None,
            name=filename,
            key=upload_filename,
            size=len(file_content),
            extension=extension_lower,
            mime_type=file.mimetype,
            hash=hashlib.sha3_256(file_content).hexdigest(),
            storage_backend="local",
        )

    def upload_bytes(
        self,
        *,
        filename: str,
        content: bytes,
        account_id,
        mime_type: str | None = None,
        folder: str = "artifacts",
    ) -> UploadFile:
        """上传内存字节到本地磁盘，并创建 UploadFile 记录。"""
        upload_filename = _build_object_key(filename, folder=folder)
        resolved_mime_type = mime_type or mimetypes.guess_type(filename)[0] or "application/octet-stream"

        try:
            storage_root = _get_local_storage_root()
            file_path = _safe_join(storage_root, upload_filename)
            _ensure_parent_dir(file_path)
            with open(file_path, "wb") as f:
                f.write(content)
        except Exception:
            logging.exception(
                "Local storage bytes upload failed: key=%s account_id=%s",
                upload_filename,
                account_id,
            )
            raise FailException("上传产物文件失败，请稍后重试")

        extension = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
        return self.upload_file_service.create_upload_file(
            account_id=account_id,
            name=filename,
            key=upload_filename,
            size=len(content),
            extension=extension,
            mime_type=resolved_mime_type,
            hash=hashlib.sha3_256(content).hexdigest(),
            storage_backend="local",
        )

    @classmethod
    def upload_bytes_without_record(
        cls,
        *,
        filename: str,
        content: bytes,
        folder: str = "generated-images",
    ) -> str:
        """上传内存字节到本地磁盘，不创建 UploadFile 记录，返回可访问 URL。"""
        upload_filename = _build_object_key(filename, folder=folder)
        try:
            storage_root = _get_local_storage_root()
            file_path = _safe_join(storage_root, upload_filename)
            _ensure_parent_dir(file_path)
            with open(file_path, "wb") as f:
                f.write(content)
        except Exception:
            logging.exception(
                "Local storage bytes upload without record failed: key=%s",
                upload_filename,
            )
            raise FailException("上传产物文件失败，请稍后重试")
        return cls.get_file_url(upload_filename)

    # ------------------------------------------------------------------
    # 文件下载
    # ------------------------------------------------------------------
    def download_file(self, key: str, target_file_path: str) -> None:
        """将本地存储的文件下载（复制）到指定路径。"""
        try:
            storage_root = _get_local_storage_root()
            src_path = _safe_join(storage_root, key)
            _ensure_parent_dir(target_file_path)
            with open(src_path, "rb") as src, open(target_file_path, "wb") as dst:
                dst.write(src.read())
        except FileNotFoundError:
            raise FailException("文件不存在")
        except Exception:
            logging.exception("Local storage download failed: key=%s target=%s", key, target_file_path)
            raise FailException("下载文件失败，请稍后重试")

    # ------------------------------------------------------------------
    # URL 生成
    # ------------------------------------------------------------------
    @classmethod
    def get_file_url(cls, key: str, download_name: str | None = None) -> str:
        """生成本地存储文件的访问 URL。

        - ``LOCAL_STORAGE_BASE_URL`` 配置时：``{base_url}/{key}``
        - 未配置时：相对路径 ``/storage/local/{key}``（由浏览器拼接当前域名）
        """
        base_url = _get_local_storage_base_url()
        safe_key = key.replace("\\", "/").lstrip("/")
        if base_url:
            return f"{base_url.rstrip('/')}/{safe_key}"

        if download_name:
            utf8_name = quote(download_name, safe="")
            return f"{LOCAL_STORAGE_URL_PREFIX}/{safe_key}?download={utf8_name}"
        return f"{LOCAL_STORAGE_URL_PREFIX}/{safe_key}"
