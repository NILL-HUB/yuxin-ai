import logging
import math
from uuid import UUID

from internal.entity.agent_entity import normalize_agent_metadata
from internal.exception import NotFoundException
from internal.extension.database_extension import db
from internal.lib.helper import datetime_to_timestamp, escape_like_pattern
from internal.model.admin import AdminUser
from internal.model.app import App

logger = logging.getLogger(__name__)


class AdminAppService:
    def __init__(self, session=None):
        self.session = session or db.session

    def list_apps(self, *, search: str = "", status: str = "all", current_page: int = 1, page_size: int = 20) -> dict[str, object]:
        current_page = max(int(current_page or 1), 1)
        page_size = max(min(int(page_size or 20), 100), 1)
        query = self.session.query(App)
        if search:
            query = query.filter(App.name.ilike(f"%{escape_like_pattern(search)}%"))
        if status and status != "all":
            query = query.filter(App.status == status)
        total = query.count()
        apps = query.order_by(App.created_at.desc()).offset((current_page - 1) * page_size).limit(page_size).all()
        return {
            "list": [self._serialize_app(app) for app in apps],
            "paginator": {
                "total_record": total,
                "total_page": math.ceil(total / page_size) if total else 0,
                "current_page": current_page,
                "page_size": page_size,
            },
        }

    def get_app(self, app_id: UUID) -> dict[str, object]:
        app = self.session.query(App).filter(App.id == app_id).one_or_none()
        if app is None:
            raise NotFoundException("应用不存在")
        return self._serialize_app(app)

    def update_app(
        self,
        app_id: UUID,
        *,
        status: str | None = None,
        is_public: bool | None = None,
        agent_metadata: dict | None = None,
    ) -> dict[str, object]:
        app = self.session.query(App).filter(App.id == app_id).one_or_none()
        if app is None:
            raise NotFoundException("应用不存在")
        if status is not None:
            app.status = status
        if is_public is not None:
            app.is_public = is_public
        if agent_metadata is not None:
            app.agent_metadata = normalize_agent_metadata(agent_metadata)
        self.session.commit()
        return self._serialize_app(app)

    def offline_app(self, app_id: UUID) -> None:
        app = self.session.query(App).filter(App.id == app_id).one_or_none()
        if app is None:
            raise NotFoundException("应用不存在")
        app.status = "offline"
        app.is_public = False
        self.session.commit()

    def batch_offline_apps(self, app_ids: list[UUID]) -> dict[str, object]:
        """批量下架应用，返回成功/失败统计"""
        succeeded: list[str] = []
        failed: list[dict[str, str]] = []
        for app_id in app_ids:
            try:
                app = self.session.query(App).filter(App.id == app_id).one_or_none()
                if app is None:
                    failed.append({"id": str(app_id), "reason": "应用不存在"})
                    continue
                app.status = "offline"
                app.is_public = False
                succeeded.append(str(app_id))
            except Exception as e:
                logger.warning("批量下架应用失败: app_id=%s, error=%s", app_id, e)
                failed.append({"id": str(app_id), "reason": str(e)})
        self.session.commit()
        return {"succeeded": succeeded, "failed": failed}

    def batch_delete_apps(self, app_ids: list[UUID], *, retention_days: int | None = None, deleted_by=None) -> dict[str, object]:
        """批量删除应用（逐个进入回收站），返回成功/失败统计"""
        from internal.service.recycle_bin_service import RecycleBinService
        succeeded: list[str] = []
        failed: list[dict[str, str]] = []
        for app_id in app_ids:
            try:
                app = self.session.query(App).filter(App.id == app_id).one_or_none()
                if app is None:
                    failed.append({"id": str(app_id), "reason": "应用不存在"})
                    continue
                deleted = RecycleBinService().delete_resource(
                    resource_type="app",
                    resource_id=app.id,
                    resource_key=str(app.id),
                    resource_name=app.name,
                    deleted_by=deleted_by,
                    retention_days=retention_days,
                )
                if not deleted:
                    failed.append({"id": str(app_id), "reason": "应用不存在"})
                    continue
                succeeded.append(str(app_id))
            except Exception as e:
                logger.warning("批量删除应用失败: app_id=%s, error=%s", app_id, e)
                failed.append({"id": str(app_id), "reason": str(e)})
        return {"succeeded": succeeded, "failed": failed}

    def _resolve_creator_name(self, created_by_admin) -> str:
        """根据创建管理员 id 解析展示名（平台级资源归属显示为创建者）"""
        if not created_by_admin:
            return ""
        admin_user = self.session.query(AdminUser.name).filter(AdminUser.id == created_by_admin).one_or_none()
        if admin_user is None:
            return ""
        return admin_user[0] or ""

    def _serialize_app(self, app: App) -> dict[str, object]:
        return {
            "id": str(app.id),
            "name": app.name,
            "icon": app.icon,
            "description": app.description,
            "status": app.status,
            "app_type": app.app_type,
            "is_public": app.is_public,
            "agent_metadata": app.normalized_agent_metadata,
            "debug_conversation_id": str(app.debug_conversation_id) if app.debug_conversation_id else None,
            "creator_name": self._resolve_creator_name(app.created_by_admin),
            "created_at": datetime_to_timestamp(app.created_at),
            "updated_at": datetime_to_timestamp(app.updated_at),
        }
