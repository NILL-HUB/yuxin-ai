"""内容存储配置服务。

管理 ``storage_config`` 表中的存储后端配置：
- 列出所有后端配置（local / cos / oss）与激活状态
- 运行时切换激活后端：仅影响新上传文件，历史文件按 storage_backend 路由
- 更新各后端的密钥/桶等配置项（configs JSON）
- 环境变量 ``STORAGE_BACKEND`` 作为未配置时的降级方案

配置项明文存储仅用于内存中转，服务端不记录完整密钥，仅保留
可展示的脱敏信息（如桶名、区域、域名）。
"""
import logging
import os
from dataclasses import dataclass

from injector import inject
from sqlalchemy import func, true

from internal.exception import ValidateErrorException
from internal.model import StorageConfig, UploadFile
from pkg.sqlalchemy import SQLAlchemy

logger = logging.getLogger(__name__)

# 支持的后端列表
SUPPORTED_BACKENDS = ("local", "cos", "oss")

# 各后端允许持久化的配置键（其余键不入库，避免密钥泄露）
_ALLOWED_CONFIG_KEYS = {
    "local": ("root", "base_url"),
    "cos": ("bucket", "region", "scheme", "domain", "enable_internal_domain", "auto_switch_domain_on_retry"),
    "oss": ("bucket", "endpoint", "domain"),
}


def _sanitize_configs(backend: str, configs: dict | None) -> dict:
    """仅保留后端允许的配置键，剔除密钥类字段。"""
    if not isinstance(configs, dict):
        return {}
    allowed = _ALLOWED_CONFIG_KEYS.get(backend, ())
    return {k: v for k, v in configs.items() if k in allowed}


@inject
@dataclass
class StorageConfigService:
    """内容存储配置服务。"""

    db: SQLAlchemy

    # ------------------------------------------------------------------
    # 查询
    # ------------------------------------------------------------------
    def get_active_backend(self) -> str:
        """获取当前激活的存储后端。

        优先读取 ``storage_config`` 表中激活的记录，未配置时降级到
        ``STORAGE_BACKEND`` 环境变量（默认 local）。
        """
        active = (
            self.db.session.query(StorageConfig)
            .filter(StorageConfig.is_active == true())
            .order_by(StorageConfig.updated_at.desc())
            .first()
        )
        if active is not None:
            return active.backend
        return (os.getenv("STORAGE_BACKEND") or "local").strip().lower()

    def list_configs(self) -> list[StorageConfig]:
        """列出所有存储后端配置。"""
        return (
            self.db.session.query(StorageConfig)
            .order_by(StorageConfig.created_at.asc())
            .all()
        )

    def get_config(self, backend: str) -> StorageConfig | None:
        """按后端名获取配置记录。"""
        return (
            self.db.session.query(StorageConfig)
            .filter(StorageConfig.backend == backend)
            .order_by(StorageConfig.created_at.asc())
            .first()
        )

    def get_storage_stats(self) -> dict:
        """统计各后端下的文件数量与体积（upload_file 表聚合）。"""
        rows = (
            self.db.session.query(
                UploadFile.storage_backend,
                func.count(UploadFile.id),
                func.coalesce(func.sum(UploadFile.size), 0),
            )
            .group_by(UploadFile.storage_backend)
            .all()
        )
        stats = {}
        for backend, count, size in rows:
            key = backend or "local"
            stats[key] = {"count": count, "size": int(size or 0)}
        return stats

    # ------------------------------------------------------------------
    # 写入
    # ------------------------------------------------------------------
    def upsert_config(self, backend: str, configs: dict | None = None) -> StorageConfig:
        """新增或更新后端配置（仅保存白名单键）。"""
        self._validate_backend(backend)
        config = self.get_config(backend)
        sanitized = _sanitize_configs(backend, configs)
        if config is None:
            config = StorageConfig(backend=backend, configs=sanitized)
            with self.db.auto_commit():
                self.db.session.add(config)
        else:
            with self.db.auto_commit():
                config.configs = sanitized
        logger.info("storage config upsert backend=%s keys=%s", backend, list(sanitized.keys()))
        return config

    def set_active_backend(self, backend: str) -> StorageConfig:
        """激活指定后端：同一时间仅一个后端处于激活状态。

        仅影响新上传文件；历史文件按 ``upload_file.storage_backend`` 路由。
        """
        self._validate_backend(backend)
        with self.db.auto_commit():
            for config in self.db.session.query(StorageConfig).all():
                config.is_active = config.backend == backend
        active = self.get_config(backend)
        if active is None:
            active = StorageConfig(backend=backend, configs={})
            with self.db.auto_commit():
                self.db.session.add(active)
        if not active.is_active:
            with self.db.auto_commit():
                active.is_active = True
        logger.info("storage backend switched to %s", backend)
        return active

    def ensure_default_config(self) -> None:
        """确保系统至少有一个可用的后端配置（幂等，供启动时调用）。

        无任何激活记录时，将 ``STORAGE_BACKEND`` 环境变量指定的后端（或
        默认 local）在 DB 中标记激活，保证 Admin 界面与运行时一致。
        """
        existing = {c.backend for c in self.list_configs()}
        for backend in SUPPORTED_BACKENDS:
            if backend in existing:
                continue
            with self.db.auto_commit():
                self.db.session.add(StorageConfig(backend=backend, configs={}))
        if not any(c.is_active for c in self.list_configs()):
            default_backend = (os.getenv("STORAGE_BACKEND") or "local").strip().lower()
            if default_backend not in SUPPORTED_BACKENDS:
                default_backend = "local"
            active = self.get_config(default_backend)
            if active is not None:
                with self.db.auto_commit():
                    active.is_active = True

    @staticmethod
    def _validate_backend(backend: str) -> None:
        if backend not in SUPPORTED_BACKENDS:
            raise ValidateErrorException(
                f"不支持的存储后端: {backend}（可选值: {'/'.join(SUPPORTED_BACKENDS)}）"
            )
