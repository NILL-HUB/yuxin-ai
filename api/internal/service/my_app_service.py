from datetime import UTC

from internal.entity.app_entity import AppStatus
from internal.exception import FailException, NotFoundException
from internal.extension.database_extension import db
from internal.model.app import App


class MyAppService:
    def __init__(self, session=None):
        self.session = session or db.session

    @staticmethod
    def _timestamp(value) -> int | None:
        if value is None:
            return None
        return int(value.replace(tzinfo=UTC).timestamp())

    def list_my_apps(self, account_id) -> dict[str, object]:
        """返回用户“我的应用”：本人从应用商店添加（fork）且已发布的应用。

        可见性规则：只展示 `status == published` 的应用；草稿/下架状态不出现。
        （「管理员分配」已下线，用户获取应用的入口为应用商店添加。）
        """
        apps = []
        forked_apps = self._list_forked_apps(account_id)
        for app in forked_apps:
            if app.status != AppStatus.PUBLISHED.value:
                continue
            apps.append(self._serialize_forked_app(app))
        return {"list": apps}

    def _list_forked_apps(self, account_id) -> list[App]:
        return (
            self.session.query(App)
            .filter(
                App.account_id == account_id,
                App.original_app_id.isnot(None),
                App.status == AppStatus.PUBLISHED.value,
            )
            .order_by(App.created_at.desc())
            .all()
        )

    def get_user_app(self, account_id, app_id) -> App:
        """校验用户可用应用：本人从商店添加（fork）且已发布的应用。

        草稿不具备使用资格：草稿态副本不可对话。
        """
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
            if forked_app.status != AppStatus.PUBLISHED.value:
                raise FailException("AI 功能未发布，暂不可用")
            return forked_app
        raise NotFoundException("AI 功能不存在")

    def _serialize_forked_app(self, app: App) -> dict[str, object]:
        return {
            "id": str(app.id),
            "name": app.name,
            "icon": app.icon,
            "description": app.description,
            "created_at": self._timestamp(app.created_at),
            "source": "forked",
            # 只展示已发布的 fork 副本，状态如实透传
            "status": app.status,
            "can_edit": False,
        }
