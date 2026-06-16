from dataclasses import dataclass
from uuid import UUID

from flask import request
from injector import inject

from internal.middleware import admin_login_required, permission_required
from internal.schema.admin_routing_log_schema import (
    GetRoutingLogsReq,
    RoutingLogPageResp,
)
from internal.service.routing_log_service import RoutingLogService
from pkg.response import success_json, validate_error_json


@inject
@dataclass
class AdminRoutingLogHandler:
    routing_log_service: RoutingLogService

    @admin_login_required
    @permission_required("routing_log:read")
    def list(self):
        req = GetRoutingLogsReq(request.args)
        if not req.validate():
            return validate_error_json(req.errors)
        result = self.routing_log_service.page(
            page=req.current_page.data,
            page_size=req.page_size.data,
            account_id=UUID(req.account_id.data) if req.account_id.data else None,
            status=req.status.data or None,
            agent_id=req.agent_id.data or None,
            agent_pool=req.agent_pool.data or None,
            tool_name=req.tool_name.data or None,
            tool_pool=req.tool_pool.data or None,
            model_id=req.model_id.data or None,
            key_id=req.key_id.data or None,
            start_at=req.start_at.data or None,
            end_at=req.end_at.data or None,
        )
        return success_json(RoutingLogPageResp().dump(result))
