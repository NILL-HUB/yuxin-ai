from __future__ import annotations

import os
import uuid
from urllib.parse import urlparse

import requests

from internal.core.ports.storage_port import ObjectStoragePort


def _guess_image_extension(image_url: str, content_type: str = "") -> str:
    parsed = urlparse(str(image_url or ""))
    extension = os.path.splitext(parsed.path)[1].strip().lower()
    if extension in {".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp", ".svg", ".avif"}:
        return extension.lstrip(".")

    normalized_content_type = str(content_type or "").lower()
    if "svg" in normalized_content_type:
        return "svg"
    if "jpeg" in normalized_content_type or "jpg" in normalized_content_type:
        return "jpg"
    if "webp" in normalized_content_type:
        return "webp"
    if "gif" in normalized_content_type:
        return "gif"
    if "bmp" in normalized_content_type:
        return "bmp"
    if "avif" in normalized_content_type:
        return "avif"
    return "png"


def persist_remote_image(
    image_url: str,
    *,
    source: str,
    storage_port: ObjectStoragePort | None = None,
    account_id=None,
) -> str:
    """下载第三方图片并上传到存储，返回稳定 URL。

    提供 ``account_id`` 时建 UploadFile 记录并入文件中心（`产物/`，计配额）；
    未提供时维持原行为（只落对象、不建记录）。
    """
    if not image_url:
        raise ValueError("image_url is required")

    response = requests.get(image_url, timeout=60)
    response.raise_for_status()

    extension = _guess_image_extension(
        image_url=image_url,
        content_type=response.headers.get("Content-Type", ""),
    )
    filename = f"{source}_{uuid.uuid4()}.{extension}"
    if account_id:
        from app.http.module import injector
        from internal.service.file_center_service import FileCenterService

        return injector.get(FileCenterService).save_generated_asset(
            account_id,
            filename=filename,
            content=response.content,
            folder="generated-images",
        )["url"]
    if storage_port is not None:
        return storage_port.upload_bytes_without_record(
            filename=filename,
            content=response.content,
            folder="generated-images",
        )
    from app.http.module import injector
    from internal.service.storage.runtime_storage_service import RuntimeStorageProxy
    return injector.get(RuntimeStorageProxy).upload_bytes_without_record(
        filename=filename,
        content=response.content,
        folder="generated-images",
    )
