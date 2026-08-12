"""存储后端工厂。

根据 ``STORAGE_BACKEND`` 环境变量动态选择存储后端实现类：
- ``local``: 本地文件存储（默认，开发/单机部署）
- ``cos``:   腾讯云 COS
- ``oss``:   阿里云 OSS

被 ``app/http/module.py`` 在 DI 配置阶段调用，将选中的实现类绑定到
``ObjectStoragePort`` 与 ``CosService`` 两个接口。
"""

import os

from internal.exception import FailException


def get_storage_service_class():
    """返回当前配置下的存储后端实现类。

    延迟导入避免在模块加载阶段强依赖所有后端的 SDK。
    """
    backend = (os.getenv("STORAGE_BACKEND") or "local").strip().lower()

    if backend == "local":
        from internal.service.storage.local_storage_service import LocalStorageService
        return LocalStorageService

    if backend == "cos":
        from internal.service.cos_service import CosService
        return CosService

    if backend == "oss":
        from internal.service.storage.aliyun_oss_service import AliyunOSSService
        return AliyunOSSService

    raise FailException(f"不支持的存储后端: {backend}（可选值: local / cos / oss）")
