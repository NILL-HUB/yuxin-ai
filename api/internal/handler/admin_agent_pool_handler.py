from dataclasses import dataclass
from uuid import UUID

from flask import request
from injector import inject

from internal.middleware import admin_login_required, permission_required
from internal.schema.admin_agent_pool_schema import (
    AdminAgentPoolConfigPageResp,
    AdminAgentPoolConfigResp,
    AdminAgentPoolStatsResp,
    GetAdminAgentPoolConfigsReq,
    SetAdminAgentPoolConfigStatusReq,
)
from internal.service.admin_agent_pool_service import AdminAgentPoolService
from pkg.response import success_json, success_message, validate_error_json


@inject
@dataclass
class AdminAgentPoolHandler:
    admin_agent_pool_service: AdminAgentPoolService

    @admin_login_required
    @permission_required("agent_pool:read")
    def list(self):
        req = GetAdminAgentPoolConfigsReq(request.args)
        if not req.validate():
            return validate_error_json(req.errors)
        result = self.admin_agent_pool_service.list_configs(
            page=req.current_page.data,
            per_page=req.page_size.data,
            enabled=req.enabled.data,
            keyword=req.keyword.data,
        )
        resp = AdminAgentPoolConfigPageResp()
        return success_json(resp.dump(result))

    @admin_login_required
    @permission_required("agent_pool:manage")
    def create(self):
        payload = request.get_json(silent=True) or {}
        result = self.admin_agent_pool_service.create_config(payload)
        resp = AdminAgentPoolConfigResp()
        return success_json(resp.dump(result))

    @admin_login_required
    @permission_required("agent_pool:read")
    def get(self, config_id: UUID):
        resp = AdminAgentPoolConfigResp()
        return success_json(resp.dump(self.admin_agent_pool_service.get_config(config_id)))

    @admin_login_required
    @permission_required("agent_pool:manage")
    def update(self, config_id: UUID):
        payload = request.get_json(silent=True) or {}
        result = self.admin_agent_pool_service.update_config(config_id, payload)
        resp = AdminAgentPoolConfigResp()
        return success_json(resp.dump(result))

    @admin_login_required
    @permission_required("agent_pool:manage")
    def delete(self, config_id: UUID):
        self.admin_agent_pool_service.delete_config(config_id)
        return success_message("删除Agent池配置成功")

    @admin_login_required
    @permission_required("agent_pool:manage")
    def set_status(self, config_id: UUID):
        req = SetAdminAgentPoolConfigStatusReq()
        if not req.validate():
            return validate_error_json(req.errors)
        enabled = req.enabled.data == "true"
        result = self.admin_agent_pool_service.set_enabled(config_id, enabled)
        resp = AdminAgentPoolConfigResp()
        return success_json(resp.dump(result))

    @admin_login_required
    @permission_required("agent_pool:manage")
    def check_health(self, config_id: UUID):
        result = self.admin_agent_pool_service.check_health(config_id)
        resp = AdminAgentPoolConfigResp()
        return success_json(resp.dump(result))

    @admin_login_required
    @permission_required("agent_pool:read")
    def list_stats(self):
        result = self.admin_agent_pool_service.list_pool_stats()
        resp = AdminAgentPoolStatsResp()
        return success_json(resp.dump(result))
