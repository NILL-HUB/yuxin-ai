from datetime import UTC
from uuid import UUID

from internal.entity.app_entity import AppStatus
from internal.exception import FailException, NotFoundException
from internal.extension.database_extension import db
from internal.model.app import App, AppAssignment


class MyAppService:
    def __init__(self, session=None):
        self.session = session or db.session

    @staticmethod
    def _timestamp(value) -> int | None:
        if value is None:
            return None
        return int(value.replace(tzinfo=UTC).timestamp())

    def list_my_apps(self, account_id: UUID) -> dict[str, object]:
        assignments = (
            self.session.query(AppAssignment)
            .filter(AppAssignment.account_id == account_id, AppAssignment.status == "active")
            .order_by(AppAssignment.assigned_at.desc())
            .all()
        )
        apps = []
        for assignment in assignments:
            app = getattr(assignment, "app", None)
            if app is None or app.status != AppStatus.PUBLISHED.value:
                continue
            apps.append(self._serialize_my_app(assignment, app))
        return {"list": apps}

    def get_assigned_app(self, account_id: UUID, app_id: UUID) -> App:
        assignment = (
            self.session.query(AppAssignment)
            .filter(
                AppAssignment.account_id == account_id,
                AppAssignment.app_id == app_id,
                AppAssignment.status == "active",
            )
            .one_or_none()
        )
        if assignment is None:
            raise NotFoundException("AI 功能不存在或未分配")
        app = getattr(assignment, "app", None)
        if app is None:
            raise NotFoundException("AI 功能不存在")
        if app.status != AppStatus.PUBLISHED.value:
            raise FailException("AI 功能未发布，暂不可用")
        return app

    def _serialize_my_app(self, assignment: AppAssignment, app: App) -> dict[str, object]:
        return {
            "id": str(app.id),
            "assignment_id": str(assignment.id),
            "name": app.name,
            "icon": app.icon,
            "description": app.description,
            "assigned_at": self._timestamp(assignment.assigned_at),
        }
