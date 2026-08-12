"""阿里云 OSS 对象存储服务。

通过 ``oss2`` SDK 实现 ``ObjectStoragePort`` 接口，方法签名与 ``CosService`` 保持一致。
通过环境变量 ``STORAGE_BACKEND=oss`` 切换启用。

必需配置：
- ``OSS_ACCESS_KEY_ID``: 阿里云 AccessKey ID
- ``OSS_ACCESS_KEY_SECRET``: 阿里云 AccessKey Secret
- ``OSS_ENDPOINT``: OSS 端点（如 ``oss-cn-beijing.aliyuncs.com``）
- ``OSS_BUCKET``: Bucket 名称
- ``OSS_DOMAIN``: (可选) 自定义访问域名/CDN 域名

存储路径规则与 COS/Local 实现一致：
    {year}/{month:02d}/{day:02d}/[folder/]{uuid}.{ext}
"""
from __future__ import annotations

import hashlib
import logging
import mimetypes
import os
import uuid
from dataclasses import dataclass
from injector import inject
from werkzeug.datastructures import FileStorage

from internal.entity.upload_file_entity import ALLOWED_DOCUMENT_EXTENSION, ALLOWED_IMAGE_EXTENSION
from internal.exception import FailException
from internal.lib.helper import utc_now_naive
from internal.model import Account, UploadFile
from internal.service.upload_file_service import UploadFileService


def _import_oss2():
    """延迟导入 oss2，避免未安装时影响其他后端。"""
    try:
        import oss2  # noqa: PLC0415
        return oss2
    except ImportError as e:
        raise FailException(
            "未安装阿里云 OSS SDK (oss2)，请在 requirements.txt 中添加 oss2 并重新构建镜像"
        ) from e


