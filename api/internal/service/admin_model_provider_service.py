# api/internal/service/admin_model_provider_service.py
import logging
import math
from datetime import UTC, datetime
from uuid import UUID

from injector import inject

from internal.exception import ConflictException, NotFoundException
from internal.extension.database_extension import db
from internal.lib.helper import escape_like_pattern
from internal.model.model_pool_entity import ModelPoolConfig
from internal.model.model_provider_entity import ModelProviderConfig
from pkg.sqlalchemy import SQLAlchemy

logger = logging.getLogger(__name__)


@inject
class AdminModelProviderService:
    """模型供应商 CRUD 服务"""

    def __init__(self, session=None, db: SQLAlchemy = None):
        self.session = session or db.session
        self._db = db

    @staticmethod
    def _now() -> datetime:
        return datetime.now(UTC).replace(tzinfo=None)

    @staticmethod
    def _timestamp(value) -> int | None:
        if value is None:
            return None
        return int(value.replace(tzinfo=UTC).timestamp())

    # ------------------------------------------------------------------
    # 查询
    # ------------------------------------------------------------------

    def list_providers(
        self,
        *,
        search: str = "",
        status: str = "",
        current_page: int = 1,
        page_size: int = 20,
    ) -> dict:
        current_page = max(int(current_page or 1), 1)
        page_size = max(min(int(page_size or 20), 100), 1)
        query = self.session.query(ModelProviderConfig)
        search = (search or "").strip()
        if search:
            like_value = f"%{escape_like_pattern(search)}%"
            query = query.filter(
                (ModelProviderConfig.name.ilike(like_value))
                | (ModelProviderConfig.label.ilike(like_value))
            )
        if status:
            query = query.filter(ModelProviderConfig.status == status)
        total = query.count()
        providers = (
            query.order_by(ModelProviderConfig.created_at.asc())
            .offset((current_page - 1) * page_size)
            .limit(page_size)
            .all()
        )
        return {
            "list": [self._serialize_provider(p) for p in providers],
            "paginator": {
                "total_record": total,
                "total_page": math.ceil(total / page_size) if total else 0,
                "current_page": current_page,
                "page_size": page_size,
            },
        }

    def get_provider(self, provider_id: UUID) -> dict:
        return self._serialize_provider(self._get_provider_or_raise(provider_id))

    def list_provider_options(self) -> dict:
        """获取 active 供应商下拉选项"""
        providers = (
            self.session.query(ModelProviderConfig)
            .filter(ModelProviderConfig.status == "active")
            .order_by(ModelProviderConfig.label.asc())
            .all()
        )
        return {
            "options": [
                {
                    "id": str(p.id),
                    "name": p.name,
                    "label": p.label,
                    "description": p.description or "",
                    "default_base_url": p.default_base_url,
                    "supported_model_types": p.supported_model_types or [],
                }
                for p in providers
            ]
        }

    # ------------------------------------------------------------------
    # 创建/更新/删除
    # ------------------------------------------------------------------

    def create_provider(self, payload: dict) -> dict:
        name = (payload.get("name") or "").strip()
        if not name:
            raise NotFoundException("供应商 name 不能为空")

        # 唯一性校验
        existing = self.session.query(ModelProviderConfig).filter_by(name=name).first()
        if existing:
            raise ConflictException(f"供应商 {name} 已存在")

        provider = ModelProviderConfig(
            name=name,
            label=payload.get("label") or name,
            description=payload.get("description") or "",
            icon=payload.get("icon") or "",
            background=payload.get("background") or "#FFFFFF",
            default_base_url=payload.get("default_base_url") or "",
            supported_model_types=payload.get("supported_model_types") or ["chat"],
            status=payload.get("status") or "active",
        )
        self.session.add(provider)
        self.session.commit()

        self._invalidate_cache(provider.name)
        return self._serialize_provider(provider)

    def update_provider(self, provider_id: UUID, payload: dict) -> dict:
        provider = self._get_provider_or_raise(provider_id)
        # name 不可改
        if "label" in payload:
            provider.label = payload["label"]
        if "description" in payload:
            provider.description = payload["description"] or ""
        if "icon" in payload:
            provider.icon = payload["icon"] or ""
        if "background" in payload:
            provider.background = payload["background"] or "#FFFFFF"
        if "default_base_url" in payload:
            provider.default_base_url = payload["default_base_url"] or ""
        if "supported_model_types" in payload:
            provider.supported_model_types = payload["supported_model_types"] or ["chat"]
        if "status" in payload:
            provider.status = payload["status"]
        provider.updated_at = self._now()
        self.session.commit()

        self._invalidate_cache(provider.name)
        return self._serialize_provider(provider)

    def delete_provider(self, provider_id: UUID) -> None:
        provider = self._get_provider_or_raise(provider_id)
        # 前置校验：无关联 active 模型
        active_models_count = (
            self.session.query(ModelPoolConfig)
            .filter(
                ModelPoolConfig.provider == provider.name,
                ModelPoolConfig.status == "active",
            )
            .count()
        )
        if active_models_count > 0:
            raise ConflictException(
                f"存在 {active_models_count} 个关联模型，请先删除或禁用模型"
            )
        provider_name = provider.name
        self.session.delete(provider)
        self.session.commit()

        self._invalidate_cache(provider_name)

    def set_provider_status(self, provider_id: UUID, status: str) -> dict:
        provider = self._get_provider_or_raise(provider_id)
        if status == "disabled":
            # 级联禁用所有 active 模型
            affected_models = (
                self.session.query(ModelPoolConfig)
                .filter(
                    ModelPoolConfig.provider == provider.name,
                    ModelPoolConfig.status == "active",
                )
                .all()
            )
            for model in affected_models:
                model.status = "disabled"
                model.updated_at = self._now()
                self._invalidate_model_cache(model.provider, model.model_name)
        provider.status = status
        provider.updated_at = self._now()
        self.session.commit()

        self._invalidate_cache(provider.name)
        return self._serialize_provider(provider)

    # ------------------------------------------------------------------
    # 内部方法
    # ------------------------------------------------------------------

    def _get_provider_or_raise(self, provider_id: UUID) -> ModelProviderConfig:
        provider = self.session.query(ModelProviderConfig).filter_by(id=provider_id).first()
        if provider is None:
            raise NotFoundException("供应商不存在")
        return provider

    def _serialize_provider(self, provider: ModelProviderConfig) -> dict:
        # 查询关联模型数量
        model_count = (
            self.session.query(ModelPoolConfig)
            .filter(ModelPoolConfig.provider == provider.name)
            .count()
        )
        return {
            "id": str(provider.id),
            "name": provider.name,
            "label": provider.label,
            "description": provider.description or "",
            "icon": provider.icon or "",
            "background": provider.background or "#FFFFFF",
            "default_base_url": provider.default_base_url,
            "supported_model_types": provider.supported_model_types or [],
            "status": provider.status,
            "model_count": model_count,
            "created_at": self._timestamp(provider.created_at),
            "updated_at": self._timestamp(provider.updated_at),
        }

    def _invalidate_cache(self, provider_name: str) -> None:
        """失效 LanguageModelManager 中的 provider 缓存"""
        try:
            from internal.core.language_model.language_model_manager import LanguageModelManager
            from injector import Injector
            injector = Injector()
            manager = injector.get(LanguageModelManager)
            manager.invalidate_provider(provider_name)
        except Exception as e:
            logger.debug("缓存失效跳过（可能未初始化）: %s", e)

    def _invalidate_model_cache(self, provider_name: str, model_name: str) -> None:
        """失效单个模型缓存"""
        try:
            from internal.core.language_model.language_model_manager import LanguageModelManager
            from injector import Injector
            injector = Injector()
            manager = injector.get(LanguageModelManager)
            manager.invalidate_model(provider_name, model_name)
        except Exception as e:
            logger.debug("模型缓存失效跳过: %s", e)
