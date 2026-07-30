from dataclasses import dataclass
from uuid import UUID
from flask import request
from flask_login import current_user, login_required
from injector import inject

from internal.schema.workflow_schema import (
    CreateWorkflowReq,
    UpdateWorkflowReq,
    GetWorkflowResp,
    GetWorkflowsWithPageReq,
    GetWorkflowsWithPageResp,
    ImportWorkflowResp,
)
from internal.service import WorkflowRunService, WorkflowService
from pkg.paginator import PageModel
from pkg.response import validate_error_json, success_json, success_message, compact_generate_response


@inject
@dataclass
class WorkflowHandler:
    """工作流处理器"""
    workflow_service: WorkflowService
    workflow_run_service: WorkflowRunService

    @login_required
    def create_workflow(self):
        """新增工作流"""
        # 1.提取请求并校验
        req = CreateWorkflowReq()
        if not req.validate():
            return validate_error_json(req.errors)

        # 2.调用服务创建工作流
        workflow = self.workflow_service.create_workflow(req, current_user)

        return success_json({"id": workflow.id})

    @login_required
    def delete_workflow(self, workflow_id: UUID):
        """根据传递的工作流id删除指定的工作流"""
        self.workflow_service.delete_workflow(workflow_id, current_user)
        return success_message("删除工作流成功")

    @login_required
    def update_workflow(self, workflow_id: UUID):
        """根据传递的工作流id获取工作流详情"""
        # 1.提取请求并校验
        req = UpdateWorkflowReq()
        if not req.validate():
            return validate_error_json(req.errors)

        # 2.调用服务更新工作流数据
        self.workflow_service.update_workflow(workflow_id, current_user, **req.data)

        return success_message("修改工作流基础信息成功")

    @login_required
    def get_workflow(self, workflow_id: UUID):
        """根据传递的工作流id获取工作流详情"""
        workflow = self.workflow_service.get_workflow(workflow_id, current_user)
        resp = GetWorkflowResp()
        return success_json(resp.dump(workflow))

    @login_required
    def get_workflows_with_page(self):
        """获取当前登录账号下的工作流分页列表数据"""
        # 1.提取请求并校验
        req = GetWorkflowsWithPageReq(request.args)
        if not req.validate():
            return validate_error_json(req.errors)

        # 2.获取分页列表数据
        workflows, paginator = self.workflow_service.get_workflows_with_page(req, current_user)

        # 3.构建响应并返回
        resp = GetWorkflowsWithPageResp(many=True)

        return success_json(PageModel(list=resp.dump(workflows), paginator=paginator))

    @login_required
    def update_draft_graph(self, workflow_id: UUID):
        """根据传递的工作流id+请求信息更新工作流草稿图配置"""
        # 1.提取草稿图接口请求json数据
        draft_graph_dict = request.get_json(force=True, silent=True) or {
            "nodes": [],
            "edges": [],
        }

        # 2.调用服务更新工作流的草稿图配置
        self.workflow_service.update_draft_graph(workflow_id, draft_graph_dict, current_user)

        return success_message("更新工作流草稿配置成功")

    @login_required
    def get_draft_graph(self, workflow_id: UUID):
        """根据传递的工作流id获取该工作流的草稿配置信息"""
        draft_graph = self.workflow_service.get_draft_graph(workflow_id, current_user)
        return success_json(draft_graph)

    @login_required
    def debug_workflow(self, workflow_id: UUID):
        """根据传递的变量字典+工作流id调试指定的工作流"""
        # 1.提取用户传递的输入变量信息
        inputs = request.get_json(force=True, silent=True) or {}

        # 2.调用服务调试指定的API接口
        response = self.workflow_service.debug_workflow(workflow_id, inputs, current_user)

        return compact_generate_response(response)

    @login_required
    def publish_workflow(self, workflow_id: UUID):
        """根据传递的工作流id发布指定的工作流"""
        self.workflow_service.publish_workflow(workflow_id, current_user)
        return success_message("发布工作流成功")

    @login_required
    def cancel_publish_workflow(self, workflow_id: UUID):
        """根据传递的工作流id取消发布指定的工作流"""
        self.workflow_service.cancel_publish_workflow(workflow_id, current_user)
        return success_message("取消发布工作流成功")

    @login_required
    def regenerate_icon(self, workflow_id: UUID):
        """根据传递的工作流id重新生成工作流图标"""
        icon_url = self.workflow_service.regenerate_icon(workflow_id, current_user)
        return success_json({"icon": icon_url})

    @login_required
    def generate_icon_preview(self):
        """根据传递的名称和描述生成图标预览（不保存到工作流）"""
        # 1.获取请求数据
        data = request.get_json(force=True, silent=True) or {}
        name = data.get('name', '').strip()
        description = data.get('description', '').strip()

        # 2.校验名称不能为空
        if not name:
            return validate_error_json({'name': ['工作流名称不能为空']})

        # 3.调用服务生成图标
        icon_url = self.workflow_service.generate_icon_preview(name, description)

        return success_json({"icon": icon_url})

    @login_required
    def share_workflow_to_public(self, workflow_id: UUID):
        """分享或取消分享工作流到广场"""
        # 1.提取请求数据
        data = request.get_json(force=True, silent=True) or {}
        is_public = data.get("is_public", False)

        # 2.调用服务更新工作流公开状态
        self.workflow_service.share_workflow_to_public(workflow_id, current_user, is_public)

        message = "分享工作流到广场成功" if is_public else "取消分享工作流成功"
        return success_message(message)

    # ------------------------------------------------------------------
    # 工作流导入导出（阶段 6）
    # ------------------------------------------------------------------
    @login_required
    def export_workflow(self, workflow_id: UUID):
        """导出工作流为 JSON

        查询参数：
        - include_versions: 是否附带版本历史元数据（不含 graph 内容），默认 false
        """
        # 1.校验工作流归属当前账号
        self.workflow_service.get_workflow(workflow_id, current_user)

        # 2.解析查询参数
        include_versions = request.args.get("include_versions", "").lower() in ("true", "1", "yes")

        # 3.调用服务导出
        data = self.workflow_service.export_workflow(workflow_id, include_versions=include_versions)
        return success_json(data)

    @login_required
    def import_workflow(self):
        """导入工作流 JSON

        支持两种 body：
        1. 信封格式：{"json_data": {...}, "overwrite_name": false}
        2. 直接格式：直接 POST 导出的工作流 JSON（含 format=openagent-workflow 字段）
           此时 overwrite_name 从查询参数 ?overwrite_name=true 读取
        """
        # 1.解析请求 body
        body = request.get_json(force=True, silent=True)
        if not isinstance(body, dict):
            return validate_error_json({"json_data": ["请求体必须是 JSON 对象"]})

        # 2.判断是信封格式还是直接格式
        if "json_data" in body and isinstance(body.get("json_data"), dict):
            # 信封格式：从 body 中直接读取 json_data 与 overwrite_name
            json_data = body.get("json_data")
            overwrite_name = bool(body.get("overwrite_name", False))
        elif body.get("format") == "openagent-workflow":
            # 直接格式：body 本身就是导出的工作流 JSON
            json_data = body
            overwrite_name = request.args.get("overwrite_name", "").lower() in ("true", "1", "yes")
        else:
            return validate_error_json({"json_data": ["无法识别的导入数据格式，缺少 json_data 字段或 format 字段不正确"]})

        # 3.调用服务导入
        workflow = self.workflow_service.import_workflow(
            json_data=json_data,
            account_id=current_user.id,
            overwrite_name=overwrite_name,
        )

        # 4.返回新创建的工作流信息
        resp = ImportWorkflowResp()
        return success_json(resp.dump(workflow))

    # ------------------------------------------------------------------
    # 工作流执行历史（Plan B-11）
    # ------------------------------------------------------------------
    @login_required
    def get_workflow_runs_with_page(self, workflow_id: UUID):
        """分页查询工作流的执行历史记录。

        查询参数：
        - page: 当前页码，默认 1
        - page_size: 每页条数，默认 10
        - status: 可选状态过滤（running/succeeded/failed/stopped）
        - trigger_source: 可选触发源过滤（debug/app/schedule/api）
        """
        # 1.校验 workflow_id 归属当前账号（防止越权查询他人工作流的执行历史）
        self.workflow_service.get_workflow(workflow_id, current_user)

        # 2.提取分页参数
        page = request.args.get("page", default=1, type=int)
        page_size = request.args.get("page_size", default=10, type=int)
        status = request.args.get("status", default=None, type=str) or None
        trigger_source = request.args.get("trigger_source", default=None, type=str) or None

        # 3.查询分页数据
        runs, paginator = self.workflow_run_service.get_runs_with_page(
            workflow_id=workflow_id,
            account=current_user,
            page=page,
            page_size=page_size,
            status=status,
            trigger_source=trigger_source,
        )

        # 4.序列化并返回
        list_data = [self.workflow_run_service.serialize_run(run) for run in runs]
        return success_json(PageModel(list=list_data, paginator=paginator))

    @login_required
    def get_workflow_run(self, workflow_id: UUID, run_id: UUID):
        """获取单条执行记录详情。"""
        # 1.校验 workflow_id 归属当前账号
        self.workflow_service.get_workflow(workflow_id, current_user)

        # 2.查询执行记录
        run = self.workflow_run_service.get_run(run_id, current_user)
        if run is None:
            return success_json(None)

        return success_json(self.workflow_run_service.serialize_run(run))

    @login_required
    def get_workflow_run_node_executions(self, workflow_id: UUID, run_id: UUID):
        """获取执行记录的节点级回放数据。"""
        # 1.校验 workflow_id 归属当前账号
        self.workflow_service.get_workflow(workflow_id, current_user)

        # 2.查询节点执行记录
        node_executions = self.workflow_run_service.get_node_executions(run_id, current_user)

        # 3.序列化并返回
        list_data = [
            self.workflow_run_service.serialize_node_execution(node_exec)
            for node_exec in node_executions
        ]
        return success_json({"list": list_data})
