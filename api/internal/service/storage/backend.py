"""存储后端枚举定义。

定义系统支持的文件存储后端类型，通过环境变量 ``STORAGE_BACKEND`` 切换。
- ``local``: 本地文件系统存储（开发/测试环境默认）
- ``cos``: 腾讯云 COS 对象存储
- ``oss``: 阿里云 OSS 对象存储
"""
from __future__ import annotations

from enum import Enum


class StorageBackend(str, Enum):
    """文件存储后端枚举。"""

    LOCAL = "local"
    COS = "cos"
    OSS = "oss"

    @classmethod
    def from_env(cls, default: "StorageBackend | str" = LOCAL) -> "StorageBackend":
        """从环境变量 ``STORAGE_BACKEND`` 读取当前后端。

        非法值回退到 ``default``，默认为 ``local``。
        """
        import os

        raw = (os.getenv("STORAGE_BACKEND") or str(default)).strip().lower()
        try:
            return cls(raw)
        except ValueError:
            return cls(str(default).lower()) if not isinstance(default, cls) else default
