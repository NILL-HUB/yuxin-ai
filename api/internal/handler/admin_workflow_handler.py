from dataclasses import dataclass
from uuid import UUID

from flask import request
from injector import inject

from internal.middleware import admin_login_required, permission_required
from internal.schema.admin_workflow_schema import (
    AdminWorkflowPageResp,
    AdminWorkflowResp,
    GetAdminWorkflowsReq,
    UpdateAdminWorkflowReq,
)
from internal.service.admin_workflow_service import AdminWorkflowService
from pkg.response import success_json, success_message, validate_error_json


@inject
@dataclass
class AdminWorkflowHandler:
    admin_workflow_service: AdminWorkflowService

    @admin_login_required
    @permission_required("workflow:read")
    def list(self):
        req = GetAdminWorkflowsReq(request.args)
        if not req.validate():
            return validate_error_json(req.errors)
        result = self.admin_workflow_service.list_workflows(
            search=req.search.data,
            status=req.status.data,
            current_page=req.current_page.data,
            page_size=req.page_size.data,
        )
        resp = AdminWorkflowPageResp()
        return success_json(resp.dump(result))

    @admin_login_required
    @permission_required("workflow:read")
    def get(self, workflow_id: UUID):
        resp = AdminWorkflowResp()
        return success_json(resp.dump(self.admin_workflow_service.get_workflow(workflow_id)))

    @admin_login_required
    @permission_required("workflow:update")
    def update(self, workflow_id: UUID):
        req = UpdateAdminWorkflowReq()
        if not req.validate():
            return validate_error_json(req.errors)
        payload = request.get_json(silent=True) or {}
        result = self.admin_workflow_service.update_workflow(
            workflow_id,
            status=req.status.data,
            is_public=payload.get("is_public") if "is_public" in payload else None,
        )
        resp = AdminWorkflowResp()
        return success_json(resp.dump(result))

    @admin_login_required
    @permission_required("workflow:update")
    def offline(self, workflow_id: UUID):
        self.admin_workflow_service.offline_workflow(workflow_id)
        return success_message("下架工作流成功")