@inject
@dataclass
class AliyunOSSService:
    """阿里云 OSS 对象存储服务。

    实现 ``ObjectStoragePort`` 接口，方法签名与 ``CosService`` 保持一致，
    可通过 ``STORAGE_BACKEND=oss`` 环境变量切换。
    """

    upload_file_service: UploadFileService

    @staticmethod
    def _build_object_key(filename: str, folder: str = "") -> str:
        """生成对象存储 key（与 CosService 格式一致）。"""
        extension = filename.rsplit(".", 1)[-1] if "." in filename else ""
        random_filename = str(uuid.uuid4()) + (f".{extension}" if extension else "")
        now = utc_now_naive()
        prefix = f"{now.year}/{now.month:02d}/{now.day:02d}"
        normalized_folder = folder.strip("/")
        if normalized_folder:
            return f"{prefix}/{normalized_folder}/{random_filename}"
        return f"{prefix}/{random_filename}"

    @classmethod
    def _get_bucket(cls):
        """获取阿里云 OSS Bucket 实例。"""
        oss2 = _import_oss2()
        access_key_id = os.getenv("OSS_ACCESS_KEY_ID")
        access_key_secret = os.getenv("OSS_ACCESS_KEY_SECRET")
        endpoint = os.getenv("OSS_ENDPOINT")
        bucket_name = os.getenv("OSS_BUCKET")

        if not all([access_key_id, access_key_secret, endpoint, bucket_name]):
            raise FailException(
                "阿里云 OSS 配置不完整，请检查 OSS_ACCESS_KEY_ID/OSS_ACCESS_KEY_SECRET/"
                "OSS_ENDPOINT/OSS_BUCKET 环境变量"
            )

        auth = oss2.Auth(access_key_id, access_key_secret)
        return oss2.Bucket(auth, endpoint, bucket_name)

    @classmethod
    def _get_domain(cls) -> str:
        """获取 OSS 访问域名。"""
        domain = (os.getenv("OSS_DOMAIN") or "").strip().rstrip("/")
        if domain:
            return domain

        # 自动拼接默认域名
        bucket = os.getenv("OSS_BUCKET")
        endpoint = os.getenv("OSS_ENDPOINT", "")
        # endpoint 格式: oss-cn-beijing.aliyuncs.com
        return f"https://{bucket}.{endpoint}"

    def upload_file(self, file: FileStorage, only_image: bool, account: Account) -> UploadFile:
        """上传文件到阿里云 OSS，返回文件元数据记录。"""
        filename = file.filename
        extension = filename.rsplit(".", 1)[-1] if "." in filename else ""
        extension_lower = extension.lower()
        if extension_lower not in (ALLOWED_IMAGE_EXTENSION + ALLOWED_DOCUMENT_EXTENSION):
            raise FailException(f"该.{extension}扩展的文件不允许上传")
        if only_image and extension_lower not in ALLOWED_IMAGE_EXTENSION:
            raise FailException(f"该.{extension}扩展的文件不支持上传，请上传正确的图片")

        upload_key = self._build_object_key(filename)
        file_content = file.stream.read()

        try:
            bucket = self._get_bucket()
            bucket.put_object(upload_key, file_content)
        except Exception:
            logging.exception("OSS upload failed: key=%s account_id=%s", upload_key, account.id)
            raise FailException("上传文件失败，请稍后重试")

        return self.upload_file_service.create_upload_file(
            account_id=account.id,
            name=filename,
            key=upload_key,
            size=len(file_content),
            extension=extension_lower,
            mime_type=file.mimetype,
            hash=hashlib.sha3_256(file_content).hexdigest(),
            storage_backend="oss",
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
        """上传内存字节内容到阿里云 OSS。"""
        upload_key = self._build_object_key(filename, folder=folder)
        resolved_mime_type = mime_type or mimetypes.guess_type(filename)[0] or "application/octet-stream"

        try:
            bucket = self._get_bucket()
            bucket.put_object(upload_key, content)
        except Exception:
            logging.exception("OSS bytes upload failed: key=%s account_id=%s", upload_key, account_id)
            raise FailException("上传产物文件失败，请稍后重试")

        extension = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
        return self.upload_file_service.create_upload_file(
            account_id=account_id,
            name=filename,
            key=upload_key,
            size=len(content),
            extension=extension,
            mime_type=resolved_mime_type,
            hash=hashlib.sha3_256(content).hexdigest(),
            storage_backend="oss",
        )

    @classmethod
    def upload_bytes_without_record(
        cls,
        *,
        filename: str,
        content: bytes,
        folder: str = "generated-images",
    ) -> str:
        """上传字节到 OSS，不创建 UploadFile 记录，返回访问 URL。"""
        upload_key = cls._build_object_key(filename, folder=folder)
        try:
            bucket = cls._get_bucket()
            bucket.put_object(upload_key, content)
        except Exception:
            logging.exception("OSS bytes upload without record failed: key=%s", upload_key)
            raise FailException("上传产物文件失败，请稍后重试")
        return cls.get_file_url(upload_key)

    def download_file(self, key: str, target_file_path: str) -> None:
        """从 OSS 下载文件到指定路径。"""
        try:
            bucket = self._get_bucket()
            os.makedirs(os.path.dirname(target_file_path), exist_ok=True)
            bucket.get_object_to_file(key, target_file_path)
        except Exception as e:
            logging.exception("OSS download failed: key=%s target=%s", key, target_file_path)
            raise FailException(f"下载文件失败: {e}")

    @classmethod
    def get_file_url(cls, key: str, download_name: str | None = None) -> str:
        """根据 OSS key 获取文件访问 URL。

        默认返回匿名可访问的裸 URL（要求 Bucket 为公共读）。
        如需私有桶签名下载，可通过 ``OSS_PRESIGNED_DOWNLOAD_URL_EXPIRE_SECONDS`` 开启。
        """
        domain = cls._get_domain()
        url = f"{domain}/{key}"

        if not download_name:
            return url

        presigned_expires = int(os.getenv("OSS_PRESIGNED_DOWNLOAD_URL_EXPIRE_SECONDS", "0") or "0")
        if presigned_expires <= 0:
            return url

        # 生成预签名 URL
        try:
            bucket = cls._get_bucket()
            from urllib.parse import quote
            from unicodedata import normalize
            import unicodedata

            fallback_name = unicodedata.normalize("NFKD", download_name).encode("ascii", "ignore").decode("ascii")
            fallback_name = fallback_name.replace("\\", "_").replace('"', "_").strip(" .") or "download"
            utf8_name = quote(download_name, safe="")
            disposition = (
                f"attachment; filename=\"{fallback_name}\"; "
                f"filename*=UTF-8''{utf8_name}"
            )
            return bucket.sign_url(
                "GET",
                key,
                expires=presigned_expires,
                params={"response-content-disposition": disposition},
            )
        except Exception as e:
            logging.warning("OSS presigned URL 生成失败，回退到裸 URL: %s", e)
            return url
