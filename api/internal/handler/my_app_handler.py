from dataclasses import dataclass
from uuid import UUID

from flask_login import current_user, login_required
from injector import inject

from internal.schema.app_schema import DebugChatReq
from internal.schema.my_app_schema import MyAppListResp
from internal.service.app_service import AppService
from internal.service.my_app_service import MyAppService
from pkg.response import compact_generate_response, success_json, validate_error_json


@inject
@dataclass
class MyAppHandler:
    my_app_service: MyAppService
    app_service: AppService

    @login_required
    def list_my_apps(self):
        resp = MyAppListResp()
        return success_json(resp.dump(self.my_app_service.list_my_apps(current_user.id)))

    @login_required
    def chat(self, app_id: UUID):
        self.my_app_service.get_assigned_app(current_user.id, app_id)
        req = DebugChatReq()
        if not req.validate():
            return validate_error_json(req.errors)
        return compact_generate_response(self.app_service.debug_chat(app_id, req, current_user))
