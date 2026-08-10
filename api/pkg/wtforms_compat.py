"""纯 wtforms 文件字段与验证器（彻底移除 Flask 依赖）。

- ``FileField``：wtforms.fields.FileField 别名
- ``FileRequired`` / ``FileSize`` / ``FileAllowed``：标准文件字段验证器，
  基于 werkzeug FileStorage（``field.data``）做非空 / 大小 / 扩展名校验。
"""

import os
from typing import Optional

from wtforms.fields import FileField  # noqa: F401  (re-export)
from wtforms.validators import StopValidation

__all__ = ["FileField", "FileRequired", "FileSize", "FileAllowed"]


def _get_filename(data) -> Optional[str]:
    """从 FileStorage 或任意带 filename 属性的对象提取文件名。"""
    if data is None:
        return None
    filename = getattr(data, "filename", None)
    if filename is None and isinstance(data, str):
        filename = data
    return filename


def _get_size(data) -> int:
    """从 FileStorage（content_length）或文件对象（seek/tell）提取字节大小。"""
    content_length = getattr(data, "content_length", None)
    if content_length:
        return int(content_length)
    stream = getattr(data, "stream", None)
    if stream is not None:
        try:
            pos = stream.tell()
            stream.seek(0, os.SEEK_END)
            size = stream.tell()
            stream.seek(pos)
            return size
        except (OSError, AttributeError, ValueError):
            pass
    return 0


class FileRequired:
    """文件必填验证器（非空且带文件名）。"""

    def __init__(self, message: str = "文件不能为空"):
        self.message = message

    def __call__(self, form, field):
        if _get_filename(field.data) in (None, ""):
            raise StopValidation(self.message)


class FileSize:
    """文件大小验证器（上限，单位字节）。"""

    def __init__(self, max_size: int, message: Optional[str] = None):
        self.max_size = max_size
        self.message = message or f"文件大小不能超过{max_size}字节"

    def __call__(self, form, field):
        size = _get_size(field.data)
        if size > self.max_size:
            raise StopValidation(self.message)


class FileAllowed:
    """文件扩展名白名单验证器。"""

    def __init__(self, upload_set, message: Optional[str] = None):
        if isinstance(upload_set, (list, tuple, set)):
            self.upload_set = {str(ext).lstrip(".").lower() for ext in upload_set}
        elif isinstance(upload_set, str):
            self.upload_set = {upload_set.lstrip(".").lower()}
        else:
            self.upload_set = set()
        self.message = message or "文件类型不允许上传"

    def __call__(self, form, field):
        filename = _get_filename(field.data)
        if filename in (None, ""):
            return
        ext = os.path.splitext(str(filename))[1].lstrip(".").lower()
        if ext not in self.upload_set:
            raise StopValidation(self.message)
