from dataclasses import dataclass
from uuid import UUID

from flask import request
from injector import inject

from internal.middleware import admin_login_required, permission_required
from internal.service.admin_sub_pool_service import AdminSubPoolService
from pkg.response import success_json, success_message


@inject
@dataclass
class AdminSubPoolHandler:
    admin_sub_pool_service: AdminSubPoolService

    @admin_login_required
    @permission_required("agent_pool:read")
    def list(self):
        result = self.admin_sub_pool_service.list_definitions(
            page=request.args.get("current_page", 1),
            per_page=request.args.get("page_size", 20),
            pool_type=request.args.get("pool_type", ""),
            enabled=request.args.get("enabled", ""),
            keyword=request.args.get("keyword", ""),
        )
        return success_json(result)

    @admin_login_required
    @permission_required("agent_pool:manage")
    def create(self):
        payload = request.get_json(silent=True) or {}
        result = self.admin_sub_pool_service.create_definition(payload)
        return success_json(result)

    @admin_login_required
    @permission_required("agent_pool:read")
    def get(self, def_id: UUID):
        return success_json(self.admin_sub_pool_service.get_definition(def_id))

    @admin_login_required
    @permission_required("agent_pool:manage")
    def update(self, def_id: UUID):
        payload = request.get_json(silent=True) or {}
        result = self.admin_sub_pool_service.update_definition(def_id, payload)
        return success_json(result)

    @admin_login_required
    @permission_required("agent_pool:manage")
    def delete(self, def_id: UUID):
        self.admin_sub_pool_service.delete_definition(def_id)
        return success_message("删除子池定义成功")

    @admin_login_required
    @permission_required("agent_pool:manage")
    def set_status(self, def_id: UUID):
        payload = request.get_json(silent=True) or {}
        enabled = str(payload.get("enabled", "true")).lower() == "true"
        result = self.admin_sub_pool_service.set_enabled(def_id, enabled)
        return success_json(result)
