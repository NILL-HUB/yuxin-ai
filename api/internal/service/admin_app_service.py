import math
from uuid import UUID

from internal.entity.agent_entity import normalize_agent_metadata
from internal.exception import NotFoundException
from internal.extension.database_extension import db
from internal.lib.helper import datetime_to_timestamp
from internal.model.app import App


class AdminAppService:
    def __init__(self, session=None):
        self.session = session or db.session

    def list_apps(self, *, search: str = "", status: str = "all", current_page: int = 1, page_size: int = 20) -> dict[str, object]:
        current_page = max(int(current_page or 1), 1)
        page_size = max(min(int(page_size or 20), 50), 1)
        query = self.session.query(App)
        if search:
            query = query.filter(App.name.ilike(f"%{search}%"))
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

    @staticmethod
    def _serialize_app(app: App) -> dict[str, object]:
        return {
            "id": str(app.id),
            "name": app.name,
            "icon": app.icon,
            "description": app.description,
            "status": app.status,
            "is_public": app.is_public,
            "agent_metadata": app.normalized_agent_metadata,
            "created_at": datetime_to_timestamp(app.created_at),
            "updated_at": datetime_to_timestamp(app.updated_at),
        }
