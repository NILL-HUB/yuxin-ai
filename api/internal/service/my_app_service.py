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
        """返回用户“我的应用”：管理员分配的应用 + 从应用商店添加（fork）的应用。

        用户自己创建的分身应用暂不纳入（分身体系未完善）。
        """
        apps = []
        seen_app_ids = set()

        assignments = (
            self.session.query(AppAssignment)
            .filter(AppAssignment.account_id == account_id, AppAssignment.status == "active")
            .order_by(AppAssignment.assigned_at.desc())
            .all()
        )
        for assignment in assignments:
            app = getattr(assignment, "app", None)
            if app is None or app.status != AppStatus.PUBLISHED.value:
                continue
            apps.append(self._serialize_my_app(assignment, app, source="assigned"))
            seen_app_ids.add(app.id)

        # 从应用商店添加（fork）的应用：归属当前用户且带 original_app_id
        forked_apps = self._list_forked_apps(account_id)
        for app in forked_apps:
            if app.id in seen_app_ids:
                continue
            apps.append(self._serialize_forked_app(app))
        return {"list": apps}

    def _list_forked_apps(self, account_id: UUID) -> list[App]:
        return (
            self.session.query(App)
            .filter(
                App.account_id == account_id,
                App.original_app_id.isnot(None),
            )
            .order_by(App.created_at.desc())
            .all()
        )

    def get_assigned_app(self, account_id: UUID, app_id: UUID) -> App:
        """校验用户可用应用：管理员分配的应用或本人从商店添加（fork）的应用。"""
        assignment = (
            self.session.query(AppAssignment)
            .filter(
                AppAssignment.account_id == account_id,
                AppAssignment.app_id == app_id,
                AppAssignment.status == "active",
            )
            .one_or_none()
        )
        if assignment is not None:
            app = getattr(assignment, "app", None)
            if app is not None and app.status == AppStatus.PUBLISHED.value:
                return app
            raise FailException("AI 功能未发布，暂不可用")

        # 本人 fork 的应用（草稿态也可在“我的应用”中对话调试）
        forked_app = (
            self.session.query(App)
            .filter(
                App.id == app_id,
                App.account_id == account_id,
                App.original_app_id.isnot(None),
            )
            .one_or_none()
        )
        if forked_app is not None:
            return forked_app
        raise NotFoundException("AI 功能不存在或未分配")

    def _serialize_my_app(
        self,
        assignment: AppAssignment,
        app: App,
        *,
        source: str = "assigned",
    ) -> dict[str, object]:
        return {
            "id": str(app.id),
            "assignment_id": str(assignment.id),
            "name": app.name,
            "icon": app.icon,
            "description": app.description,
            "assigned_at": self._timestamp(assignment.assigned_at),
            "source": source,
            "status": app.status,
            # 管理端分配的应用：用户只可对话使用，不可编辑/调试
            "can_edit": False,
        }

    def _serialize_forked_app(self, app: App) -> dict[str, object]:
        return {
            "id": str(app.id),
            "assignment_id": "",
            "name": app.name,
            "icon": app.icon,
            "description": app.description,
            "assigned_at": self._timestamp(app.created_at),
            "source": "forked",
            # 商店添加（fork）的应用对用户而言是“已添加、可直接使用”，
            # 不呈现为可编辑的草稿；自建分身体系落地后 can_edit 才可能为 True。
            "status": AppStatus.PUBLISHED.value,
            "can_edit": False,
        }
