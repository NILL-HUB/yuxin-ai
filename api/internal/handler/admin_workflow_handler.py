from dataclasses import dataclass
from uuid import UUID

from flask import g, request
from injector import inject

from internal.extension.database_extension import db
from internal.middleware import admin_login_required, permission_required
from internal.model import Account
from internal.schema.admin_workflow_schema import (
    AdminWorkflowPageResp,
    AdminWorkflowResp,
    GetAdminWorkflowsReq,
    UpdateAdminWorkflowReq,
)
from internal.schema.workflow_schema import CreateWorkflowReq
from internal.service import WorkflowService
from internal.service.admin_workflow_service import AdminWorkflowService
from pkg.response import success_json, success_message, validate_error_json


@inject
@dataclass
class AdminWorkflowHandler:
    admin_workflow_service: AdminWorkflowService
    workflow_service: WorkflowService

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
    @permission_required("workflow:create")
    def create(self):
        """创建工作流（归属到管理员绑定的空间账号，复用空间端服务）"""
        req = CreateWorkflowReq()
        if not req.validate():
            return validate_error_json(req.errors)

        account = self._get_admin_account()
        workflow = self.workflow_service.create_workflow(req, account)
        return success_json({"id": str(workflow.id)})

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
    @permission_required("workflow:delete")
    def delete(self, workflow_id: UUID):
        """删除工作流（管理员视角，不校验账号归属）"""
        self.workflow_service.delete_workflow_for_admin(workflow_id)
        return success_message("删除工作流成功")

    @admin_login_required
    @permission_required("workflow:read")
    def get_draft_graph(self, workflow_id: UUID):
        """获取工作流草稿图（管理员视角，复用空间端服务）"""
        draft_graph = self.workflow_service.get_draft_graph_for_admin(workflow_id)
        return success_json(draft_graph)

    @admin_login_required
    @permission_required("workflow:update")
    def update_draft_graph(self, workflow_id: UUID):
        """保存工作流草稿图（管理员视角，复用空间端服务）"""
        draft_graph_dict = request.get_json(force=True, silent=True) or {
            "nodes": [],
            "edges": [],
        }
        self.workflow_service.update_draft_graph_for_admin(workflow_id, draft_graph_dict)
        return success_message("更新工作流草稿配置成功")

    @admin_login_required
    @permission_required("workflow:update")
    def publish(self, workflow_id: UUID):
        """发布工作流（管理员视角，复用空间端服务）"""
        self.workflow_service.publish_workflow_for_admin(workflow_id)
        return success_message("发布工作流成功")

    @admin_login_required
    @permission_required("workflow:update")
    def offline(self, workflow_id: UUID):
        self.admin_workflow_service.offline_workflow(workflow_id)
        return success_message("下架工作流成功")

    def _get_admin_account(self) -> Account:
        """获取管理员绑定的空间账号，作为资源的归属账号"""
        account_id = g.current_admin_user.get("account_id")
        if not account_id:
            raise ValueError("管理员账号未关联空间账号，请先在 RBAC 管理中绑定")
        account = db.session.get(Account, account_id)
        if not account:
            raise ValueError("管理员关联的空间账号不存在")
        return account
